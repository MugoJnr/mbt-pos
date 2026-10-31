"""Shop figures: sales, paid sales, credit, collections and profit share one formula."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class FinancialOverviewTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "finance.db")
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
            ("admin", ac._hash_pw("admin-pass"), "admin", "Admin"),
        )
        db.execute("INSERT INTO customers (name, phone, is_active) VALUES ('QA', '0700', 1)")
        db.commit()
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

    def test_credit_sale_profit_repayment_and_cashier_range(self):
        from desktop.utils.financials import compute_financials
        from desktop.utils.stock_layers import ensure_cost_layers
        db = self.ac._db()
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock) VALUES ('Widget', 'W1', 1000, 760, 5)"
        )
        db.execute(
            """INSERT INTO sales
               (receipt_number, total, amount_paid, payment_method, status, sale_date)
               VALUES ('R-1000', 1000, 600, 'Cash', 'completed', '2026-10-01')"""
        )
        sale_id = db.execute("SELECT id FROM sales WHERE receipt_number='R-1000'").fetchone()["id"]
        db.execute(
            """INSERT INTO sale_items
               (sale_id, product_id, product_name, quantity, unit_price, discount, total)
               VALUES (?, 1, 'Widget', 1, 1000, 0, 1000)""",
            (sale_id,),
        )
        ensure_cost_layers(db)
        db.execute(
            """INSERT INTO cost_layer_uses
               (layer_id, product_id, sale_id, quantity, unit_cost, reversed)
               VALUES (1, 1, ?, 1, 760, 0)""",
            (sale_id,),
        )
        db.execute(
            """INSERT INTO debt_invoices
               (invoice_number, sale_id, customer_id, customer_name, total_amount, amount_paid, balance, status)
               VALUES ('INV-1', ?, ?, 'QA', 1000, 600, 400, 'partial')""",
            (sale_id, self.customer),
        )
        invoice_id = db.execute("SELECT id FROM debt_invoices").fetchone()["id"]
        db.commit()
        day = compute_financials(db, "2026-10-01", "2026-10-01")
        self.assertEqual(day["total_sales"], 1000)
        self.assertEqual(day["paid_sales"], 600)
        self.assertEqual(day["new_credit"], 400)
        self.assertEqual(day["gross_profit"], 240)
        self.assertEqual(day["realized_gross_profit"], 144)
        self.assertEqual(day["unrealized_gross_profit"], 96)
        self.assertEqual(day["outstanding_debt"], 400)

        db.execute(
            """INSERT INTO debt_payments
               (payment_receipt, invoice_id, customer_id, amount, payment_method,
                balance_before, balance_after, notes, created_at, reversed)
               VALUES ('PAY-1', ?, ?, 200, 'Cash', 400, 200, 'Later repayment',
                       '2026-10-02T10:00:00', 0)""",
            (invoice_id, self.customer),
        )
        db.execute(
            "UPDATE debt_invoices SET amount_paid=800, balance=200, status='partial' WHERE id=?",
            (invoice_id,),
        )
        db.commit()
        sale_day = compute_financials(db, "2026-10-01", "2026-10-01")
        pay_day = compute_financials(db, "2026-10-02", "2026-10-02")
        self.assertEqual(sale_day["total_sales"], 1000)
        self.assertEqual(sale_day["paid_sales"], 800)
        self.assertEqual(sale_day["new_credit"], 200)
        self.assertEqual(sale_day["realized_gross_profit"], 192)
        self.assertEqual(sale_day["unrealized_gross_profit"], 48)
        self.assertEqual(pay_day["total_sales"], 0)
        self.assertEqual(pay_day["debt_repayments"], 200)
        self.assertEqual(pay_day["total_collected"], 200)
        self.assertEqual(pay_day["outstanding_debt"], 200)
        db.close()

        cashier = self._headers("cashier", "cashier-pass")
        one = self.client.get("/api/reports/summary?start=2026-10-01&end=2026-10-01", headers=cashier)
        self.assertEqual(one.status_code, 200, one.get_json())
        self.assertEqual(one.get_json()["summary"]["total_sales"], 1000)
        self.assertNotIn("gross_profit", one.get_json()["summary"])
        self.assertNotIn("paid_sales", one.get_json()["finance"])
        span = self.client.get("/api/reports/summary?start=2026-10-01&end=2026-10-02", headers=cashier)
        self.assertEqual(span.status_code, 403, span.get_json())
        admin = self._headers("admin", "admin-pass")
        both = self.client.get("/api/reports/summary?start=2026-10-01&end=2026-10-02", headers=admin)
        self.assertEqual(both.status_code, 200, both.get_json())
        self.assertEqual(both.get_json()["finance"]["gross_profit"], 240)
        self.assertEqual(both.get_json()["finance"]["total_collected"], 800)
