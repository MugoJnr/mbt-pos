"""Cashier valuation, product removal, and FIFO profit on a disposable shop."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class RemovalAndProfitTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "test.db")
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
        self.api._role = "admin"
        self.api._user_id = 1
        self.api._username = "admin"

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_unused_product_is_deleted_and_stocked_product_is_archived(self):
        unused = self.api.create_product({
            "name": "Unused Soap", "price": 10, "cost_price": 4, "stock": 0,
        })
        self.assertTrue(unused.get("success"), unused)
        removed = self.api.delete_product(unused["id"])
        self.assertEqual(removed.get("mode"), "deleted", removed)
        db = self.ac._db()
        self.assertIsNone(db.execute("SELECT id FROM products WHERE id=?", (unused["id"],)).fetchone())
        db.close()

        kept = self.api.create_product({
            "name": "Stocked Soap", "price": 20, "cost_price": 8, "stock": 5,
        })
        archived = self.api.delete_product(kept["id"])
        self.assertEqual(archived.get("mode"), "archived", archived)
        db = self.ac._db()
        row = db.execute("SELECT is_active FROM products WHERE id=?", (kept["id"],)).fetchone()
        db.close()
        self.assertEqual(int(row[0]), 0)

    def test_cashier_cannot_remove_a_product(self):
        created = self.api.create_product({
            "name": "Cashier Soap", "price": 10, "cost_price": 4, "stock": 0,
        })
        self.api._role = "cashier"
        denied = self.api.delete_product(created["id"])
        self.assertEqual(denied.get("status"), 403, denied)
        db = self.ac._db()
        row = db.execute("SELECT id FROM products WHERE id=?", (created["id"],)).fetchone()
        db.close()
        self.assertIsNotNone(row)

    def test_profit_uses_the_consumed_layers_after_the_current_cost_changes(self):
        from desktop.utils.stock_layers import add_layer, consume_fifo, period_profit
        db = sqlite3.connect(":memory:")
        db.execute(
            "CREATE TABLE sales (id INTEGER PRIMARY KEY, sale_date TEXT, created_at TEXT, status TEXT, total REAL)"
        )
        db.execute(
            "CREATE TABLE sale_items (id INTEGER PRIMARY KEY, sale_id INTEGER, product_id INTEGER, quantity REAL, total REAL)"
        )
        db.execute("INSERT INTO sales VALUES (1, '2026-10-27', '2026-10-27 09:00:00', 'completed', 30)")
        db.execute("INSERT INTO sale_items VALUES (1, 1, 7, 3, 30)")
        self.assertTrue(add_layer(db, 7, 2, 4, "receipt", "a").get("success"))
        self.assertTrue(add_layer(db, 7, 2, 10, "receipt", "b").get("success"))
        used = consume_fifo(db, 7, 3, sale_id=1, reference="RCP-1")
        self.assertTrue(used.get("success"), used)
        self.assertEqual(used["cogs"], 18.0)
        detail = period_profit(db, "2026-10-27", "2026-10-27")
        self.assertEqual(detail["cogs"], 18.0)
        self.assertEqual(detail["profit"], 12.0)
        self.assertEqual(detail["uncosted_lines"], 0)

        db.execute("INSERT INTO sales VALUES (2, '2026-10-27', '2026-10-27 10:00:00', 'completed', 10)")
        db.execute(
            "INSERT INTO sale_items (id, sale_id, product_id, quantity, total) VALUES (2, 2, 8, 1, 10)"
        )
        bare = period_profit(db, "2026-10-27", "2026-10-27")
        self.assertEqual(bare["profit"], 12.0)
        self.assertEqual(bare["uncosted_revenue"], 10.0)
        self.assertEqual(bare["uncosted_lines"], 1)
        db.close()


if __name__ == "__main__":
    unittest.main()
