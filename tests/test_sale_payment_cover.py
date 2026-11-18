"""A sale must not leave the shop when the money and the debt do not match the total."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SalePaymentCoverTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "payments.db")
        os.environ["MBT_DATA_ROOT"] = self._tmpdir.name
        os.environ["APPDATA"] = self._tmpdir.name
        os.environ["LOCALAPPDATA"] = self._tmpdir.name
        os.environ["PROGRAMDATA"] = self._tmpdir.name
        os.environ["MBT_TEST_INSTANCE"] = "1"
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
        db.commit()
        db.close()
        self.api = ac.APIClient()
        self.api._role = "superadmin"
        self.api._username = "owner"
        self.api._user_id = 1
        created = self.api.create_product({
            "name": "Sugar", "sku": "SUGAR", "price": 200, "cost_price": 100, "stock": 0,
        })
        self.assertTrue(created.get("success"), created)
        self.product_id = created["id"]
        db = ac._db()
        try:
            db.execute("UPDATE products SET stock=? WHERE id=?", (10, self.product_id))
            db.commit()
        finally:
            db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self._tmpdir.cleanup()

    def _stock(self):
        db = self.ac._db()
        try:
            return float(db.execute(
                "SELECT stock FROM products WHERE id=?", (self.product_id,)
            ).fetchone()[0])
        finally:
            db.close()

    def _sale(self, **extra):
        payload = {
            "items": [{
                "product_id": self.product_id,
                "quantity": 2,
                "unit_price": 200,
                "discount": 0,
            }],
            "subtotal": 400,
            "discount": 0,
            "tax": 0,
            "total": 400,
            "payment_method": "Cash",
            "amount_paid": 400,
        }
        payload.update(extra)
        return self.api.create_sale(payload)

    def test_short_cash_does_not_sell_or_change_stock(self):
        before = self._stock()
        result = self._sale(amount_paid=50, client_token="short-cash")
        self.assertIn("do not cover", result.get("error", "").lower())
        self.assertFalse(result.get("success"))
        self.assertEqual(self._stock(), before)
        db = self.ac._db()
        try:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0)
        finally:
            db.close()

    def test_credit_without_a_customer_does_not_sell(self):
        result = self._sale(payment_method="Credit Sale", amount_paid=0, client_token="credit-none")
        self.assertIn("customer", result.get("error", "").lower())
        self.assertEqual(self._stock(), 10)

    def test_cash_change_and_matching_credit_still_sell(self):
        changed = self._sale(amount_paid=500, change_amount=100, client_token="cash-change")
        self.assertTrue(changed.get("success"), changed)
        self.assertEqual(self._stock(), 8)
        customer = self.api.create_customer({"name": "Amina", "phone": "0700000001"})
        self.assertTrue(customer.get("success"), customer)
        credit = self._sale(
            payment_method="Credit Sale",
            amount_paid=0,
            customer_id=customer["customer_id"],
            client_token="full-credit",
        )
        self.assertTrue(credit.get("success"), credit)
        self.assertGreater(int(credit.get("debt_invoice_id") or 0), 0)
        self.assertEqual(self._stock(), 6)

    def test_tender_lines_that_do_not_add_up_are_refused(self):
        short = self._sale(
            payment_method="Mixed",
            amount_paid=100,
            payment_tenders=[
                {"method": "Cash", "amount": 100},
                {"method": "M-Pesa", "amount": 100},
            ],
            client_token="short-split",
        )
        self.assertIn("do not match", short.get("error", "").lower())
        self.assertEqual(self._stock(), 10)
        exact = self._sale(
            payment_method="Mixed",
            amount_paid=0,
            payment_tenders=[
                {"method": "Cash", "amount": 150},
                {"method": "M-Pesa", "amount": 250},
            ],
            client_token="exact-split",
        )
        self.assertTrue(exact.get("success"), exact)
        db = self.ac._db()
        try:
            row = db.execute(
                "SELECT amount_paid, cash_paid, electronic_paid FROM sales WHERE client_token=?",
                ("exact-split",),
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(float(row[0]), 400)
        self.assertEqual(float(row[1]), 150)
        self.assertEqual(float(row[2]), 250)
        self.assertEqual(self._stock(), 8)

    def test_a_line_total_cannot_understate_the_price(self):
        lied = self._sale(items=[{
            "product_id": self.product_id,
            "quantity": 2,
            "unit_price": 200,
            "discount": 0,
            "total": 1,
        }])
        self.assertIn("does not match", lied.get("error", "").lower())
        self.assertEqual(self._stock(), 10)

    def test_web_sale_refuses_a_short_cash_payment(self):
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        appmod.init_db()
        client = appmod.app.test_client()
        logged = client.post("/api/auth/login", json={
            "username": "owner", "password": "owner-pass",
        })
        self.assertEqual(logged.status_code, 200, logged.get_json())
        token = logged.get_json()["token"]
        refused = client.post("/api/sales", json={
            "items": [{
                "product_id": self.product_id,
                "quantity": 1,
                "unit_price": 200,
                "discount": 0,
            }],
            "subtotal": 200,
            "total": 200,
            "payment_method": "Cash",
            "amount_paid": 20,
        }, headers={"Authorization": "Bearer " + token})
        self.assertEqual(refused.status_code, 400, refused.get_json())
        self.assertIn("do not cover", refused.get_json().get("error", "").lower())
        self.assertEqual(self._stock(), 10)
