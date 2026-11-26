"""Till, stored reports, and the portal credit definition use one sales rule."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class FinancialParityTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "parity.db")
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = "superadmin"
        self.api._user_id = 1
        self.api._username = "owner"
        db = ac._db()
        db.execute(
            "INSERT INTO users (id, username, password_hash, role, full_name, is_active) "
            "VALUES (1,'owner','x','superadmin','Owner',1)"
        )
        db.commit()
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_report_uses_the_till_sales_and_credit_split(self):
        product = self.api.create_product({
            "name": "Parity Soap", "price": 100, "stock": 5, "unit": "pcs", "cost_price": 40,
        })
        self.assertTrue(product.get("success"), product)
        cash = self.api.create_sale({
            "items": [{
                "product_id": product["id"], "product_name": "Parity Soap", "sku": "P",
                "quantity": 1, "unit_price": 100, "discount": 0, "total": 100,
            }],
            "subtotal": 100, "discount": 0, "tax": 0, "total": 100,
            "payment_method": "Cash", "amount_paid": 100, "change_amount": 0,
        })
        self.assertTrue(cash.get("success"), cash)
        customer = self.api.create_customer({"name": "Parity Customer", "phone": "0711111111"})
        credit = self.api.create_sale({
            "items": [{
                "product_id": product["id"], "product_name": "Parity Soap", "sku": "P",
                "quantity": 1, "unit_price": 100, "discount": 0, "total": 100,
            }],
            "subtotal": 100, "discount": 0, "tax": 0, "total": 100,
            "payment_method": "Credit", "amount_paid": 0, "change_amount": 0,
            "customer_id": customer["customer_id"],
        })
        self.assertTrue(credit.get("success"), credit)
        from desktop.utils.financials import compute_financials
        from desktop.utils.shop_time import shop_today
        from backend.cloud.report_engine import ReportEngine
        day = shop_today().isoformat()
        db = self.ac._db()
        figures = compute_financials(db, day, day)
        db.close()
        report = ReportEngine(self._db_path, config_getter=lambda: {}).generate_report(
            "daily", day, day,
        )
        summary = report["summary"]
        self.assertEqual(summary["revenue"], figures["total_sales"])
        self.assertEqual(summary["paid_sales"], figures["paid_sales"])
        self.assertEqual(summary["new_credit"], figures["new_credit"])
        self.assertEqual(summary["source"], "compute_financials")
        self.assertEqual(figures["paid_sales"], 100)
        self.assertEqual(figures["new_credit"], 100)
        self.assertEqual(figures["total_sales"], 200)

    def test_remote_backup_without_cloud_sign_in_is_not_uploaded(self):
        from backend.cloud.command_center import CommandCenter
        center = CommandCenter(self._db_path, config_getter=lambda: {})
        with patch("backend.cloud_backup.paths.is_cloud_configured", return_value=False), \
             patch("backend.cloud_backup.paths.is_logged_in", return_value=False):
            ok, message, detail = center._cmd_run_backup({})
        self.assertFalse(ok)
        self.assertFalse(detail["uploaded"])
        self.assertEqual(detail["status"], "cloud_authentication_unavailable")
        self.assertIn("uploaded", message.lower())
