"""One customer payment can be split across several debts."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class DebtAllocationTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "debt.db")
        os.environ["MBT_DATA_ROOT"] = self._tmpdir.name
        os.environ["APPDATA"] = self._tmpdir.name
        os.environ["LOCALAPPDATA"] = self._tmpdir.name
        os.environ["PROGRAMDATA"] = self._tmpdir.name
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("admin", ac._hash_pw("admin-pass"), "admin", "Admin"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("viewer", ac._hash_pw("viewer-pass"), "viewer", "Viewer"),
        )
        db.execute("INSERT INTO customers (name, phone, is_active) VALUES ('Test Customer', '0700', 1)")
        db.commit()
        self.customer = db.execute("SELECT id FROM customers").fetchone()["id"]
        db.close()
        self.api = ac.APIClient()
        self.api._role = "admin"
        self.api._user_id = 1
        self.api._username = "admin"

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _debt(self, amount, when, receipt):
        db = self.ac._db()
        db.execute(
            "INSERT INTO sales (receipt_number, total, status, sale_date, created_at) VALUES (?,?,?,?,?)",
            (receipt, amount, "completed", when[:10], when),
        )
        sale_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            "INSERT INTO debt_invoices (invoice_number, sale_id, receipt_number, customer_id, "
            "customer_name, total_amount, amount_paid, balance, status, created_at) "
            "VALUES (?,?,?,?,?,?,0,?,'pending',?)",
            (f"INV-{receipt}", sale_id, receipt, self.customer, "Test Customer", amount, amount, when),
        )
        invoice_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()
        return invoice_id

    def _open(self):
        db = self.ac._db()
        rows = db.execute(
            "SELECT receipt_number, balance, status FROM debt_invoices ORDER BY created_at, id"
        ).fetchall()
        wallet = db.execute(
            "SELECT balance FROM customer_wallet WHERE customer_id=?", (self.customer,)
        ).fetchone()
        collections = db.execute("SELECT COUNT(*) AS c, COALESCE(SUM(amount),0) AS s FROM debt_collections").fetchone()
        payments = db.execute(
            "SELECT COUNT(*) AS c, COALESCE(SUM(amount),0) AS s FROM debt_payments WHERE COALESCE(reversed,0)=0"
        ).fetchone()
        db.close()
        return (
            [(row["receipt_number"], round(float(row["balance"]), 2), row["status"]) for row in rows],
            round(float(wallet["balance"]), 2) if wallet else 0.0,
            int(collections["c"]),
            round(float(collections["s"] or 0), 2),
            int(payments["c"]),
            round(float(payments["s"] or 0), 2),
        )

    def test_oldest_debt_first_splits_one_collection(self):
        self._debt(40, "2026-01-01T08:00:00", "RCP-A")
        self._debt(60, "2026-01-02T08:00:00", "RCP-B")
        result = self.api.collect_customer_payment(self.customer, 50, client_token="pay-50")
        self.assertTrue(result.get("success"), result)
        self.assertEqual(result.get("allocated"), 50)
        self.assertEqual(result.get("unapplied"), 0)
        self.assertEqual(len(result.get("allocations") or []), 2)
        balances, credit, collections, collected, payments, paid = self._open()
        self.assertEqual(balances, [("RCP-A", 0.0, "paid"), ("RCP-B", 50.0, "partial")])
        self.assertEqual(credit, 0)
        self.assertEqual(collections, 1)
        self.assertEqual(collected, 50)
        self.assertEqual(payments, 2)
        self.assertEqual(paid, 50)

    def test_twenty_leaves_the_oldest_debt_partial(self):
        self._debt(40, "2026-01-01T08:00:00", "RCP-A")
        self._debt(60, "2026-01-02T08:00:00", "RCP-B")
        self._debt(150, "2026-01-03T08:00:00", "RCP-C")
        result = self.api.collect_customer_payment(self.customer, 20, client_token="pay-20")
        self.assertTrue(result.get("success"), result)
        balances, *_rest = self._open()
        self.assertEqual(balances, [
            ("RCP-A", 20.0, "partial"),
            ("RCP-B", 60.0, "pending"),
            ("RCP-C", 150.0, "pending"),
        ])
        self.assertEqual(sum(item[1] for item in balances), 230)

    def test_manual_allocation_pays_the_chosen_receipt(self):
        first = self._debt(40, "2026-01-01T08:00:00", "RCP-A")
        second = self._debt(60, "2026-01-02T08:00:00", "RCP-B")
        result = self.api.collect_customer_payment(
            self.customer, 50, mode="manual",
            allocations=[{"invoice_id": second, "amount": 50}],
            client_token="pay-manual",
        )
        self.assertTrue(result.get("success"), result)
        balances, *_rest = self._open()
        self.assertEqual(balances, [("RCP-A", 40.0, "pending"), ("RCP-B", 10.0, "partial")])
        self.assertNotEqual(first, second)

    def test_manual_allocation_can_cover_several_receipts(self):
        a = self._debt(40, "2026-01-01T08:00:00", "RCP-A")
        b = self._debt(60, "2026-01-02T08:00:00", "RCP-B")
        c = self._debt(150, "2026-01-03T08:00:00", "RCP-C")
        result = self.api.collect_customer_payment(
            self.customer, 100, mode="manual",
            allocations=[
                {"invoice_id": a, "amount": 10},
                {"invoice_id": b, "amount": 20},
                {"invoice_id": c, "amount": 70},
            ],
            client_token="pay-split-debts",
        )
        self.assertTrue(result.get("success"), result)
        balances, *_rest = self._open()
        self.assertEqual([item[1] for item in balances], [30.0, 40.0, 80.0])
        self.assertEqual(sum(item["amount"] for item in result["allocations"]), 100)

    def test_several_payments_against_one_debt_stay_separate(self):
        self._debt(100, "2026-01-01T08:00:00", "RCP-A")
        for amount, token in ((20, "p1"), (30, "p2"), (10, "p3")):
            result = self.api.collect_customer_payment(self.customer, amount, client_token=token)
            self.assertTrue(result.get("success"), result)
        balances, _credit, collections, collected, payments, paid = self._open()
        self.assertEqual(balances, [("RCP-A", 40.0, "partial")])
        self.assertEqual(collections, 3)
        self.assertEqual(collected, 60)
        self.assertEqual(payments, 3)
        self.assertEqual(paid, 60)

    def test_split_tender_is_one_collection(self):
        self._debt(40, "2026-01-01T08:00:00", "RCP-A")
        self._debt(60, "2026-01-02T08:00:00", "RCP-B")
        result = self.api.collect_customer_payment(
            self.customer, 50,
            methods=[{"method": "cash", "amount": 20}, {"method": "mpesa", "amount": 30}],
            client_token="split",
        )
        self.assertTrue(result.get("success"), result)
        self.assertEqual(result.get("amount"), 50)
        self.assertEqual(result.get("methods"), [
            {"method": "cash", "amount": 20},
            {"method": "mpesa", "amount": 30},
        ])
        _balances, _credit, collections, collected, payments, paid = self._open()
        self.assertEqual(collections, 1)
        self.assertEqual(collected, 50)
        self.assertEqual(paid, 50)
        self.assertEqual(payments, 2)

    def test_overpayment_becomes_customer_credit_not_negative_debt(self):
        self._debt(100, "2026-01-01T08:00:00", "RCP-A")
        result = self.api.collect_customer_payment(self.customer, 120, client_token="over")
        self.assertTrue(result.get("success"), result)
        self.assertEqual(result.get("allocated"), 100)
        self.assertEqual(result.get("unapplied"), 20)
        balances, credit, *_rest = self._open()
        self.assertEqual(balances, [("RCP-A", 0.0, "paid")])
        self.assertEqual(credit, 20)
        later = self._debt(30, "2026-02-01T08:00:00", "RCP-D")
        applied = self.api.collect_customer_payment(
            self.customer, 20, mode="manual", from_credit=True,
            allocations=[{"invoice_id": later, "amount": 20}],
            client_token="apply-credit",
        )
        self.assertTrue(applied.get("success"), applied)
        balances, credit, *_rest = self._open()
        self.assertEqual(balances[1], ("RCP-D", 10.0, "partial"))
        self.assertEqual(credit, 0)

    def test_reversal_restores_every_allocation(self):
        self._debt(40, "2026-01-01T08:00:00", "RCP-A")
        self._debt(60, "2026-01-02T08:00:00", "RCP-B")
        paid = self.api.collect_customer_payment(self.customer, 50, client_token="to-reverse")
        self.assertTrue(paid.get("success"), paid)
        reversed_payment = self.api.reverse_debt_collection(paid["collection_id"], "Customer returned the cash")
        self.assertTrue(reversed_payment.get("success"), reversed_payment)
        balances, credit, collections, _collected, payments, _paid = self._open()
        self.assertEqual(balances, [("RCP-A", 40.0, "pending"), ("RCP-B", 60.0, "pending")])
        self.assertEqual(credit, 0)
        self.assertEqual(collections, 1)
        self.assertEqual(payments, 0)
        again = self.api.reverse_debt_collection(paid["collection_id"], "Customer returned the cash")
        self.assertIn("already", again.get("error", "").lower())

    def test_duplicate_token_does_not_collect_twice(self):
        self._debt(40, "2026-01-01T08:00:00", "RCP-A")
        first = self.api.collect_customer_payment(self.customer, 10, client_token="same")
        second = self.api.collect_customer_payment(self.customer, 10, client_token="same")
        self.assertTrue(first.get("success"), first)
        self.assertTrue(second.get("duplicate"), second)
        balances, _credit, collections, collected, *_rest = self._open()
        self.assertEqual(balances, [("RCP-A", 30.0, "partial")])
        self.assertEqual(collections, 1)
        self.assertEqual(collected, 10)

    def test_concurrent_payments_cannot_allocate_more_than_the_debt(self):
        self._debt(100, "2026-01-01T08:00:00", "RCP-A")
        barrier = threading.Barrier(2)
        results = []

        def pay(token):
            api = self.ac.APIClient()
            api._role = "admin"
            api._user_id = 1
            api._username = "admin"
            barrier.wait()
            results.append(api.collect_customer_payment(self.customer, 100, client_token=token))

        threads = [threading.Thread(target=pay, args=(f"concurrent-{i}",)) for i in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue(all(item.get("success") for item in results), results)
        balances, credit, _collections, collected, _payments, paid = self._open()
        self.assertEqual(balances, [("RCP-A", 0.0, "paid")])
        self.assertEqual(paid, 100)
        self.assertEqual(credit, 100)
        self.assertEqual(collected, 200)

    def test_statement_shows_the_allocation_and_blocks_a_viewer(self):
        self._debt(40, "2026-01-01T08:00:00", "RCP-A")
        self._debt(60, "2026-01-02T08:00:00", "RCP-B")
        self.api.collect_customer_payment(self.customer, 50, client_token="statement")
        statement = self.api.get_customer_statement(self.customer)
        self.assertEqual(statement.get("outstanding"), 50)
        self.assertEqual(len(statement["collections"]), 1)
        self.assertEqual(len(statement["collections"][0]["allocations"]), 2)
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        client = appmod.app.test_client()
        login = client.post("/api/auth/login", json={"username": "viewer", "password": "viewer-pass"})
        self.assertEqual(login.status_code, 200, login.get_json())
        headers = {"Authorization": f"Bearer {login.get_json()['token']}"}
        denied = client.post(
            f"/api/debt/customers/{self.customer}/collect",
            headers=headers,
            json={"amount": 10, "client_token": "viewer"},
        )
        self.assertEqual(denied.status_code, 403, denied.get_json())

    def test_manual_under_allocation_is_rejected_while_debt_remains(self):
        second = self._debt(60, "2026-01-02T08:00:00", "RCP-B")
        self._debt(40, "2026-01-01T08:00:00", "RCP-A")
        result = self.api.collect_customer_payment(
            self.customer, 50, mode="manual",
            allocations=[{"invoice_id": second, "amount": 20}],
            client_token="short",
        )
        self.assertIn("not allocated", result.get("error", ""))
        balances, *_rest = self._open()
        self.assertEqual([item[1] for item in balances], [40.0, 60.0])


if __name__ == "__main__":
    unittest.main()
