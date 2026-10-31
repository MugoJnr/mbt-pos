"""Supplier receipts write FIFO layers, and both sale paths consume them."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class FifoReceiveSaleTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "fifo.db")
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
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        self.client = appmod.app.test_client()
        self.api = ac.APIClient()
        self.api._role = "superadmin"
        self.api._username = "owner"
        self.api._user_id = 1

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _login(self):
        response = self.client.post(
            "/api/auth/login", json={"username": "owner", "password": "owner-pass"},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return {"Authorization": f"Bearer {response.get_json()['token']}"}

    def test_two_receipts_then_twelve_units_cost_1120(self):
        created = self.api.create_product({
            "name": "QA-Layered-Product", "sku": "QA-LAYER",
            "price": 200, "cost_price": 0, "stock": 0,
        })
        self.assertTrue(created.get("success"), created)
        pid = created["id"]
        supplier = self.api.create_supplier({"name": "QA-Supplier-Primary"})
        self.assertTrue(supplier.get("success"), supplier)
        first = self.api.receive_stock(pid, 10, supplier_id=supplier["id"], unit_cost=100)
        self.assertTrue(first.get("success"), first)
        second = self.api.receive_stock(pid, 10, supplier_id=supplier["id"], unit_cost=140)
        self.assertTrue(second.get("success"), second)
        self.assertEqual(second["new_stock"], 20)

        headers = self._login()
        sale = self.client.post("/api/sales", headers=headers, json={
            "items": [{"product_id": pid, "quantity": 12, "unit_price": 200}],
            "subtotal": 2400, "discount": 0, "tax": 0, "total": 2400,
            "payment_method": "cash", "amount_paid": 2400,
            "client_token": "fifo-twelve",
        })
        self.assertEqual(sale.status_code, 200, sale.get_json())
        again = self.client.post("/api/sales", headers=headers, json={
            "items": [{"product_id": pid, "quantity": 12, "unit_price": 200}],
            "subtotal": 2400, "total": 2400, "payment_method": "cash",
            "amount_paid": 2400, "client_token": "fifo-twelve",
        })
        self.assertTrue(again.get_json().get("duplicate"))

        today = date.today().isoformat()
        db = self.ac._db()
        try:
            from desktop.utils.stock_layers import period_profit
            stock = db.execute("SELECT stock, cost_price FROM products WHERE id=?", (pid,)).fetchone()
            self.assertEqual(float(stock["stock"]), 8)
            self.assertEqual(float(stock["cost_price"]), 140)
            profit = period_profit(db, today, today)
            self.assertEqual(profit["cogs"], 1280)
            self.assertEqual(profit["revenue_costed"], 2400)
            self.assertEqual(profit["profit"], 1120)
            self.assertEqual(profit["uncosted_lines"], 0)
            db.execute("UPDATE products SET cost_price=50 WHERE id=?", (pid,))
            db.commit()
            again_profit = period_profit(db, today, today)
            self.assertEqual(again_profit["profit"], 1120)
            self.assertEqual(again_profit["cogs"], 1280)
        finally:
            db.close()

    def test_zero_quantity_does_not_sell_one(self):
        created = self.api.create_product({
            "name": "QA-Zero", "price": 10, "cost_price": 4, "stock": 5,
        })
        headers = self._login()
        denied = self.client.post("/api/sales", headers=headers, json={
            "items": [{"product_id": created["id"], "quantity": 0, "unit_price": 10}],
            "subtotal": 0, "total": 0, "payment_method": "cash", "amount_paid": 0,
        })
        self.assertEqual(denied.status_code, 400, denied.get_json())
        db = self.ac._db()
        try:
            stock = db.execute(
                "SELECT stock FROM products WHERE id=?", (created["id"],)
            ).fetchone()["stock"]
            sales = db.execute("SELECT COUNT(*) AS c FROM sales").fetchone()["c"]
        finally:
            db.close()
        self.assertEqual(float(stock), 5)
        self.assertEqual(sales, 0)

    def test_three_prices_sell_thirty_five_uses_oldest_batches(self):
        created = self.api.create_product({
            "name": "QA-FIFO-35", "price": 150, "cost_price": 0, "stock": 0,
        })
        supplier = self.api.create_supplier({"name": "QA-Batch-Supplier"})
        other = self.api.create_supplier({"name": "QA-Other-Supplier"})
        pid = created["id"]
        for qty, cost, who in ((20, 100, supplier), (30, 110, supplier), (25, 120, other)):
            saved = self.api.receive_delivery(
                who["id"],
                [{"product_id": pid, "quantity": qty, "unit_cost": cost}],
                reference=f"INV-{cost}",
            )
            self.assertTrue(saved.get("success"), saved)
        headers = self._login()
        sale = self.client.post("/api/sales", headers=headers, json={
            "items": [{"product_id": pid, "quantity": 35, "unit_price": 150}],
            "subtotal": 5250, "discount": 0, "tax": 0, "total": 5250,
            "payment_method": "cash", "amount_paid": 5250,
            "client_token": "fifo-thirty-five",
        })
        self.assertEqual(sale.status_code, 200, sale.get_json())
        today = date.today().isoformat()
        db = self.ac._db()
        try:
            from desktop.utils.stock_layers import period_profit
            layers = db.execute(
                "SELECT remaining_qty, unit_cost, purchase_unit_cost, supplier_name "
                "FROM cost_layers WHERE product_id=? ORDER BY id",
                (pid,),
            ).fetchall()
            self.assertEqual([float(row["remaining_qty"]) for row in layers], [0, 15, 25])
            self.assertEqual([float(row["unit_cost"]) for row in layers], [100, 110, 120])
            self.assertEqual(layers[2]["supplier_name"], "QA-Other-Supplier")
            uses = db.execute(
                "SELECT quantity, unit_cost FROM cost_layer_uses "
                "WHERE product_id=? AND COALESCE(reversed,0)=0 ORDER BY id",
                (pid,),
            ).fetchall()
            self.assertEqual(
                [(float(row["quantity"]), float(row["unit_cost"])) for row in uses],
                [(20, 100), (15, 110)],
            )
            profit = period_profit(db, today, today)
            self.assertEqual(profit["cogs"], 3650)
            self.assertEqual(profit["revenue_costed"], 5250)
            self.assertEqual(profit["profit"], 1600)
            value = db.execute(
                "SELECT COALESCE(SUM(remaining_qty * unit_cost),0) FROM cost_layers WHERE product_id=?",
                (pid,),
            ).fetchone()[0]
            self.assertEqual(float(value), 4650)
        finally:
            db.close()
        history = self.api.get_product_history(pid)
        self.assertEqual(history["batch_summary"]["inventory_value"], 4650)
        self.assertEqual(history["batch_summary"]["active_batches"], 2)
        self.api._role = "cashier"
        hidden = self.api.get_product_history(pid)
        self.assertNotIn("inventory_value", hidden["batch_summary"])
        self.assertNotIn("unit_cost", hidden["batches"][0])
        self.assertNotIn("cost_price", hidden["product"])

    def test_extra_delivery_cost_is_kept_separate_from_the_buy_price(self):
        created = self.api.create_product({
            "name": "QA-Landed", "price": 200, "cost_price": 1, "stock": 0,
        })
        supplier = self.api.create_supplier({"name": "QA-Landed-Supplier"})
        saved = self.api.receive_delivery(
            supplier["id"],
            [{"product_id": created["id"], "quantity": 10, "unit_cost": 100, "extra_unit_cost": 5}],
            reference="INV-LANDED",
        )
        self.assertTrue(saved.get("success"), saved)
        db = self.ac._db()
        try:
            layer = db.execute(
                "SELECT unit_cost, purchase_unit_cost, extra_unit_cost, reference_note "
                "FROM cost_layers WHERE product_id=?",
                (created["id"],),
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(float(layer["purchase_unit_cost"]), 100)
        self.assertEqual(float(layer["extra_unit_cost"]), 5)
        self.assertEqual(float(layer["unit_cost"]), 105)
        self.assertEqual(layer["reference_note"], "INV-LANDED")
        self.api.update_product(created["id"], {"cost_price": 1})
        db = self.ac._db()
        try:
            layer = db.execute(
                "SELECT unit_cost FROM cost_layers WHERE product_id=?",
                (created["id"],),
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(float(layer["unit_cost"]), 105)

    def test_one_delivery_cost_is_split_by_buy_value_and_old_sales_stay(self):
        from desktop.utils.stock_layers import allocate_delivery_extra, correct_opening_cost, opening_backfill
        oil = self.api.create_product({"name": "QA-Split-Oil", "price": 300, "cost_price": 0, "stock": 0})
        soap = self.api.create_product({"name": "QA-Split-Soap", "price": 80, "cost_price": 0, "stock": 0})
        supplier = self.api.create_supplier({"name": "QA-Split-Supplier"})
        saved = self.api.receive_delivery(
            supplier["id"],
            [
                {"product_id": oil["id"], "quantity": 10, "unit_cost": 100},
                {"product_id": soap["id"], "quantity": 10, "unit_cost": 200},
            ],
            reference="INV-SPLIT",
            delivery_extra=30,
        )
        self.assertTrue(saved.get("success"), saved)
        self.assertEqual(saved.get("grand_total"), 3030)
        db = self.ac._db()
        try:
            rows = db.execute(
                "SELECT product_id, purchase_unit_cost, extra_unit_cost, unit_cost "
                "FROM cost_layers WHERE product_id IN (?, ?) ORDER BY product_id",
                (oil["id"], soap["id"]),
            ).fetchall()
            by_id = {row["product_id"]: row for row in rows}
            self.assertEqual(float(by_id[oil["id"]]["purchase_unit_cost"]), 100)
            self.assertEqual(float(by_id[oil["id"]]["extra_unit_cost"]), 1)
            self.assertEqual(float(by_id[oil["id"]]["unit_cost"]), 101)
            self.assertEqual(float(by_id[soap["id"]]["purchase_unit_cost"]), 200)
            self.assertEqual(float(by_id[soap["id"]]["extra_unit_cost"]), 2)
            self.assertEqual(float(by_id[soap["id"]]["unit_cost"]), 202)
            zero = allocate_delivery_extra(
                [{"quantity": 4, "unit_cost": 10, "extra_unit_cost": 9}], 0,
            )
            self.assertEqual(zero["total"], 0)
            self.assertEqual(zero["shares"], [0])
            opening = self.api.create_product({
                "name": "QA-Opening", "price": 20, "cost_price": 8, "stock": 5,
            })
            opening_backfill(db)
            db.commit()
            layer = db.execute(
                "SELECT id, source_type, supplier_name, reference_note, unit_cost "
                "FROM cost_layers WHERE product_id=? AND source_type='opening'",
                (opening["id"],),
            ).fetchone()
            self.assertEqual(layer["supplier_name"], "Opening stock")
            self.assertIn("Supplier unknown", layer["reference_note"])
            from desktop.utils.stock_layers import consume_fifo
            used = consume_fifo(db, opening["id"], 1, sale_id=1, reference="OPEN-1")
            self.assertEqual(used["cogs"], 8)
            corrected = correct_opening_cost(db, layer["id"], 12)
            self.assertTrue(corrected.get("success"), corrected)
            kept = db.execute(
                "SELECT unit_cost FROM cost_layer_uses WHERE reference='OPEN-1'"
            ).fetchone()
            remaining = db.execute(
                "SELECT unit_cost, remaining_qty FROM cost_layers WHERE id=?",
                (layer["id"],),
            ).fetchone()
            self.assertEqual(float(kept["unit_cost"]), 8)
            self.assertEqual(float(remaining["unit_cost"]), 12)
            self.assertEqual(float(remaining["remaining_qty"]), 4)
        finally:
            db.close()
        headers = self._login()
        created = self.api.create_product({
            "name": "QA-Adjust-Layer", "price": 30, "cost_price": 9, "stock": 2,
        })
        adjusted = self.client.post(
            f"/api/products/{created['id']}/adjust",
            headers=headers,
            json={"new_qty": 5, "expected_stock": 2, "reason": "QA count correction"},
        )
        self.assertEqual(adjusted.status_code, 200, adjusted.get_json())
        db = self.ac._db()
        try:
            stock = db.execute(
                "SELECT stock FROM products WHERE id=?", (created["id"],)
            ).fetchone()["stock"]
            layers = db.execute(
                "SELECT COALESCE(SUM(remaining_qty),0) FROM cost_layers WHERE product_id=?",
                (created["id"],),
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(float(stock), 5)
        self.assertEqual(float(layers), 5)


if __name__ == "__main__":
    unittest.main()
