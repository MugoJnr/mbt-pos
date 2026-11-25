"""Receipt-first partial return: original prices, request, PIN, damaged goods."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ReceiptReturn570(unittest.TestCase):
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
        self.owner = ac.APIClient()
        self.owner._role = "superadmin"
        self.owner._username = "admin"
        db = ac._db()
        row = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        if row:
            self.owner._user_id = int(row["id"])
            db.execute("UPDATE users SET role='superadmin' WHERE id=?", (self.owner._user_id,))
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, role, full_name) VALUES (?,?,?,?)",
                ("admin", "x:y", "superadmin", "Shop Owner"),
            )
            self.owner._user_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        from desktop.utils.superadmin_pin import set_superadmin_user_pin
        set_superadmin_user_pin(db, self.owner._user_id, "246810")
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name) VALUES (?,?,?,?)",
            ("qa_brian", "x:y", "cashier", "QA Cashier Brian"),
        )
        self.cashier_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        self.ids = {}
        for name, price, stock in (
            ("Cooking Oil", 250.0, 20),
            ("Sugar", 180.0, 20),
            ("Rice", 160.0, 20),
        ):
            db.execute(
                "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) VALUES (?,?,?,?,?,?)",
                (name, name[:3].upper(), price, 40.0, stock, 1),
            )
            self.ids[name] = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.commit()
        db.close()
        self.cashier = ac.APIClient()
        self.cashier._role = "cashier"
        self.cashier._user_id = self.cashier_id
        self.cashier._username = "qa_brian"

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _sell(self):
        created = self.owner.create_sale({
            "items": [
                {"product_id": self.ids["Cooking Oil"], "product_name": "Cooking Oil", "quantity": 3, "unit_price": 250, "discount": 0, "total": 750},
                {"product_id": self.ids["Sugar"], "product_name": "Sugar", "quantity": 2, "unit_price": 180, "discount": 0, "total": 360},
                {"product_id": self.ids["Rice"], "product_name": "Rice", "quantity": 5, "unit_price": 160, "discount": 0, "total": 800},
            ],
            "subtotal": 1910, "total": 1910, "payment_method": "Cash",
            "amount_paid": 1910, "change_amount": 0,
        })
        self.assertTrue(created.get("success"), created)
        lookup = self.owner.get_sale_for_return(created["receipt_number"])
        self.assertTrue(lookup.get("success"), lookup)
        by_name = {row["product_name"]: row for row in lookup["items"]}
        return created, by_name

    def test_partial_return_uses_charged_prices(self):
        created, by_name = self._sell()
        original_total = float(self.ac._db().execute(
            "SELECT total FROM sales WHERE id=?", (created["sale_id"],)
        ).fetchone()["total"])
        self.ac._db().close()
        ret = self.owner.return_sale(
            int(created["sale_id"]),
            [
                {"sale_item_id": by_name["Cooking Oil"]["id"], "quantity": 1},
                {"sale_item_id": by_name["Rice"]["id"], "quantity": 2},
            ],
            "customer returned one oil and two rice",
            refund_method="Cash",
        )
        self.assertTrue(ret.get("executed"), ret)
        self.assertAlmostEqual(float(ret["refund_total"]), 570.0, places=2)
        db = self.ac._db()
        original = db.execute(
            "SELECT total, status FROM sales WHERE id=?", (created["sale_id"],)
        ).fetchone()
        self.assertEqual(original["status"], "completed")
        self.assertAlmostEqual(float(original["total"]), original_total, places=2)
        oil = float(db.execute("SELECT stock FROM products WHERE id=?", (self.ids["Cooking Oil"],)).fetchone()["stock"])
        rice = float(db.execute("SELECT stock FROM products WHERE id=?", (self.ids["Rice"],)).fetchone()["stock"])
        sugar = float(db.execute("SELECT stock FROM products WHERE id=?", (self.ids["Sugar"],)).fetchone()["stock"])
        db.close()
        self.assertEqual(oil, 18.0)
        self.assertEqual(rice, 17.0)
        self.assertEqual(sugar, 18.0)

    def test_cashier_request_does_not_move_stock(self):
        created, by_name = self._sell()
        before = float(self.ac._db().execute(
            "SELECT stock FROM products WHERE id=?", (self.ids["Cooking Oil"],)
        ).fetchone()["stock"])
        self.ac._db().close()
        queued = self.cashier.return_sale(
            int(created["sale_id"]),
            [{"sale_item_id": by_name["Cooking Oil"]["id"], "quantity": 1}],
            "customer wants one oil back",
        )
        self.assertTrue(queued.get("pending_approval"), queued)
        self.assertFalse(queued.get("executed"))
        self.assertAlmostEqual(float(queued["refund_total"]), 250.0, places=2)
        db = self.ac._db()
        stock = float(db.execute(
            "SELECT stock FROM products WHERE id=?", (self.ids["Cooking Oil"],)
        ).fetchone()["stock"])
        returns = db.execute("SELECT COUNT(*) AS c FROM sales WHERE status='return'").fetchone()["c"]
        db.close()
        self.assertEqual(stock, before)
        self.assertEqual(int(returns), 0)
        done = self.owner.execute_approval(int(queued["id"]), "approve", note="checked the receipt")
        self.assertTrue(done.get("success"), done)
        db = self.ac._db()
        stock = float(db.execute(
            "SELECT stock FROM products WHERE id=?", (self.ids["Cooking Oil"],)
        ).fetchone()["stock"])
        linked = db.execute(
            "SELECT COUNT(*) AS c FROM sales WHERE status='return' AND original_sale_id=?",
            (created["sale_id"],),
        ).fetchone()["c"]
        db.close()
        self.assertEqual(stock, before + 1)
        self.assertEqual(int(linked), 1)

    def test_cashier_pin_executes_once_and_damaged_is_not_restocked(self):
        created, by_name = self._sell()
        before = float(self.ac._db().execute(
            "SELECT stock FROM products WHERE id=?", (self.ids["Rice"],)
        ).fetchone()["stock"])
        self.ac._db().close()
        refused = self.cashier.return_sale(
            int(created["sale_id"]),
            [{"sale_item_id": by_name["Rice"]["id"], "quantity": 2}],
            "wrong pin",
            pin="0000",
            pin_username="admin",
            condition="damaged",
        )
        self.assertEqual(refused.get("status"), 403)
        self.assertFalse(refused.get("executed"))
        done = self.cashier.return_sale(
            int(created["sale_id"]),
            [{"sale_item_id": by_name["Rice"]["id"], "quantity": 2}],
            "two rice bags were damaged",
            pin="246810",
            pin_username="admin",
            condition="damaged",
        )
        self.assertTrue(done.get("executed"), done)
        self.assertAlmostEqual(float(done["refund_total"]), 320.0, places=2)
        self.assertEqual(done.get("authoriser"), "admin")
        db = self.ac._db()
        stock = float(db.execute(
            "SELECT stock FROM products WHERE id=?", (self.ids["Rice"],)
        ).fetchone()["stock"])
        damaged = db.execute(
            "SELECT COUNT(*) AS c FROM stock_movements WHERE movement_type='RETURN_DAMAGED'"
        ).fetchone()["c"]
        db.close()
        self.assertEqual(stock, before)
        self.assertGreaterEqual(int(damaged), 1)
