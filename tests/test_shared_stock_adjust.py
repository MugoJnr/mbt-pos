"""Web and till stock changes go through the same adjustment rules."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SharedStockAdjustTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "adjust.db")
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
        self.api = ac.APIClient()
        self.api._role = "superadmin"
        self.api._user_id = 1
        self.api._username = "owner"
        db = ac._db()
        db.execute(
            "INSERT INTO users (id, username, password_hash, role) VALUES (1, 'owner', 'x', 'superadmin')"
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, unit) "
            "VALUES ('QA Sugar', 'SUG', 150, 100, 10, 'kg')"
        )
        db.commit()
        db.close()
        from desktop.utils.shop_time import shop_today
        self.yesterday = (shop_today() - timedelta(days=1)).isoformat()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self._tmpdir.cleanup()

    def _stock(self):
        db = self.ac._db()
        try:
            return db.execute("SELECT stock FROM products WHERE sku='SUG'").fetchone()["stock"]
        finally:
            db.close()

    def test_cashier_cannot_adjust_and_a_past_date_needs_a_reason(self):
        self.api._role = "cashier"
        denied = self.api.adjust_stock(1, 12, "Count correction", expected_stock=10)
        self.assertEqual(denied.get("status"), 403)
        self.assertEqual(self._stock(), 10)
        self.api._role = "superadmin"
        missing = self.api.adjust_stock(
            1, 12, "Count correction", expected_stock=10, business_date=self.yesterday,
        )
        self.assertEqual(missing.get("status"), 400)
        self.assertIn("reason", missing.get("error", "").lower())
        self.assertEqual(self._stock(), 10)

    def test_same_token_changes_stock_once_and_keeps_the_reason(self):
        first = self.api.adjust_stock(
            1, 12, "Count correction", expected_stock=10,
            business_date=self.yesterday,
            backdate_reason="Correction of an earlier recording error",
            idempotency_key="adj-once",
        )
        self.assertTrue(first.get("success"), first)
        self.assertEqual(self._stock(), 12)
        second = self.api.adjust_stock(
            1, 20, "Count correction", expected_stock=12,
            business_date=self.yesterday,
            backdate_reason="Correction of an earlier recording error",
            idempotency_key="adj-once",
        )
        self.assertTrue(second.get("duplicate"), second)
        self.assertEqual(self._stock(), 12)
        db = self.ac._db()
        try:
            reason = db.execute(
                "SELECT reason FROM stock_movements WHERE reference='adj-once'"
            ).fetchone()["reason"]
        finally:
            db.close()
        self.assertIn("Correction of an earlier recording error", reason)

    def test_stocktake_shortage_consumes_the_oldest_cost_batch(self):
        from desktop.utils.stock_layers import add_layer
        from desktop.utils.stocktake import apply_stocktake, record_count, start_stocktake
        db = self.ac._db()
        try:
            added = add_layer(db, 1, 10, 100, "purchase", "RCV-TEST")
            self.assertTrue(added.get("success"), added)
            opened = start_stocktake(db, "Evening")
            saved = record_count(db, opened["id"], 1, 8)
            self.assertTrue(saved.get("stock_unchanged"), saved)
            db.commit()
            applied = apply_stocktake(db, opened["id"], username="owner", user_id=1)
            self.assertTrue(applied.get("success"), applied)
            self.assertFalse(applied.get("duplicate"))
            remaining = db.execute(
                "SELECT remaining_qty FROM cost_layers WHERE id=?", (added["id"],)
            ).fetchone()["remaining_qty"]
            value = db.execute(
                "SELECT ROUND(SUM(remaining_qty * unit_cost), 2) FROM cost_layers"
            ).fetchone()[0]
            again = apply_stocktake(db, opened["id"], username="owner", user_id=1)
            remaining_again = db.execute(
                "SELECT remaining_qty FROM cost_layers WHERE id=?", (added["id"],)
            ).fetchone()["remaining_qty"]
            stock = db.execute("SELECT stock FROM products WHERE id=1").fetchone()["stock"]
        finally:
            db.close()
        self.assertEqual(float(remaining), 8.0)
        self.assertEqual(float(value), 800.0)
        self.assertTrue(again.get("duplicate"))
        self.assertEqual(float(remaining_again), 8.0)
        self.assertEqual(float(stock), 8.0)

    def test_web_route_delegates_to_the_shared_adjustment(self):
        path = os.path.join(ROOT, "web", "web_routes.py")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        start = text.index("def adjust_stock(pid):")
        end = text.index("def _web_superadmin_pin", start)
        body = text[start:end]
        self.assertIn("_inventory_api().adjust_stock", body)
        self.assertNotIn("UPDATE products SET stock", body)
        inventory = os.path.join(ROOT, "web", "dashboard-ui", "src", "routes", "inventory.tsx")
        with open(inventory, encoding="utf-8") as handle:
            screen = handle.read()
        self.assertIn('["inventory-valuation", productsQ.dataUpdatedAt]', screen)
        sales = os.path.join(ROOT, "desktop", "tabs", "sales_tab.py")
        with open(sales, encoding="utf-8") as handle:
            till = handle.read()
        self.assertIn("def hideEvent", till)
        self.assertIn("self.invalidate_catalog()", till)


if __name__ == "__main__":
    unittest.main()
