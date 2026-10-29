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


if __name__ == "__main__":
    unittest.main()
