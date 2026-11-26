"""Rejected goods stay out of stock, and missing buying prices are not stored as zero."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SupplierCostHealthTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "cost-health.db")
        os.environ["MBT_TEST_INSTANCE"] = "1"
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
        self.api = ac.APIClient()
        self.api._role = "admin"
        self.api._username = "qa-admin"

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _product(self, name, stock=0, cost=0, unit="pcs"):
        created = self.api.create_product({
            "name": name, "price": 200, "cost_price": cost, "stock": stock, "unit": unit,
        })
        self.assertTrue(created.get("success"), created)
        return created["id"]

    def _supplier(self, name="QA Health Supplier"):
        created = self.api.create_supplier({
            "name": name, "phone": "0700111222", "contact_name": "Amina",
            "email": "amina@example.com", "tax_pin": "P000111222B",
        })
        self.assertTrue(created.get("success"), created)
        return created["id"]

    def test_exact_supplier_name_is_not_merged_and_a_similar_name_is_kept(self):
        first = self._supplier("Kamau Wholesalers")
        duplicate = self.api.create_supplier({"name": " kamau wholesalers "})
        self.assertEqual(duplicate.get("status"), 409)
        self.assertEqual(duplicate.get("id"), first)
        similar = self.api.create_supplier({"name": "Kamau Wholesalers Ltd"})
        self.assertTrue(similar.get("success"), similar)
        self.assertNotEqual(similar["id"], first)

    def test_rejected_quantity_does_not_enter_stock_and_partial_outstanding_is_recorded(self):
        supplier = self._supplier()
        sugar = self._product("QA Sugar 1kg", cost=100)
        oil = self._product("QA Oil 1L", cost=200, unit="ltr")
        saved = self.api.receive_delivery(supplier, [
            {"product_id": sugar, "quantity": 20, "ordered_qty": 22, "rejected_qty": 2,
             "unit_cost": 145},
            {"product_id": oil, "quantity": 10, "ordered_qty": 15, "rejected_qty": 1.5,
             "unit_cost": 230},
        ], reference="INV-QA-14675", client_token="health-partial-1", payment_amount=5000)
        self.assertTrue(saved.get("success"), saved)
        self.assertEqual(saved["grand_total"], round(20 * 145 + 10 * 230, 2))
        db = self.ac._db()
        try:
            stocks = {
                row["id"]: row["stock"]
                for row in db.execute("SELECT id, stock FROM products WHERE id IN (?,?)", (sugar, oil))
            }
            self.assertEqual(stocks[sugar], 20)
            self.assertEqual(stocks[oil], 10)
            line = db.execute(
                "SELECT quantity, rejected_qty, ordered_qty FROM stock_receipt_lines "
                "WHERE product_id=?",
                (oil,),
            ).fetchone()
            self.assertEqual(line["quantity"], 10)
            self.assertEqual(line["rejected_qty"], 1.5)
            self.assertEqual(line["ordered_qty"], 15)
            layers = db.execute(
                "SELECT COALESCE(SUM(remaining_qty),0) FROM cost_layers WHERE product_id=?",
                (sugar,),
            ).fetchone()[0]
            self.assertEqual(layers, 20)
        finally:
            db.close()
        again = self.api.receive_delivery(
            supplier, [{"product_id": sugar, "quantity": 20, "unit_cost": 145}],
            client_token="health-partial-1",
        )
        self.assertTrue(again.get("duplicate"))
        db = self.ac._db()
        try:
            stock = db.execute("SELECT stock FROM products WHERE id=?", (sugar,)).fetchone()["stock"]
            self.assertEqual(stock, 20)
        finally:
            db.close()

    def test_missing_buying_price_is_not_posted_as_zero_and_free_stock_is_explicit(self):
        supplier = self._supplier("Free Goods Co")
        blank = self._product("QA Blank Cost", cost=0)
        refused = self.api.receive_delivery(supplier, [
            {"product_id": blank, "quantity": 4},
        ])
        self.assertIn("buying price", refused.get("error", "").lower())
        zero = self.api.receive_delivery(supplier, [
            {"product_id": blank, "quantity": 4, "unit_cost": 0},
        ])
        self.assertIn("free stock", zero.get("error", "").lower())
        free = self.api.receive_delivery(supplier, [
            {"product_id": blank, "quantity": 4, "unit_cost": 0, "explicit_zero": True},
        ], client_token="free-stock-1")
        self.assertTrue(free.get("success"), free)
        db = self.ac._db()
        try:
            row = db.execute(
                "SELECT stock, cost_price, cost_confirmed FROM products WHERE id=?", (blank,)
            ).fetchone()
            self.assertEqual(row["stock"], 4)
            self.assertEqual(row["cost_price"], 0)
            self.assertEqual(row["cost_confirmed"], 1)
            layers = db.execute(
                "SELECT COUNT(*) FROM cost_layers WHERE product_id=? AND source_type='purchase'",
                (blank,),
            ).fetchone()[0]
            self.assertEqual(layers, 0)
        finally:
            db.close()
        products = self.api.get_products()
        blank_row = next(item for item in products if item["id"] == blank)
        codes = [badge["code"] for badge in blank_row["cost_health"]["badges"]]
        self.assertIn("explicit_zero", codes)
        self.assertNotIn("missing_price", codes)

    def test_excess_without_confirmation_is_refused_and_cashier_cannot_send_a_cost(self):
        supplier = self._supplier("Excess Supplier")
        pid = self._product("QA Excess", cost=50)
        over = self.api.receive_delivery(supplier, [{
            "product_id": pid, "quantity": 22, "ordered_qty": 20, "unit_cost": 50,
        }])
        self.assertIn("more than ordered", over.get("error", "").lower())
        self.api._role = "cashier"
        hidden = self.api.receive_delivery(supplier, [{
            "product_id": pid, "quantity": 2, "unit_cost": 55,
        }], client_token="cashier-card-cost")
        self.assertEqual(hidden.get("status"), 403, hidden)
        self.api._role = "viewer"
        denied = self.api.receive_delivery(supplier, [{
            "product_id": pid, "quantity": 1, "unit_cost": 55,
        }])
        self.assertEqual(denied.get("status"), 403)

    def test_legacy_zero_is_review_and_null_is_missing(self):
        from desktop.utils.cost_health import classify
        self.assertEqual(classify(None, 0, 3, 0, 0)[0], "missing_price")
        self.assertIn("zero_review", classify(0, 0, 3, 0, 0))
        self.assertIn("explicit_zero", classify(0, 1, 3, 0, 0))
        self.assertNotIn("missing_fifo", classify(0, 1, 3, 0, 0))
        self.assertIn("missing_fifo", classify(80, 1, 5, 0, 0))
        self.assertEqual(classify(80, 1, 5, 5, 400)[0], "complete")


if __name__ == "__main__":
    unittest.main()
