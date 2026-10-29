"""One sale can take cash, M-Pesa, and customer credit without double-counting."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class MixedCreditTenderTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "tender.db")
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
            "INSERT INTO products (name, sku, price, cost_price, stock, is_active) VALUES (?,?,?,?,?,1)",
            ("QA Mix", "QA-MIX", 100, 40, 50),
        )
        db.execute(
            "INSERT INTO customers (name, phone, is_active) VALUES ('QA Credit', '0700', 1)"
        )
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

    def _headers(self):
        response = self.client.post(
            "/api/auth/login", json={"username": "cashier", "password": "cashier-pass"},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return {"Authorization": f"Bearer {response.get_json()['token']}"}

    def _sell(self, headers, tenders, token, customer=True):
        body = {
            "items": [{"product_id": self.product, "quantity": 10, "unit_price": 100}],
            "subtotal": 1000, "total": 1000,
            "payment_method": "Mixed",
            "payment_tenders": tenders,
            "client_token": token,
        }
        if customer:
            body["customer_id"] = self.customer
        return self.client.post("/api/sales", headers=headers, json=body)

    def test_cash_mpesa_and_credit_is_one_sale(self):
        headers = self._headers()
        denied = self._sell(headers, [
            {"method": "Cash", "amount": 200},
            {"method": "M-Pesa", "amount": 300, "status": "pending"},
            {"method": "Credit", "amount": 500},
        ], "pending-mpesa")
        self.assertEqual(denied.status_code, 400, denied.get_json())
        sale = self._sell(headers, [
            {"method": "Cash", "amount": 200},
            {"method": "M-Pesa", "amount": 300},
            {"method": "Credit", "amount": 500},
        ], "st-05")
        self.assertEqual(sale.status_code, 200, sale.get_json())
        body = sale.get_json()
        self.assertEqual(body["debt"]["balance"], 500)
        again = self._sell(headers, [
            {"method": "Cash", "amount": 200},
            {"method": "M-Pesa", "amount": 300},
            {"method": "Credit", "amount": 500},
        ], "st-05")
        self.assertTrue(again.get_json().get("duplicate"))
        db = self.ac._db()
        try:
            count = db.execute("SELECT COUNT(*) AS c FROM sales").fetchone()["c"]
            stock = db.execute("SELECT stock FROM products WHERE id=?", (self.product,)).fetchone()["stock"]
            debts = db.execute("SELECT COUNT(*) AS c FROM debt_invoices").fetchone()["c"]
        finally:
            db.close()
        self.assertEqual(count, 1)
        self.assertEqual(float(stock), 40)
        self.assertEqual(debts, 1)

    def test_three_methods_without_cash(self):
        headers = self._headers()
        sale = self._sell(headers, [
            {"method": "M-Pesa", "amount": 400, "reference": "QA-MPESA-1"},
            {"method": "Card", "amount": 350, "reference": "QA-CARD-1"},
            {"method": "Bank Transfer", "amount": 250},
        ], "three-no-cash", customer=False)
        self.assertEqual(sale.status_code, 200, sale.get_json())
        body = sale.get_json()
        self.assertFalse(body.get("debt"))
        detail = self.client.get(
            f"/api/receipts/sale/{body['sale_id']}", headers=headers,
        )
        self.assertEqual(detail.status_code, 200, detail.get_json())
        methods = [row["method"] for row in detail.get_json().get("tenders") or []]
        self.assertEqual(methods, ["M-Pesa", "Card", "Bank Transfer"])
        stored = detail.get_json()["header"]["payment_method"]
        self.assertIn("M-Pesa", stored)
        self.assertIn("Card", stored)
        self.assertIn("Bank Transfer", stored)
        self.assertNotIn("Cash", stored)
        short = self._sell(headers, [
            {"method": "M-Pesa", "amount": 100},
            {"method": "Card", "amount": 100},
        ], "short-split", customer=False)
        self.assertEqual(short.status_code, 400, short.get_json())
        over = self._sell(headers, [
            {"method": "M-Pesa", "amount": 700},
            {"method": "Card", "amount": 500},
        ], "over-no-cash", customer=False)
        self.assertEqual(over.status_code, 400, over.get_json())

    def test_four_confirmed_parts(self):
        headers = self._headers()
        sale = self._sell(headers, [
            {"method": "Cash", "amount": 100},
            {"method": "M-Pesa", "amount": 200},
            {"method": "Card", "amount": 200},
            {"method": "Credit", "amount": 500},
        ], "st-07")
        self.assertEqual(sale.status_code, 200, sale.get_json())
        self.assertEqual(sale.get_json()["debt"]["balance"], 500)

    def test_credit_without_a_customer_is_rejected(self):
        headers = self._headers()
        sale = self._sell(headers, [
            {"method": "Cash", "amount": 400},
            {"method": "Credit", "amount": 600},
        ], "no-customer", customer=False)
        self.assertEqual(sale.status_code, 400, sale.get_json())


if __name__ == "__main__":
    unittest.main()
