"""Supplier invoices stay on the delivery. Payments never move stock or customer debt."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SupplierPayableTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "payables.db")
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
            "INSERT INTO users (username, password_hash, role, full_name, is_active) "
            "VALUES (?,?,?,?,1)",
            ("owner", ac._hash_pw("owner-pass"), "superadmin", "Owner"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) "
            "VALUES (?,?,?,?,1)",
            ("till", ac._hash_pw("till-pass"), "cashier", "Till"),
        )
        db.commit()
        db.close()
        self.api = ac.APIClient()
        self.api._role = "admin"
        self.api._username = "qa-admin"
        self.api._user_id = 1
        from desktop.utils.security import _pin_hash
        db = ac._db()
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?,?,?)",
            ("superadmin_pin_hash", _pin_hash("246810"), "2026-10-31T00:00:00"),
        )
        db.commit()
        db.close()
        self.supplier = self.api.create_supplier({"name": "Payable Supplier", "phone": "0700111222"})["id"]
        self.product = self._product("Payable Flour", 0, 100)

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _product(self, name, stock, cost):
        created = self.api.create_product({
            "name": name, "sku": name.replace(" ", "-"), "price": 80,
            "cost_price": cost, "stock": stock, "unit": "pcs",
        })
        self.assertTrue(created.get("success"), created)
        return created["id"]

    def _deliver(self, qty, cost, **extra):
        saved = self.api.receive_delivery(
            self.supplier,
            [{"product_id": self.product, "quantity": qty, "unit_cost": cost}],
            reference=extra.pop("reference", ""),
            **extra,
        )
        self.assertTrue(saved.get("success"), saved)
        return saved

    def _balance(self, receipt_id):
        row = self.api.get_stock_receipt(receipt_id)
        self.assertFalse(row.get("error"), row)
        return row

    def _stock(self):
        db = self.ac._db()
        try:
            return float(db.execute("SELECT stock FROM products WHERE id=?", (self.product,)).fetchone()["stock"])
        finally:
            db.close()

    def _debts(self):
        db = self.ac._db()
        try:
            return db.execute("SELECT COUNT(*) FROM debt_invoices").fetchone()[0]
        finally:
            db.close()

    def test_paid_partial_and_unpaid_do_not_touch_customer_debt(self):
        paid = self._deliver(10, 1000, payment_amount=10000, payment_method="cash", reference="CASH-1")
        self.assertEqual(paid["outstanding"], 0)
        self.assertEqual(self._balance(paid["receipt_id"])["payment_status"], "PAID")
        self.assertEqual(self._stock(), 10)

        partial = self._deliver(2, 10000, payment_amount=5000, payment_method="mpesa")
        opened = self._balance(partial["receipt_id"])
        self.assertEqual(opened["amount_paid"], 5000)
        self.assertEqual(opened["outstanding"], 15000)
        self.assertEqual(opened["payment_status"], "PARTIALLY PAID")
        self.assertEqual(self._stock(), 12)

        unpaid = self._deliver(1, 8000)
        opened = self._balance(unpaid["receipt_id"])
        self.assertEqual(opened["outstanding"], 8000)
        self.assertEqual(opened["payment_status"], "UNPAID")
        later = self.api.record_supplier_payment(
            self.supplier, 3000, method="bank", reference="BANK-3", mode="manual",
            allocations=[{"receipt_id": unpaid["receipt_id"], "amount": 3000}],
        )
        self.assertTrue(later.get("success"), later)
        opened = self._balance(unpaid["receipt_id"])
        self.assertEqual(opened["amount_paid"], 3000)
        self.assertEqual(opened["outstanding"], 5000)
        self.assertEqual(self._stock(), 13)
        self.assertEqual(self._debts(), 0)

    def test_oldest_manual_and_advance(self):
        other = self.api.create_supplier({"name": "Three Bills"})["id"]
        item = self._product("Payable Oil", 0, 10)
        ids = []
        for amount in (4000, 6000, 2000):
            saved = self.api.receive_delivery(
                other, [{"product_id": item, "quantity": 1, "unit_cost": amount}],
            )
            self.assertTrue(saved.get("success"), saved)
            ids.append(saved["receipt_id"])
        stock_before = float(self.ac._db().execute(
            "SELECT stock FROM products WHERE id=?", (item,)
        ).fetchone()["stock"])
        self.ac._db().close()
        paid = self.api.record_supplier_payment(other, 5000, method="cash", mode="oldest")
        self.assertTrue(paid.get("success"), paid)
        self.assertEqual(len(paid["allocations"]), 2)
        balances = {row["id"]: row for row in self.api.supplier_payable_summary()["invoices"] if row["supplier_id"] == other}
        self.assertEqual(balances[ids[0]]["outstanding"], 0)
        self.assertEqual(balances[ids[0]]["payment_status"], "PAID")
        self.assertEqual(balances[ids[1]]["outstanding"], 5000)
        self.assertEqual(balances[ids[1]]["payment_status"], "PARTIALLY PAID")
        self.assertEqual(balances[ids[2]]["outstanding"], 2000)
        self.assertEqual(self.api.supplier_statement(other)["outstanding"], 7000)
        stock_after = float(self.ac._db().execute(
            "SELECT stock FROM products WHERE id=?", (item,)
        ).fetchone()["stock"])
        self.ac._db().close()
        self.assertEqual(stock_before, stock_after)

        manual = self.api.record_supplier_payment(
            other, 2000, method="cash", mode="manual",
            allocations=[{"receipt_id": ids[2], "amount": 2000}],
        )
        self.assertTrue(manual.get("success"), manual)
        self.assertEqual(self._balance(ids[2])["payment_status"], "PAID")
        self.assertEqual(self._balance(ids[1])["outstanding"], 5000)

        over = self.api.record_supplier_payment(other, 7000, method="cash", mode="oldest")
        self.assertTrue(over.get("success"), over)
        self.assertEqual(over["unapplied"], 2000)
        self.assertEqual(self.api.supplier_statement(other)["outstanding"], 0)
        self.assertGreaterEqual(self.api.supplier_statement(other)["advance"], 2000)
        self.assertEqual(self._balance(ids[1])["outstanding"], 0)

    def test_admin_edit_backdate_void_return_and_requests(self):
        saved = self._deliver(10, 100, reference="INV-1")
        receipt_id = saved["receipt_id"]
        created = self._balance(receipt_id)["created_at"]
        self.api._role = "cashier"
        self.api._user_id = 2
        self.api._username = "till"
        blocked = self.api.correct_stock_receipt_line(receipt_id, self.product, 12, pin="246810")
        self.assertEqual(blocked.get("status"), 403)
        blocked = self.api.backdate_stock_receipt(receipt_id, "2026-10-01", "late book")
        self.assertEqual(blocked.get("status"), 403)
        asked = self.api.request_delivery_action(receipt_id, "backdate", "Book was late", "2026-10-01")
        self.assertTrue(asked.get("success"), asked)
        own = self.api.review_delivery_request(asked["request_id"], "approve")
        self.assertEqual(own.get("status"), 403)

        self.api._role = "admin"
        self.api._user_id = 1
        self.api._username = "qa-admin"
        approved = self.api.review_delivery_request(asked["request_id"], "approve")
        self.assertTrue(approved.get("success"), approved)
        opened = self._balance(receipt_id)
        self.assertEqual(opened["effective_date"], "2026-10-01")
        self.assertEqual(opened["created_at"], created)

        bigger = self.api.correct_stock_receipt_line(receipt_id, self.product, 12, reason="extra cartons")
        self.assertTrue(bigger.get("success"), bigger)
        self.assertEqual(bigger["delta"], 2)
        self.assertEqual(self._stock(), 12)
        smaller = self.api.correct_stock_receipt_line(
            receipt_id, self.product, 7, pin="246810", reason="count was wrong",
        )
        self.assertTrue(smaller.get("success"), smaller)
        self.assertEqual(smaller["delta"], -5)
        self.assertEqual(self._balance(receipt_id)["grand_total"], 700)

        header = self.api.update_stock_receipt_header(receipt_id, reference="INV-1B", due_date="2026-11-15")
        self.assertTrue(header.get("success"), header)
        self.assertEqual(self._balance(receipt_id)["reference_note"], "INV-1B")

        returned = self.api.return_receipt_line(
            receipt_id, self.product, 3, reason="damaged", pin="246810", client_token="ret-1",
        )
        self.assertTrue(returned.get("success"), returned)
        opened = self._balance(receipt_id)
        line = opened["lines"][0]
        self.assertEqual(line["quantity"], 7)
        self.assertEqual(line["returned_qty"], 3)
        self.assertEqual(opened["grand_total"], 400)
        self.assertEqual(self._stock(), 4)
        again = self.api.return_receipt_line(
            receipt_id, self.product, 3, reason="damaged", pin="246810", client_token="ret-1",
        )
        self.assertTrue(again.get("duplicate"))
        self.assertEqual(self._stock(), 4)

        unpaid = self._deliver(2, 50)
        self.api._role = "cashier"
        self.api._user_id = 2
        void_ask = self.api.request_delivery_action(unpaid["receipt_id"], "void", "Wrong supplier")
        self.assertTrue(void_ask.get("success"), void_ask)
        self.api._role = "admin"
        self.api._user_id = 1
        rejected = self.api.review_delivery_request(void_ask["request_id"], "reject", note="Keep it")
        self.assertEqual(rejected["status"], "rejected")
        self.assertNotEqual(self._balance(unpaid["receipt_id"])["status"], "reversed")

        payable = self._deliver(1, 8000, payment_amount=3000, payment_method="cash")
        stock_before = self._stock()
        voided = self.api.reverse_stock_receipt(payable["receipt_id"], reason="Not ours", pin="246810")
        self.assertTrue(voided.get("success"), voided)
        opened = self._balance(payable["receipt_id"])
        self.assertEqual(opened["status"], "reversed")
        self.assertEqual(opened["payment_status"], "VOIDED")
        self.assertEqual(opened["outstanding"], 0)
        self.assertEqual(voided["supplier_credit"], 3000)
        self.assertEqual(self._stock(), stock_before - 1)
        second = self.api.reverse_stock_receipt(payable["receipt_id"], reason="again", pin="246810")
        self.assertIn("already", second.get("error", "").lower())

    def test_delivery_request_reaches_the_requests_centre_for_an_admin_only(self):
        saved = self._deliver(2, 40)
        self.api._role = "cashier"
        self.api._user_id = 2
        asked = self.api.request_delivery_action(
            saved["receipt_id"], "backdate", "Wrong day", "2026-10-01",
        )
        self.assertTrue(asked.get("success"), asked)
        from backend.requests_centre import list_centre
        db = self.ac._db()
        try:
            cashier = list_centre(db, {"id": 2, "role": "cashier"}, {"type": "supplier_backdate"})
            manager = list_centre(
                db, {"id": 9, "role": "manager"},
                {"queue": "action", "type": "supplier_backdate"},
            )
            admin = list_centre(
                db, {"id": 1, "role": "admin"},
                {"queue": "action", "type": "supplier_backdate"},
            )
            own = list_centre(
                db, {"id": 2, "role": "admin"},
                {"queue": "action", "type": "supplier_backdate"},
            )
        finally:
            db.close()
        self.assertEqual(len(cashier["requests"]), 1)
        self.assertEqual(cashier["requests"][0]["source"], "delivery")
        self.assertEqual(manager["requests"], [])
        self.assertEqual(len(admin["requests"]), 1)
        self.assertEqual(admin["requests"][0]["next_action"], "Awaiting your review")
        self.assertEqual(own["requests"], [])
