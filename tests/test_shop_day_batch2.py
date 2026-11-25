"""Second shop-day batch: returns, supplier pay, reports, settings, roles."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class QuantityAndMixTests(unittest.TestCase):
    def test_stepped_float_is_not_too_many_decimal_places(self):
        from desktop.utils.quantities import QuantityError, parse_quantity
        value = 0.0
        for _ in range(50):
            value += 0.01
            parse_quantity(value)
        self.assertAlmostEqual(parse_quantity(value), 0.5, places=4)
        with self.assertRaises(QuantityError):
            parse_quantity("1.12345")

    def test_mpesa_refund_label_and_account(self):
        from desktop.utils.accounting_engine import payment_method_account
        from desktop.utils.payment_tenders import refund_method_label
        self.assertEqual(refund_method_label("m-pesa"), "M-Pesa")
        self.assertEqual(refund_method_label("M-Pesa"), "M-Pesa")
        self.assertEqual(payment_method_account("m-pesa"), "1010")
        self.assertEqual(payment_method_account("cash"), "1000")

    def test_payment_bars_sum_to_100(self):
        from desktop.utils.charts import payment_bar_rows
        rows = payment_bar_rows([
            {"label": "Cash", "value": 30},
            {"label": "M-Pesa", "value": 70},
            {"label": "Credit", "value": 51},
        ])
        self.assertAlmostEqual(sum(row["pct"] for row in rows), 100.0, places=2)

    def test_viewer_grants_cannot_add_a_write(self):
        from desktop.utils.security import effective_actions
        actions = effective_actions({
            "role": "viewer",
            "permission_grants": ["accounting.create_expenses", "sales.create"],
        })
        self.assertNotIn("accounting.create_expenses", actions)
        self.assertNotIn("sales.create", actions)
        self.assertIn("sales.view_all", actions)


class ShopDayMoneyTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "day.db")
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        from desktop.utils.security import _pin_hash
        ac._SCHEMA_READY = False
        self.ac = ac
        db = ac._db()
        db.execute(
            "INSERT INTO users (id, username, password_hash, role, full_name, is_active) "
            "VALUES (1,'owner','x','superadmin','Owner',1)"
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('superadmin_pin_hash', ?)",
            (_pin_hash("135790"),),
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('inventory_costing', 'fifo')"
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('receipt_footer', 'Thanks')"
        )
        db.commit()
        db.close()
        self.api = ac.APIClient()
        self.api._role = "admin"
        self.api._user_id = 1
        self.api._username = "owner"

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_mpesa_return_credits_mpesa_not_cash(self):
        created = self.api.create_product({
            "name": "Fert", "price": 3500, "cost_price": 3000, "stock": 4,
        })
        self.assertTrue(created.get("success"), created)
        sale = self.api.create_sale({
            "items": [{
                "product_id": created["id"], "product_name": "Fert",
                "quantity": 1, "unit_price": 3500, "discount": 0, "total": 3500,
            }],
            "subtotal": 3500, "total": 3500, "payment_method": "M-Pesa",
            "amount_paid": 3500, "electronic_paid": 3500, "cash_paid": 0,
        })
        self.assertTrue(sale.get("success"), sale)
        line = self.ac._db().execute(
            "SELECT id FROM sale_items WHERE sale_id=?", (sale["sale_id"],)
        ).fetchone()
        self.ac._db().close()
        done = self.api.return_sale(
            int(sale["sale_id"]),
            [{"sale_item_id": int(line["id"]), "quantity": 1}],
            "Wrong bag",
            refund_method="M-Pesa",
            pin="135790",
        )
        self.assertTrue(done.get("success"), done)
        db = self.ac._db()
        try:
            credit = db.execute(
                """SELECT COALESCE(SUM(jl.credit),0)
                   FROM journal_lines jl
                   JOIN journal_entries je ON je.id=jl.journal_id
                   WHERE je.entry_type='sale_return' AND jl.account_code='1010'"""
            ).fetchone()[0]
            cash = db.execute(
                """SELECT COALESCE(SUM(jl.credit),0)
                   FROM journal_lines jl
                   JOIN journal_entries je ON je.id=jl.journal_id
                   WHERE je.entry_type='sale_return' AND jl.account_code='1000'"""
            ).fetchone()[0]
        finally:
            db.close()
        self.assertAlmostEqual(float(credit), 3500.0, places=2)
        self.assertAlmostEqual(float(cash), 0.0, places=2)

    def test_payment_does_not_settle_a_voided_receipt_or_a_silent_overpay(self):
        product = self.api.create_product({
            "name": "Seed", "price": 100, "cost_price": 80, "stock": 0,
        })
        supplier = self.api.create_supplier({"name": "Sagana"})
        other = self.api.create_supplier({"name": "Kiambu"})
        voided = self.api.receive_delivery(
            supplier["id"],
            [{"product_id": product["id"], "quantity": 2, "unit_cost": 4000}],
            client_token="void-me",
        )
        live = self.api.receive_delivery(
            supplier["id"],
            [{"product_id": product["id"], "quantity": 1, "unit_cost": 2000}],
            client_token="keep-me",
        )
        self.assertTrue(voided.get("success") and live.get("success"), (voided, live))
        reversed_row = self.api.reverse_stock_receipt(voided["receipt_id"], pin="135790")
        self.assertTrue(reversed_row.get("success"), reversed_row)
        refused = self.api.record_supplier_payment(supplier["id"], 40000, method="cash")
        self.assertEqual(refused.get("status"), 409)
        paid = self.api.record_supplier_payment(supplier["id"], 2000, method="M-Pesa", reference="QA1")
        self.assertTrue(paid.get("success"), paid)
        self.assertEqual(paid["allocations"][0]["receipt_id"], live["receipt_id"])
        self.assertNotEqual(paid["supplier_id"], other["id"])
        confirmed = self.api.record_supplier_payment(
            supplier["id"], 500, method="cash", allow_overpay=True,
        )
        self.assertTrue(confirmed.get("success"), confirmed)
        self.assertGreater(confirmed.get("unapplied") or 0, 0)

    def test_saving_a_footer_does_not_change_costing_and_is_historic(self):
        saved = self.api.update_settings({
            "receipt_footer": "QA footer",
            "inventory_costing": "weighted_avg",
            "accounting_method": "cash",
            "config_version": 0,
        })
        self.assertTrue(saved.get("success"), saved)
        self.assertIn("receipt_footer", saved.get("changed") or [])
        self.assertNotIn("inventory_costing", saved.get("changed") or [])
        db = self.ac._db()
        try:
            costing = db.execute(
                "SELECT value FROM system_settings WHERE key='inventory_costing'"
            ).fetchone()[0]
            history = db.execute(
                "SELECT setting_key, old_value, new_value FROM settings_history "
                "WHERE setting_key='receipt_footer'"
            ).fetchall()
        finally:
            db.close()
        self.assertEqual(costing, "fifo")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["new_value"], "QA footer")

    def test_report_sale_value_nets_returns(self):
        product = self.api.create_product({
            "name": "Maize", "price": 250, "cost_price": 180, "stock": 10,
        })
        sale = self.api.create_sale({
            "items": [{
                "product_id": product["id"], "product_name": "Maize",
                "quantity": 2, "unit_price": 250, "discount": 0, "total": 500,
            }],
            "subtotal": 500, "total": 500, "payment_method": "Cash",
            "amount_paid": 500,
        })
        line = self.ac._db().execute(
            "SELECT id FROM sale_items WHERE sale_id=?", (sale["sale_id"],)
        ).fetchone()
        self.ac._db().close()
        done = self.api.return_sale(
            int(sale["sale_id"]),
            [{"sale_item_id": int(line["id"]), "quantity": 1}],
            "One bag back",
            refund_method="Cash",
            pin="135790",
        )
        self.assertTrue(done.get("success"), done)
        from desktop.utils.shop_time import shop_today
        day = shop_today().isoformat()
        summary = self.api.get_report_summary(day, day)["summary"]
        self.assertAlmostEqual(float(summary["total_revenue"]), 250.0, places=2)
        self.assertAlmostEqual(float(summary["returns_total"]), 250.0, places=2)


if __name__ == "__main__":
    unittest.main()
