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
            ("QA Mix", "QA-MIX", 100, 40, 200),
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
        self.assertEqual(float(stock), 190)
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

    def test_full_credit_line_is_debt_not_a_payment(self):
        headers = self._headers()
        sale = self._sell(headers, [
            {"method": "Credit", "amount": 1000},
        ], "full-credit")
        self.assertEqual(sale.status_code, 200, sale.get_json())
        body = sale.get_json()
        self.assertEqual(body["debt"]["balance"], 1000)
        detail = self.client.get(f"/api/receipts/sale/{body['sale_id']}", headers=headers)
        header = detail.get_json()["header"]
        self.assertEqual(float(header["amount_paid"] or 0), 0)
        notes = header.get("notes") or ""
        self.assertNotIn("Paid:", notes)
        self.assertIn("Credit", notes)

    def test_two_payments_plus_credit_reconcile(self):
        headers = self._headers()
        sale = self._sell(headers, [
            {"method": "M-Pesa", "amount": 500, "reference": "QA-MPESA-PART"},
            {"method": "Card", "amount": 300, "reference": "QA-CARD-PART"},
            {"method": "Credit", "amount": 200},
        ], "part-two")
        self.assertEqual(sale.status_code, 200, sale.get_json())
        body = sale.get_json()
        self.assertEqual(body["debt"]["balance"], 200)
        detail = self.client.get(f"/api/receipts/sale/{body['sale_id']}", headers=headers).get_json()
        notes = detail["header"].get("notes") or ""
        self.assertIn("Paid:", notes)
        self.assertIn("M-Pesa 500.00", notes)
        self.assertNotIn("Paid: M-Pesa 500.00 + Card 300.00 + Credit", notes)
        self.assertEqual(float(detail["header"]["amount_paid"]), 800)

    def test_cheque_and_airtel_are_collected(self):
        headers = self._headers()
        sale = self._sell(headers, [
            {"method": "Airtel Money", "amount": 400, "reference": "QA-AIRTEL"},
            {"method": "Cheque", "amount": 600, "reference": "QA-CHQ"},
        ], "airtel-cheque", customer=False)
        self.assertEqual(sale.status_code, 200, sale.get_json())
        stored = sale.get_json()
        self.assertFalse(stored.get("debt"))
        detail = self.client.get(
            f"/api/receipts/sale/{stored['sale_id']}", headers=headers,
        ).get_json()
        methods = [row["method"] for row in detail.get("tenders") or []]
        self.assertEqual(methods, ["Airtel Money", "Cheque"])

    def test_credit_without_a_customer_is_rejected(self):
        headers = self._headers()
        sale = self._sell(headers, [
            {"method": "Cash", "amount": 400},
            {"method": "Credit", "amount": 600},
        ], "no-customer", customer=False)
        self.assertEqual(sale.status_code, 400, sale.get_json())


class CollectedMethodRollupTests(unittest.TestCase):
    def test_split_lines_fill_tiles_and_credit_is_not_collected(self):
        import json
        from desktop.utils.payment_tenders import collected_from_sales

        rows = [
            {
                "payment_method": "Cash",
                "total": 55,
                "amount_paid": 55,
                "change_amount": 20,
                "payment_tenders": "",
            },
            {
                "payment_method": "M-Pesa + Card + Bank Transfer",
                "total": 55,
                "amount_paid": 55,
                "change_amount": 0,
                "payment_tenders": json.dumps([
                    {"method": "M-Pesa", "amount": 18.33, "status": "confirmed"},
                    {"method": "Card", "amount": 18.33, "status": "confirmed"},
                    {"method": "Bank Transfer", "amount": 18.34, "status": "confirmed"},
                ]),
            },
            {
                "payment_method": "Part Payment",
                "total": 55,
                "amount_paid": 0,
                "change_amount": 0,
                "payment_tenders": json.dumps([
                    {"method": "Credit", "amount": 55, "status": "outstanding"},
                ]),
            },
        ]
        out = collected_from_sales(rows)
        self.assertEqual(out["cash_collected"], 55)
        self.assertEqual(out["mpesa_collected"], 18.33)
        self.assertEqual(out["card_collected"], 18.33)
        self.assertEqual(out["bank_collected"], 18.34)
        self.assertEqual(out["other_collected"], 0)

    def test_mixed_cash_change_is_not_kept(self):
        import json
        from desktop.utils.payment_tenders import collected_from_sales

        rows = [{
            "payment_method": "Cash + M-Pesa",
            "total": 55,
            "amount_paid": 55,
            "change_amount": 20,
            "payment_tenders": json.dumps([
                {"method": "Cash", "amount": 40, "status": "confirmed"},
                {"method": "M-Pesa", "amount": 35, "status": "confirmed"},
            ]),
        }]
        out = collected_from_sales(rows)
        self.assertEqual(out["cash_collected"], 20)
        self.assertEqual(out["mpesa_collected"], 35)

    def test_mixed_cash_without_change_is_kept(self):
        import json
        from desktop.utils.payment_tenders import collected_from_sales

        rows = [{
            "payment_method": "Cash + M-Pesa",
            "total": 55,
            "amount_paid": 55,
            "change_amount": 0,
            "payment_tenders": json.dumps([
                {"method": "Cash", "amount": 30, "status": "confirmed"},
                {"method": "M-Pesa", "amount": 25, "status": "confirmed"},
            ]),
        }]
        out = collected_from_sales(rows)
        self.assertEqual(out["cash_collected"], 30)
        self.assertEqual(out["mpesa_collected"], 25)

    def test_unconfirmed_money_is_left_out(self):
        import json
        from desktop.utils.payment_tenders import collected_from_sales

        rows = [{
            "payment_method": "M-Pesa",
            "total": 40,
            "amount_paid": 0,
            "change_amount": 0,
            "payment_tenders": json.dumps([
                {"method": "M-Pesa", "amount": 40, "status": "pending"},
            ]),
        }]
        out = collected_from_sales(rows)
        self.assertEqual(out["mpesa_collected"], 0)


if __name__ == "__main__":
    unittest.main()
