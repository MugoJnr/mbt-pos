"""Multi-product supplier deliveries, decimals, duplicates, corrections, and reversals."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class StockReceiveDeliveryTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "receive.db")
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

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _product(self, name, stock, cost, unit="pcs"):
        created = self.api.create_product({
            "name": name, "sku": name.replace(" ", "-"), "price": 50,
            "cost_price": cost, "stock": stock, "unit": unit,
        })
        self.assertTrue(created.get("success"), created)
        return created["id"]

    def _supplier(self, name="QA Receive Supplier"):
        created = self.api.create_supplier({"name": name, "phone": "0700000000"})
        self.assertTrue(created.get("success"), created)
        return created["id"]

    def _stock(self, pid):
        db = self.ac._db()
        try:
            row = db.execute(
                "SELECT stock, cost_price FROM products WHERE id=?", (pid,)
            ).fetchone()
            return float(row["stock"]), float(row["cost_price"])
        finally:
            db.close()

    def test_multi_product_delivery_updates_stock_once(self):
        supplier = self._supplier()
        a = self._product("Receive A", 20, 100)
        b = self._product("Receive B", 15, 40)
        c = self._product("Receive C", 8, 10)
        saved = self.api.receive_delivery(supplier, [
            {"product_id": a, "quantity": 10, "unit_cost": 100},
            {"product_id": b, "quantity": 5, "unit_cost": 50},
            {"product_id": c, "quantity": 12.5, "unit_cost": 8},
        ], reference="INV-100", notes="Morning drop", client_token="recv-multi-1")
        self.assertTrue(saved.get("success"), saved)
        self.assertFalse(saved.get("duplicate"))
        self.assertEqual(len(saved["lines"]), 3)
        self.assertEqual(self._stock(a), (30, 100))
        self.assertEqual(self._stock(b), (20, 50))
        self.assertEqual(self._stock(c), (20.5, 8))
        self.assertEqual(saved["grand_total"], round(10 * 100 + 5 * 50 + 12.5 * 8, 2))
        again = self.api.receive_delivery(supplier, [
            {"product_id": a, "quantity": 10, "unit_cost": 100},
        ], client_token="recv-multi-1")
        self.assertTrue(again.get("duplicate"), again)
        self.assertEqual(self._stock(a)[0], 30)
        db = self.ac._db()
        try:
            moves = db.execute(
                "SELECT COUNT(*) FROM stock_movements WHERE movement_type='PURCHASE' "
                "AND reference LIKE ?",
                (f"%{saved['receipt_number']}%",),
            ).fetchone()[0]
            self.assertEqual(int(moves), 3)
            layers = db.execute(
                "SELECT COALESCE(SUM(remaining_qty * unit_cost),0) FROM cost_layers "
                "WHERE source_id LIKE ?",
                (saved["receipt_number"] + ":%",),
            ).fetchone()[0]
            self.assertEqual(round(float(layers), 2), saved["grand_total"])
            receipt = db.execute(
                "SELECT reference_note, notes, status FROM stock_receipts WHERE id=?",
                (saved["receipt_id"],),
            ).fetchone()
            self.assertEqual(receipt["reference_note"], "INV-100")
            self.assertEqual(receipt["notes"], "Morning drop")
            self.assertEqual(receipt["status"], "posted")
        finally:
            db.close()

    def test_decimal_quantity_is_not_truncated(self):
        supplier = self._supplier("Decimal Supplier")
        pid = self._product("Receive Decimal", 1, 20)
        saved = self.api.receive_delivery(supplier, [
            {"product_id": pid, "quantity": 10.125, "unit_cost": 4},
        ], client_token="recv-decimal")
        self.assertTrue(saved.get("success"), saved)
        self.assertEqual(saved["lines"][0]["quantity"], 10.125)
        self.assertEqual(self._stock(pid)[0], 11.125)

    def test_duplicate_product_zero_qty_and_inactive_are_rejected(self):
        supplier = self._supplier("Guard Supplier")
        pid = self._product("Receive Guard", 4, 5)
        duplicate = self.api.receive_delivery(supplier, [
            {"product_id": pid, "quantity": 1, "unit_cost": 5},
            {"product_id": pid, "quantity": 2, "unit_cost": 5},
        ])
        self.assertIn("once", duplicate.get("error", "").lower())
        zero = self.api.receive_delivery(supplier, [
            {"product_id": pid, "quantity": 0, "unit_cost": 5},
        ])
        self.assertIn("error", zero)
        negative = self.api.receive_delivery(supplier, [
            {"product_id": pid, "quantity": -1, "unit_cost": 5},
        ])
        self.assertIn("error", negative)
        db = self.ac._db()
        db.execute("UPDATE products SET is_active=0 WHERE id=?", (pid,))
        db.commit()
        db.close()
        inactive = self.api.receive_delivery(supplier, [
            {"product_id": pid, "quantity": 1, "unit_cost": 5},
        ])
        self.assertIn("not active", inactive.get("error", "").lower())
        self.assertEqual(self._stock(pid)[0], 4)
        self.api._role = "viewer"
        denied = self.api.receive_delivery(supplier, [
            {"product_id": pid, "quantity": 1, "unit_cost": 5},
        ])
        self.assertIn("error", denied)

    def test_last_cost_stays_on_the_product_and_layers_keep_history(self):
        supplier = self._supplier("Cost Supplier")
        pid = self._product("Receive Cost", 0, 0)
        first = self.api.receive_stock(pid, 10, supplier_id=supplier, unit_cost=100, client_token="cost-1")
        second = self.api.receive_stock(pid, 10, supplier_id=supplier, unit_cost=120, client_token="cost-2")
        self.assertTrue(second.get("success"), second)
        self.assertEqual(self._stock(pid), (20, 120))
        db = self.ac._db()
        try:
            value = db.execute(
                "SELECT COALESCE(SUM(remaining_qty * unit_cost),0) FROM cost_layers WHERE product_id=?",
                (pid,),
            ).fetchone()[0]
            self.assertEqual(round(float(value), 2), 2200)
            first_line = db.execute(
                "SELECT unit_cost FROM stock_receipt_lines WHERE receipt_id=?",
                (first["receipt_id"],),
            ).fetchone()
            self.assertEqual(float(first_line["unit_cost"]), 100)
        finally:
            db.close()

    def test_correction_uses_the_difference_and_reverse_runs_once(self):
        supplier = self._supplier("Correct Supplier")
        pid = self._product("Receive Correct", 20, 100)
        saved = self.api.receive_delivery(supplier, [
            {"product_id": pid, "quantity": 10, "unit_cost": 100},
        ], client_token="recv-correct")
        self.assertEqual(self._stock(pid)[0], 30)
        self.api._role = "cashier"
        blocked = self.api.correct_stock_receipt_line(saved["receipt_id"], pid, 12)
        self.assertEqual(blocked.get("status"), 403)
        self.assertEqual(self._stock(pid)[0], 30)
        self.api._role = "admin"
        missing_pin = self.api.correct_stock_receipt_line(saved["receipt_id"], pid, 7)
        self.assertEqual(missing_pin.get("status"), 403)
        increased = self.api.correct_stock_receipt_line(saved["receipt_id"], pid, 12)
        self.assertTrue(increased.get("success"), increased)
        self.assertEqual(increased["delta"], 2)
        self.assertEqual(self._stock(pid)[0], 32)
        reduced = self.api.correct_stock_receipt_line(
            saved["receipt_id"], pid, 9, pin="246810",
        )
        self.assertTrue(reduced.get("success"), reduced)
        self.assertEqual(reduced["delta"], -3)
        self.assertEqual(self._stock(pid)[0], 29)
        wrong = self.api.reverse_stock_receipt(saved["receipt_id"], pin="000000")
        self.assertEqual(wrong.get("status"), 403)
        self.assertEqual(self._stock(pid)[0], 29)
        reversed_delivery = self.api.reverse_stock_receipt(
            saved["receipt_id"], pin="246810", reason="QA reverse",
        )
        self.assertTrue(reversed_delivery.get("success"), reversed_delivery)
        self.assertEqual(self._stock(pid)[0], 20)
        second = self.api.reverse_stock_receipt(saved["receipt_id"], pin="246810")
        self.assertIn("already", second.get("error", "").lower())
        self.assertEqual(self._stock(pid)[0], 20)
        db = self.ac._db()
        try:
            status = db.execute(
                "SELECT status FROM stock_receipts WHERE id=?", (saved["receipt_id"],)
            ).fetchone()["status"]
            self.assertEqual(status, "reversed")
            reversal = db.execute(
                "SELECT COUNT(*) FROM stock_movements WHERE movement_type='PURCHASE_REVERSAL' "
                "AND product_id=?",
                (pid,),
            ).fetchone()[0]
            self.assertEqual(int(reversal), 1)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
