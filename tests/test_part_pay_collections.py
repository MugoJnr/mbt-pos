"""Part pay is a sale plus money received. The unpaid part is debt, not cash."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class PartPayCollectionTests(unittest.TestCase):
    def test_part_payment_without_tender_lines_counts_the_cash_received(self):
        from desktop.utils.payment_tenders import collected_from_sales, credit_issued_from_sales

        sale = {
            "payment_method": "part payment",
            "total": 1000,
            "amount_paid": 600,
            "change_amount": 0,
            "payment_tenders": "",
        }
        out = collected_from_sales([sale])
        self.assertEqual(out["cash_collected"], 600)
        self.assertEqual(out["collected"], 600)
        self.assertEqual(out["mpesa_collected"], 0)
        self.assertEqual(credit_issued_from_sales([sale]), 400)

    def test_cash_only_part_payment_tender_is_collected_once(self):
        from desktop.utils.payment_tenders import collected_from_sales

        sale = {
            "payment_method": "Part Payment",
            "total": 1000,
            "amount_paid": 600,
            "change_amount": 0,
            "payment_tenders": json.dumps([
                {"method": "Cash", "amount": 600, "status": "confirmed"},
                {"method": "Credit", "amount": 400, "status": "outstanding"},
            ]),
        }
        out = collected_from_sales([sale])
        self.assertEqual(out["collected"], 600)
        self.assertEqual(out["cash_collected"], 600)

    def test_credit_only_tender_is_not_collected(self):
        from desktop.utils.payment_tenders import collected_from_sales

        sale = {
            "payment_method": "Part Payment",
            "total": 55,
            "amount_paid": 0,
            "change_amount": 0,
            "payment_tenders": json.dumps([
                {"method": "Credit", "amount": 55, "status": "outstanding"},
            ]),
        }
        out = collected_from_sales([sale])
        self.assertEqual(out["collected"], 0)

    def test_pending_mpesa_line_is_not_collected(self):
        from desktop.utils.payment_tenders import collected_from_sales

        sale = {
            "payment_method": "M-Pesa",
            "total": 1000,
            "amount_paid": 0,
            "change_amount": 0,
            "payment_tenders": json.dumps([
                {"method": "M-Pesa", "amount": 1000, "status": "pending"},
            ]),
        }
        self.assertEqual(collected_from_sales([sale])["collected"], 0)


class PartPayShopTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "pay.db")
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
            ("shopadmin", ac._hash_pw("pay-audit-pass"), "superadmin", "Shop Admin"),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock) VALUES ('Soap', 'SOAP', 1000, 400, 20)"
        )
        db.execute("INSERT INTO customers (name, phone, is_active) VALUES ('Amina', '0711000000', 1)")
        db.commit()
        self.user_id = db.execute("SELECT id FROM users WHERE username='shopadmin'").fetchone()["id"]
        self.customer_id = db.execute("SELECT id FROM customers").fetchone()["id"]
        self.product_id = db.execute("SELECT id FROM products").fetchone()["id"]
        db.close()
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        self.client = appmod.app.test_client()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _api(self):
        api = self.ac.APIClient()
        api._user_id = self.user_id
        api._username = "shopadmin"
        api._role = "superadmin"
        return api

    def _sale(self, **extra):
        payload = {
            "items": [{
                "product_id": self.product_id,
                "product_name": "Soap",
                "quantity": 1,
                "unit_price": 1000,
                "discount": 0,
                "total": 1000,
            }],
            "subtotal": 1000,
            "discount": 0,
            "tax": 0,
            "total": 1000,
            "original_total": 1000,
            "customer_id": self.customer_id,
        }
        payload.update(extra)
        return payload

    def test_desktop_part_pay_then_the_balance_in_three_payments(self):
        from desktop.utils.financials import compute_financials
        api = self._api()
        created = api.create_sale(self._sale(
            payment_method="part payment",
            amount_paid=500,
            cash_paid=500,
            client_token="part-500",
            payment_tenders=[
                {"method": "Cash", "amount": 500, "status": "confirmed"},
                {"method": "Credit", "amount": 1500, "status": "outstanding"},
            ],
            total=2000,
            original_total=2000,
            subtotal=2000,
            items=[{
                "product_id": self.product_id,
                "product_name": "Soap",
                "quantity": 2,
                "unit_price": 1000,
                "discount": 0,
                "total": 2000,
            }],
        ))
        self.assertTrue(created.get("success"), created)
        again = api.create_sale(self._sale(
            payment_method="part payment",
            amount_paid=500,
            client_token="part-500",
            total=2000,
            original_total=2000,
        ))
        self.assertTrue(again.get("duplicate"))
        db = self.ac._db()
        debts = db.execute("SELECT * FROM debt_invoices").fetchall()
        self.assertEqual(len(debts), 1)
        self.assertEqual(debts[0]["total_amount"], 2000)
        self.assertEqual(debts[0]["amount_paid"], 500)
        self.assertEqual(debts[0]["balance"], 1500)
        invoice_id = debts[0]["id"]
        db.close()

        for amount, left in ((300, 1200), (700, 500), (500, 0)):
            paid = api.record_debt_payment(invoice_id, amount, "Cash", notes=f"pay {amount}")
            self.assertTrue(paid.get("success"), paid)
            self.assertEqual(paid["balance_after"], left)
        too_much = api.record_debt_payment(invoice_id, 10, "Cash")
        self.assertIn("fully paid", too_much.get("error", "").lower())

        db = self.ac._db()
        payments = db.execute(
            "SELECT amount FROM debt_payments WHERE invoice_id=? ORDER BY id",
            (invoice_id,),
        ).fetchall()
        self.assertEqual([row["amount"] for row in payments], [500, 300, 700, 500])
        day = db.execute("SELECT sale_date FROM sales").fetchone()["sale_date"]
        figures = compute_financials(db, day, day)
        sales = db.execute("SELECT COUNT(*) c FROM sales").fetchone()["c"]
        db.close()
        self.assertEqual(sales, 1)
        self.assertEqual(figures["total_sales"], 2000)
        self.assertEqual(figures["total_collected"], 2000)
        self.assertEqual(figures["cash_collected"], 2000)
        self.assertEqual(figures["outstanding_debt"], 0)
        self.assertEqual(figures["debt_repayments"], 1500)

    def test_web_part_pay_split_and_short_split(self):
        login = self.client.post("/api/auth/login", json={
            "username": "shopadmin", "password": "pay-audit-pass",
        })
        self.assertEqual(login.status_code, 200, login.get_json())
        headers = {"Authorization": f"Bearer {login.get_json()['token']}"}
        part = self.client.post("/api/sales", headers=headers, json=self._sale(
            payment_method="Part Payment",
            amount_paid=600,
            cash_paid=600,
            client_token="web-part",
            payment_tenders=[
                {"method": "Cash", "amount": 600, "status": "confirmed"},
                {"method": "Credit", "amount": 400, "status": "outstanding"},
            ],
        ))
        self.assertEqual(part.status_code, 200, part.get_json())
        body = part.get_json()
        self.assertEqual(body["debt"]["balance"], 400)
        replay = self.client.post("/api/sales", headers=headers, json=self._sale(
            payment_method="Part Payment",
            amount_paid=600,
            client_token="web-part",
        ))
        self.assertTrue(replay.get_json().get("duplicate"))

        split = self.client.post("/api/sales", headers=headers, json=self._sale(
            payment_method="Mixed",
            client_token="web-split",
            payment_tenders=[
                {"method": "Cash", "amount": 400, "status": "confirmed"},
                {"method": "M-Pesa", "amount": 400, "status": "confirmed"},
                {"method": "Card", "amount": 200, "status": "confirmed"},
            ],
        ))
        self.assertEqual(split.status_code, 200, split.get_json())
        self.assertIsNone(split.get_json().get("debt"))

        short = self.client.post("/api/sales", headers=headers, json=self._sale(
            payment_method="Mixed",
            client_token="web-short",
            payment_tenders=[
                {"method": "Cash", "amount": 400, "status": "confirmed"},
                {"method": "M-Pesa", "amount": 100, "status": "confirmed"},
            ],
        ))
        self.assertEqual(short.status_code, 400, short.get_json())

        db = self.ac._db()
        rows = db.execute(
            "SELECT payment_method, total, amount_paid FROM sales ORDER BY id"
        ).fetchall()
        debts = db.execute("SELECT COUNT(*) c FROM debt_invoices").fetchone()["c"]
        db.close()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["amount_paid"], 600)
        self.assertEqual(rows[0]["total"], 1000)
        self.assertEqual(rows[1]["amount_paid"], 1000)
        self.assertEqual(debts, 1)


if __name__ == "__main__":
    unittest.main()
