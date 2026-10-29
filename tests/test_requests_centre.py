"""The Requests Centre lists existing workflows and does not create them."""
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


class RequestsCentreTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "centre.db")
        os.environ["MBT_DATA_ROOT"] = self._tmpdir.name
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        from desktop.utils.shop_time import shop_today
        ac._SCHEMA_READY = False
        self.ac = ac
        self.yesterday = (shop_today() - timedelta(days=1)).isoformat()
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("cashier", ac._hash_pw("cashier-pass"), "cashier", "Ada Cashier"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("manager", ac._hash_pw("manager-pass"), "manager", "Shop Manager"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("viewer", ac._hash_pw("viewer-pass"), "viewer", "Viewer"),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, is_active) VALUES (?,?,?,?,?,1)",
            ("Sugar", "SUG", 100, 60, 20),
        )
        db.commit()
        self.sugar = db.execute("SELECT id FROM products WHERE sku='SUG'").fetchone()["id"]
        cashier_id = db.execute("SELECT id FROM users WHERE username='cashier'").fetchone()["id"]
        db.execute(
            "INSERT INTO stock_adjustment_requests "
            "(request_number, product_id, product_name, current_stock, requested_qty, reason, status, user_id, username) "
            "VALUES ('STK-1', ?, 'Sugar', 20, 18, 'Count was short', 'pending', ?, 'cashier')",
            (self.sugar, cashier_id),
        )
        db.commit()
        db.close()
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        self.client = appmod.app.test_client()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _login(self, username):
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": f"{username}-pass"},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return {"Authorization": f"Bearer {response.get_json()['token']}"}

    def test_centre_lists_backdate_and_stock_without_posting(self):
        cashier = self._login("cashier")
        before = self.client.get("/api/requests-centre", headers=cashier)
        self.assertEqual(before.status_code, 200, before.get_json())
        self.assertEqual(before.get_json()["counts"]["all"], 1)
        created = self.client.post("/api/backdate-requests", headers=cashier, json={
            "business_date": self.yesterday,
            "reason": "Power was out",
            "sales": [{
                "payment_method": "Cash",
                "amount_paid": 200,
                "lines": [
                    {"product_id": self.sugar, "quantity": 1, "unit_price": 100},
                    {"product_id": self.sugar, "quantity": 1, "unit_price": 100},
                ],
            }],
        })
        self.assertEqual(created.status_code, 200, created.get_json())
        listed = self.client.get("/api/requests-centre?type=backdated_sale", headers=cashier)
        body = listed.get_json()
        self.assertEqual(len(body["requests"]), 1)
        self.assertEqual(body["requests"][0]["type_label"], "Backdated sale")
        self.assertIn("Power was out", body["requests"][0]["reason"])
        detail = self.client.get(
            f"/api/requests-centre/backdate/{created.get_json()['id']}",
            headers=cashier,
        )
        self.assertEqual(detail.status_code, 200, detail.get_json())
        self.assertEqual(len(detail.get_json()["sales"][0]["lines"]), 2)
        db = self.ac._db()
        sales = db.execute("SELECT COUNT(*) AS c FROM sales").fetchone()["c"]
        db.close()
        self.assertEqual(sales, 0)
        denied = self.client.get("/api/requests-centre", headers=self._login("viewer"))
        self.assertEqual(denied.status_code, 403)

    def test_cashier_cannot_see_another_cashiers_stock_request(self):
        manager = self._login("manager")
        seen = self.client.get("/api/requests-centre?type=stock_adjustment", headers=manager)
        self.assertEqual(seen.get_json()["total"], 1)
        action = self.client.get("/api/requests-centre?queue=action", headers=manager)
        self.assertTrue(any(row["type"] == "stock_adjustment" for row in action.get_json()["requests"]))
