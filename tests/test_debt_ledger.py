"""Debt stays linked to a sale and payments cannot exceed or double-count it."""
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


class DebtLedgerTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "debt.db")
        os.environ["MBT_DATA_ROOT"] = self._tmpdir.name
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
            ("cashier", ac._hash_pw("cashier-pass"), "cashier", "Cashier"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("viewer", ac._hash_pw("viewer-pass"), "viewer", "Viewer"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("admin", ac._hash_pw("admin-pass"), "admin", "Admin"),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, is_active) VALUES (?,?,?,?,?,1)",
            ("QA Debt", "QA-DEBT", 100, 40, 40),
        )
        db.execute("INSERT INTO customers (name, phone, is_active) VALUES ('QA Debtor', '0700', 1)")
        db.commit()
        self.product = db.execute("SELECT id FROM products").fetchone()["id"]
        self.customer = db.execute("SELECT id FROM customers").fetchone()["id"]
        db.close()
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        self.client = appmod.app.test_client()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _headers(self, username, password):
        response = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.get_json())
        return {"Authorization": f"Bearer {response.get_json()['token']}"}

    def _credit(self, headers, token, tenders):
        return self.client.post("/api/sales", headers=headers, json={
            "items": [{"product_id": self.product, "quantity": 10, "unit_price": 100}],
            "subtotal": 1000, "total": 1000,
            "payment_method": "Mixed",
            "payment_tenders": tenders,
            "customer_id": self.customer,
            "client_token": token,
        })

    def test_orphan_debt_is_rejected_and_repayments_settle_once(self):
        cashier = self._headers("cashier", "cashier-pass")
        viewer = self._headers("viewer", "viewer-pass")
        orphan = self.client.post("/api/debt/invoices", headers=cashier, json={
            "customer_id": self.customer, "total_amount": 500,
        })
        self.assertEqual(orphan.status_code, 400, orphan.get_json())
        sale = self._credit(cashier, "debt-1", [
            {"method": "Cash", "amount": 400},
            {"method": "Credit", "amount": 600},
        ])
        self.assertEqual(sale.status_code, 200, sale.get_json())
        invoice = sale.get_json()["debt"]["invoice_id"]
        db = self.ac._db()
        try:
            opening = db.execute(
                "SELECT payment_method, amount FROM debt_payments WHERE invoice_id=? ORDER BY id",
                (invoice,),
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(opening["payment_method"], "Cash")
        self.assertEqual(float(opening["amount"]), 400)
        denied = self.client.post(f"/api/debt/invoices/{invoice}/pay", headers=viewer, json={"amount": 100})
        self.assertEqual(denied.status_code, 403, denied.get_json())
        balances = []
        for amount, ref in ((100, "R1"), (150, "R1"), (150, "R2"), (350, "R3")):
            paid = self.client.post(f"/api/debt/invoices/{invoice}/pay", headers=cashier, json={
                "amount": amount, "payment_method": "cash", "payment_reference": ref,
            })
            balances.append((paid.status_code, (paid.get_json() or {}).get("balance_after"), (paid.get_json() or {}).get("duplicate")))
        self.assertEqual(balances[0][0], 200)
        self.assertEqual(balances[0][1], 500)
        self.assertTrue(balances[1][2])
        self.assertEqual(balances[1][1], 500)
        self.assertEqual(balances[2][1], 350)
        self.assertEqual(balances[3][1], 0)
        over = self.client.post(f"/api/debt/invoices/{invoice}/pay", headers=cashier, json={"amount": 1, "payment_reference": "R4"})
        self.assertEqual(over.status_code, 400, over.get_json())
        db = self.ac._db()
        try:
            row = db.execute("SELECT balance, status FROM debt_invoices WHERE id=?", (invoice,)).fetchone()
            pays = db.execute("SELECT COUNT(*) AS c FROM debt_payments WHERE invoice_id=?", (invoice,)).fetchone()["c"]
        finally:
            db.close()
        self.assertEqual(float(row["balance"]), 0)
        self.assertEqual(row["status"], "paid")
        self.assertEqual(pays, 4)

    def test_reversing_one_repayment_restores_only_that_amount(self):
        cashier = self._headers("cashier", "cashier-pass")
        admin = self._headers("admin", "admin-pass")
        sale = self._credit(cashier, "debt-reverse", [
            {"method": "Credit", "amount": 1000},
        ])
        self.assertEqual(sale.status_code, 200, sale.get_json())
        body = sale.get_json()
        invoice = body["debt"]["invoice_id"]
        sale_id = body["sale_id"]
        first = self.client.post(f"/api/debt/invoices/{invoice}/pay", headers=cashier, json={
            "amount": 250, "payment_method": "cash", "payment_reference": "KEEP",
        })
        second = self.client.post(f"/api/debt/invoices/{invoice}/pay", headers=cashier, json={
            "amount": 250, "payment_method": "M-Pesa", "payment_reference": "UNDO",
        })
        self.assertEqual(first.status_code, 200, first.get_json())
        self.assertEqual(second.status_code, 200, second.get_json())
        self.assertEqual(second.get_json()["balance_after"], 500)
        db = self.ac._db()
        try:
            payment_id = db.execute(
                "SELECT id FROM debt_payments WHERE invoice_id=? AND payment_reference='UNDO'",
                (invoice,),
            ).fetchone()["id"]
            stock_before = db.execute("SELECT stock FROM products WHERE id=?", (self.product,)).fetchone()["stock"]
        finally:
            db.close()
        denied = self.client.post(f"/api/debt-payments/{payment_id}/reverse", headers=cashier, json={
            "reason": "Cashier must not reverse this",
        })
        self.assertEqual(denied.status_code, 403, denied.get_json())
        reversed_pay = self.client.post(f"/api/debt-payments/{payment_id}/reverse", headers=admin, json={
            "reason": "The M-Pesa entry was never received",
            "money_outcome": "never_received",
            "client_token": "reverse-once",
        })
        self.assertEqual(reversed_pay.status_code, 200, reversed_pay.get_json())
        self.assertEqual(reversed_pay.get_json()["balance"], 750)
        again = self.client.post(f"/api/debt-payments/{payment_id}/reverse", headers=admin, json={
            "reason": "The M-Pesa entry was never received",
            "client_token": "reverse-once",
        })
        self.assertEqual(again.status_code, 200, again.get_json())
        self.assertTrue(again.get_json().get("duplicate"))
        db = self.ac._db()
        try:
            row = db.execute(
                "SELECT balance, status FROM debt_invoices WHERE id=?", (invoice,),
            ).fetchone()
            sale_row = db.execute("SELECT status FROM sales WHERE id=?", (sale_id,)).fetchone()
            kept = db.execute(
                "SELECT COALESCE(reversed,0) AS reversed FROM debt_payments WHERE payment_reference='KEEP'",
            ).fetchone()
            undone = db.execute(
                "SELECT COALESCE(reversed,0) AS reversed FROM debt_payments WHERE id=?",
                (payment_id,),
            ).fetchone()
            stock_after = db.execute("SELECT stock FROM products WHERE id=?", (self.product,)).fetchone()["stock"]
            refunds = db.execute("SELECT COUNT(*) AS c FROM debt_refunds").fetchone()["c"]
        finally:
            db.close()
        self.assertEqual(float(row["balance"]), 750)
        self.assertEqual(sale_row["status"], "completed")
        self.assertEqual(int(kept["reversed"]), 0)
        self.assertEqual(int(undone["reversed"]), 1)
        self.assertEqual(stock_after, stock_before)
        self.assertEqual(refunds, 0)

    def test_cancelling_a_partly_paid_sale_clears_the_debt_and_restores_only_the_chosen_stock(self):
        cashier = self._headers("cashier", "cashier-pass")
        admin = self._headers("admin", "admin-pass")
        sale = self._credit(cashier, "debt-cancel", [
            {"method": "Cash", "amount": 400},
            {"method": "Credit", "amount": 600},
        ])
        self.assertEqual(sale.status_code, 200, sale.get_json())
        body = sale.get_json()
        invoice = body["debt"]["invoice_id"]
        sale_id = body["sale_id"]
        db = self.ac._db()
        try:
            stock_before = db.execute("SELECT stock FROM products WHERE id=?", (self.product,)).fetchone()["stock"]
        finally:
            db.close()
        denied = self.client.post(f"/api/debts/{invoice}/cancel-sale", headers=cashier, json={
            "reason": "Cashier must not cancel this",
            "refund_status": "pending",
        })
        self.assertEqual(denied.status_code, 403, denied.get_json())
        missing = self.client.post(f"/api/debts/{invoice}/cancel-sale", headers=admin, json={
            "reason": "Wrong sale, goods not all back",
            "refund_status": "none",
            "restore": [{"product_id": self.product, "quantity": 0}],
        })
        self.assertEqual(missing.status_code, 400, missing.get_json())
        cancelled = self.client.post(f"/api/debts/{invoice}/cancel-sale", headers=admin, json={
            "reason": "Wrong sale, goods not all back",
            "refund_status": "pending",
            "restore": [{"product_id": self.product, "quantity": 4}],
            "client_token": "cancel-once",
        })
        self.assertEqual(cancelled.status_code, 200, cancelled.get_json())
        self.assertEqual(cancelled.get_json()["outstanding"], 0)
        self.assertEqual(cancelled.get_json()["money_received"], 400)
        self.assertEqual(cancelled.get_json()["stock_restored"], [
            {"product_id": self.product, "quantity": 4, "stock_after": stock_before + 4},
        ])
        again = self.client.post(f"/api/debts/{invoice}/cancel-sale", headers=admin, json={
            "reason": "Wrong sale, goods not all back",
            "refund_status": "pending",
            "client_token": "cancel-once",
        })
        self.assertEqual(again.status_code, 200, again.get_json())
        self.assertTrue(again.get_json().get("duplicate"))
        db = self.ac._db()
        try:
            sale_row = db.execute("SELECT status FROM sales WHERE id=?", (sale_id,)).fetchone()
            debt = db.execute("SELECT balance, status FROM debt_invoices WHERE id=?", (invoice,)).fetchone()
            stock_after = db.execute("SELECT stock FROM products WHERE id=?", (self.product,)).fetchone()["stock"]
            pending = db.execute(
                "SELECT amount, status FROM debt_refunds WHERE invoice_id=?", (invoice,),
            ).fetchone()
            payments = db.execute("SELECT COUNT(*) AS c FROM debt_payments WHERE invoice_id=?", (invoice,)).fetchone()["c"]
        finally:
            db.close()
        self.assertEqual(sale_row["status"], "voided")
        self.assertEqual(float(debt["balance"]), 0)
        self.assertEqual(debt["status"], "cancelled")
        self.assertEqual(stock_after, stock_before + 4)
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(float(pending["amount"]), 400)
        self.assertEqual(payments, 1)

    def test_write_off_reduces_the_debt_and_leaves_the_sale(self):
        from desktop.utils.security import _pin_hash
        cashier = self._headers("cashier", "cashier-pass")
        admin = self._headers("admin", "admin-pass")
        db = self.ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("super", self.ac._hash_pw("super-pass"), "superadmin", "Super"),
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('superadmin_pin_hash', ?)",
            (_pin_hash("246810"),),
        )
        db.commit()
        db.close()
        super_headers = self._headers("super", "super-pass")
        sale = self._credit(cashier, "debt-writeoff", [{"method": "Credit", "amount": 1000}])
        self.assertEqual(sale.status_code, 200, sale.get_json())
        invoice = sale.get_json()["debt"]["invoice_id"]
        sale_id = sale.get_json()["sale_id"]
        db = self.ac._db()
        try:
            stock_before = db.execute("SELECT stock FROM products WHERE id=?", (self.product,)).fetchone()["stock"]
            payments_before = db.execute("SELECT COUNT(*) AS c FROM debt_payments").fetchone()["c"]
        finally:
            db.close()
        denied = self.client.post(f"/api/debts/{invoice}/write-off", headers=admin, json={
            "amount": 300, "reason": "Admin cannot write this off", "pin": "246810",
        })
        self.assertEqual(denied.status_code, 403, denied.get_json())
        partial = self.client.post(f"/api/debts/{invoice}/write-off", headers=super_headers, json={
            "amount": 300, "reason": "Approved partial waiver", "pin": "246810",
            "client_token": "write-300",
        })
        self.assertEqual(partial.status_code, 200, partial.get_json())
        self.assertEqual(partial.get_json()["balance"], 700)
        self.assertFalse(partial.get_json().get("cash_receipt"))
        full = self.client.post(f"/api/debts/{invoice}/write-off", headers=super_headers, json={
            "amount": 700, "reason": "Forgive the rest", "pin": "246810",
            "client_token": "write-700",
        })
        self.assertEqual(full.status_code, 200, full.get_json())
        self.assertEqual(full.get_json()["balance"], 0)
        self.assertEqual(full.get_json()["status"], "written_off")
        db = self.ac._db()
        try:
            sale_row = db.execute("SELECT status FROM sales WHERE id=?", (sale_id,)).fetchone()
            stock_after = db.execute("SELECT stock FROM products WHERE id=?", (self.product,)).fetchone()["stock"]
            payments_after = db.execute("SELECT COUNT(*) AS c FROM debt_payments").fetchone()["c"]
            written = db.execute("SELECT SUM(amount) AS total FROM debt_write_offs WHERE invoice_id=?", (invoice,)).fetchone()
        finally:
            db.close()
        self.assertEqual(sale_row["status"], "completed")
        self.assertEqual(stock_after, stock_before)
        self.assertEqual(payments_after, payments_before)
        self.assertEqual(float(written["total"]), 1000)

    def test_return_keeps_the_invoice_arithmetic(self):
        admin = self._headers("admin", "admin-pass")
        sale = self._credit(admin, "debt-return", [
            {"method": "Cash", "amount": 400},
            {"method": "Credit", "amount": 600},
        ])
        sale_id = sale.get_json()["sale_id"]
        db = self.ac._db()
        line_id = db.execute("SELECT id FROM sale_items WHERE sale_id=?", (sale_id,)).fetchone()["id"]
        db.close()
        returned = self.client.post(f"/api/sales/{sale_id}/return", headers=admin, json={
            "items": [{"sale_item_id": line_id, "quantity": 2}],
            "reason": "Two units returned",
            "refund_method": "cash",
            "client_token": "return-once",
        })
        self.assertEqual(returned.status_code, 200, returned.get_json())
        db = self.ac._db()
        try:
            row = db.execute(
                "SELECT total_amount, amount_paid, balance FROM debt_invoices WHERE sale_id=?",
                (sale_id,),
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(float(row["balance"]), 400)
        self.assertEqual(float(row["total_amount"]), 800)
        self.assertAlmostEqual(float(row["amount_paid"]) + float(row["balance"]), float(row["total_amount"]), places=2)

    def test_failed_debt_write_rolls_the_sale_back(self):
        cashier = self._headers("cashier", "cashier-pass")
        self.ac.APIClient._test_fault = "debt-insert"
        try:
            sale = self._credit(cashier, "debt-fault", [
                {"method": "Cash", "amount": 400},
                {"method": "Credit", "amount": 600},
            ])
        finally:
            self.ac.APIClient._test_fault = None
        self.assertNotEqual(sale.status_code, 200, sale.get_json())
        db = self.ac._db()
        try:
            sales = db.execute("SELECT COUNT(*) AS c FROM sales").fetchone()["c"]
            debts = db.execute("SELECT COUNT(*) AS c FROM debt_invoices").fetchone()["c"]
            stock = db.execute("SELECT stock FROM products WHERE id=?", (self.product,)).fetchone()["stock"]
        finally:
            db.close()
        self.assertEqual(sales, 0)
        self.assertEqual(debts, 0)
        self.assertEqual(float(stock), 40)

    def test_failed_payment_commit_leaves_the_balance(self):
        cashier = self._headers("cashier", "cashier-pass")
        sale = self._credit(cashier, "pay-fault", [
            {"method": "Credit", "amount": 1000},
        ])
        invoice = sale.get_json()["debt"]["invoice_id"]
        self.ac.APIClient._test_fault = "payment-commit"
        try:
            paid = self.client.post(f"/api/debt/invoices/{invoice}/pay", headers=cashier, json={
                "amount": 100, "payment_reference": "FAIL-1",
            })
        finally:
            self.ac.APIClient._test_fault = None
        self.assertEqual(paid.status_code, 400, paid.get_json())
        retry = self.client.post(f"/api/debt/invoices/{invoice}/pay", headers=cashier, json={
            "amount": 100, "payment_reference": "FAIL-1",
        })
        self.assertEqual(retry.status_code, 200, retry.get_json())
        self.assertEqual(retry.get_json()["balance_after"], 900)
        db = self.ac._db()
        try:
            count = db.execute(
                "SELECT COUNT(*) AS c FROM debt_payments WHERE payment_reference=?",
                ("FAIL-1",),
            ).fetchone()["c"]
        finally:
            db.close()
        self.assertEqual(count, 1)

    def test_two_collectors_cannot_overpay_one_balance(self):
        cashier = self._headers("cashier", "cashier-pass")
        sale = self._credit(cashier, "race", [{"method": "Credit", "amount": 1000}])
        invoice = sale.get_json()["debt"]["invoice_id"]
        first = self.client.post(f"/api/debt/invoices/{invoice}/pay", headers=cashier, json={
            "amount": 700, "payment_reference": "RACE-BASE",
        })
        self.assertEqual(first.get_json()["balance_after"], 300)
        results = []

        def collect(ref):
            api = self.ac.APIClient()
            api._user_id = 1
            api._username = "cashier"
            api._role = "cashier"
            results.append(api.record_debt_payment(invoice, 200, payment_reference=ref))

        threads = [threading.Thread(target=collect, args=(f"RACE-{n}",)) for n in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        accepted = [row for row in results if row.get("success") and not row.get("duplicate")]
        self.assertEqual(len(accepted), 1, results)
        db = self.ac._db()
        try:
            balance = db.execute("SELECT balance FROM debt_invoices WHERE id=?", (invoice,)).fetchone()["balance"]
            taken = db.execute(
                "SELECT COALESCE(SUM(amount),0) AS s FROM debt_payments WHERE invoice_id=? AND payment_reference LIKE 'RACE-%'",
                (invoice,),
            ).fetchone()["s"]
        finally:
            db.close()
        self.assertEqual(float(balance), 100)
        self.assertEqual(float(taken), 900)

    def test_returns_follow_the_open_balance_then_cash(self):
        admin = self._headers("admin", "admin-pass")
        unpaid = self._credit(admin, "ret-unpaid", [{"method": "Credit", "amount": 1000}])
        unpaid_id = unpaid.get_json()["sale_id"]
        db = self.ac._db()
        line_id = db.execute("SELECT id FROM sale_items WHERE sale_id=?", (unpaid_id,)).fetchone()["id"]
        stock_before = db.execute("SELECT stock FROM products WHERE id=?", (self.product,)).fetchone()["stock"]
        db.close()
        returned = self.client.post(f"/api/sales/{unpaid_id}/return", headers=admin, json={
            "items": [{"sale_item_id": line_id, "quantity": 2}],
            "reason": "Unpaid credit return",
            "client_token": "ret-unpaid-1",
        })
        self.assertEqual(returned.status_code, 200, returned.get_json())
        self.assertEqual(returned.get_json().get("cash_refund"), 0)
        again = self.client.post(f"/api/sales/{unpaid_id}/return", headers=admin, json={
            "items": [{"sale_item_id": line_id, "quantity": 9}],
            "reason": "Too many",
            "client_token": "ret-unpaid-2",
        })
        self.assertEqual(again.status_code, 400, again.get_json())
        db = self.ac._db()
        try:
            row = db.execute(
                "SELECT total_amount, amount_paid, balance FROM debt_invoices WHERE sale_id=?",
                (unpaid_id,),
            ).fetchone()
            stock = db.execute("SELECT stock FROM products WHERE id=?", (self.product,)).fetchone()["stock"]
        finally:
            db.close()
        self.assertEqual(float(row["balance"]), 800)
        self.assertEqual(float(row["total_amount"]), 800)
        self.assertEqual(float(row["amount_paid"]), 0)
        self.assertEqual(float(stock), float(stock_before) + 2)

        settled = self._credit(admin, "ret-paid", [{"method": "Cash", "amount": 1000}])
        settled_body = settled.get_json()
        self.assertTrue(settled_body.get("debt") is None or settled_body["debt"].get("balance") in (0, 0.0, None))
        sale_id = settled_body["sale_id"]
        db = self.ac._db()
        try:
            debts = db.execute("SELECT COUNT(*) AS c FROM debt_invoices WHERE sale_id=?", (sale_id,)).fetchone()["c"]
            line_id = db.execute("SELECT id FROM sale_items WHERE sale_id=?", (sale_id,)).fetchone()["id"]
        finally:
            db.close()
        self.assertEqual(debts, 0)
        cash_return = self.client.post(f"/api/sales/{sale_id}/return", headers=admin, json={
            "items": [{"sale_item_id": line_id, "quantity": 1}],
            "reason": "Paid cash return",
            "client_token": "ret-paid-1",
        })
        self.assertEqual(cash_return.status_code, 200, cash_return.get_json())
        self.assertEqual(cash_return.get_json().get("cash_refund"), 100)

    def test_void_cancels_the_open_balance(self):
        db = self.ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("super", self.ac._hash_pw("super-pass"), "superadmin", "Super"),
        )
        db.commit()
        db.close()
        admin = self._headers("admin", "admin-pass")
        superadmin = self._headers("super", "super-pass")
        sale = self._credit(admin, "void-credit", [{"method": "Credit", "amount": 1000}])
        sale_id = sale.get_json()["sale_id"]
        denied = self.client.post(f"/api/sales/{sale_id}/void-now", headers=admin, json={"reason": "Not allowed"})
        self.assertEqual(denied.status_code, 403, denied.get_json())
        voided = self.client.post(f"/api/sales/{sale_id}/void-now", headers=superadmin, json={
            "reason": "Wrong customer",
        })
        self.assertEqual(voided.status_code, 200, voided.get_json())
        again = self.client.post(f"/api/sales/{sale_id}/void-now", headers=superadmin, json={
            "reason": "Wrong customer again",
        })
        self.assertNotEqual(again.status_code, 200, again.get_json())
        db = self.ac._db()
        try:
            row = db.execute("SELECT balance, status FROM debt_invoices WHERE sale_id=?", (sale_id,)).fetchone()
            stock = db.execute("SELECT stock FROM products WHERE id=?", (self.product,)).fetchone()["stock"]
        finally:
            db.close()
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(float(row["balance"]), 0)
        self.assertEqual(float(stock), 40)

    def test_settling_one_invoice_leaves_the_other(self):
        cashier = self._headers("cashier", "cashier-pass")
        first = self._credit(cashier, "two-a", [
            {"method": "Cash", "amount": 400},
            {"method": "Credit", "amount": 600},
        ])
        second = self._credit(cashier, "two-b", [{"method": "Credit", "amount": 1000}])
        first_id = first.get_json()["debt"]["invoice_id"]
        second_id = second.get_json()["debt"]["invoice_id"]
        paid = self.client.post(f"/api/debt/invoices/{first_id}/pay", headers=cashier, json={
            "amount": 600, "payment_reference": "SETTLE-A",
        })
        self.assertEqual(paid.get_json()["balance_after"], 0)
        db = self.ac._db()
        try:
            other = db.execute("SELECT balance, status FROM debt_invoices WHERE id=?", (second_id,)).fetchone()
        finally:
            db.close()
        self.assertEqual(float(other["balance"]), 1000)
        self.assertNotEqual(other["status"], "paid")


if __name__ == "__main__":
    unittest.main()
