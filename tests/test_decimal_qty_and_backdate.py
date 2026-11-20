"""Decimal quantities stay exact. Cashier backdating waits for another person."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_ISOLATION = tempfile.mkdtemp(prefix="mbt-qty-")
os.environ["MBT_DATA_ROOT"] = _ISOLATION
os.environ["APPDATA"] = os.path.join(_ISOLATION, "roaming")
os.environ["LOCALAPPDATA"] = os.path.join(_ISOLATION, "local")
os.environ["PROGRAMDATA"] = os.path.join(_ISOLATION, "programdata")
os.environ["MBT_TEST_INSTANCE"] = "1"


class QuantityRuleTests(unittest.TestCase):
    def test_every_unit_keeps_a_decimal_quantity(self):
        from desktop.utils.quantities import QuantityError, parse_quantity, money_amount
        self.assertEqual(parse_quantity("0.75", "kg"), 0.75)
        self.assertEqual(parse_quantity("0.25", "litres"), 0.25)
        self.assertEqual(parse_quantity("0.5", "kg"), 0.5)
        self.assertEqual(parse_quantity("1.25", "kg"), 1.25)
        self.assertEqual(parse_quantity("2.50", "kg"), 2.5)
        self.assertEqual(parse_quantity("1.50", "metres"), 1.5)
        self.assertEqual(parse_quantity(1, "pcs"), 1.0)
        self.assertEqual(parse_quantity("2", "piece"), 2.0)
        self.assertEqual(money_amount("10.005"), __import__("decimal").Decimal("10.01"))
        for raw, unit in (("0", "kg"), ("-1", "kg"), ("abc", "kg"), ("1.23456", "pcs"),
                          ("0.5", "pcs"), ("1.25", "piece"), ("2.25", "pieces")):
            with self.assertRaises(QuantityError):
                parse_quantity(raw, unit)
        refused = None
        try:
            parse_quantity("1.25", "pcs")
        except QuantityError as exc:
            refused = str(exc)
        self.assertIn("whole", (refused or "").lower())
        self.assertEqual(parse_quantity("1.25", "kg"), 1.25)

    def test_sale_line_keeps_three_quarter_kilos(self):
        from backend.sale_lines import fill_sale_line
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE products (id INTEGER, name TEXT, sku TEXT, unit TEXT)")
        db.execute("INSERT INTO products VALUES (1, 'Sugar', 'SUG', 'kg')")
        db.execute("INSERT INTO products VALUES (2, 'Cup', 'CUP', 'pcs')")
        line = fill_sale_line(db, {
            "product_id": 1, "quantity": "0.75", "unit_price": "200", "discount": "10",
        })
        self.assertEqual(line["quantity"], 0.75)
        self.assertEqual(line["total"], 140.0)
        with self.assertRaises(ValueError) as refused_pieces:
            fill_sale_line(db, {"product_id": 2, "quantity": "0.5", "unit_price": "20"})
        self.assertIn("whole", str(refused_pieces.exception).lower())
        with self.assertRaises(ValueError) as refused_quarters:
            fill_sale_line(db, {"product_id": 2, "quantity": "1.25", "unit_price": "20"})
        self.assertIn("whole", str(refused_quarters.exception).lower())
        db.close()


class DatedActionTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "shop.db")
        os.environ["MBT_DATA_ROOT"] = self._tmpdir.name
        os.environ["APPDATA"] = os.path.join(self._tmpdir.name, "roaming")
        os.environ["LOCALAPPDATA"] = os.path.join(self._tmpdir.name, "local")
        os.environ["PROGRAMDATA"] = os.path.join(self._tmpdir.name, "programdata")
        os.environ["MBT_TEST_INSTANCE"] = "1"
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
        self.today = shop_today().isoformat()
        self.yesterday = (shop_today() - timedelta(days=1)).isoformat()
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) "
            "VALUES (?,?,?,?,1)",
            ("ada", "x", "cashier", "Ada Cashier"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) "
            "VALUES (?,?,?,?,1)",
            ("boss", "x", "admin", "Boss Admin"),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, unit, is_active) "
            "VALUES (?,?,?,?,?,?,1)",
            ("Bulk sugar", "BULK", 200, 100, 10, "kg"),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, unit, is_active) "
            "VALUES (?,?,?,?,?,?,1)",
            ("Cup", "CUP", 20, 5, 8, "pcs"),
        )
        db.execute("INSERT INTO departments (name, active) VALUES ('Staff', 1)")
        db.commit()
        self.sugar = db.execute("SELECT id FROM products WHERE sku='BULK'").fetchone()["id"]
        self.cup = db.execute("SELECT id FROM products WHERE sku='CUP'").fetchone()["id"]
        self.cashier = db.execute("SELECT id FROM users WHERE username='ada'").fetchone()["id"]
        self.admin = db.execute("SELECT id FROM users WHERE username='boss'").fetchone()["id"]
        self.dept = db.execute("SELECT id FROM departments").fetchone()["id"]
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self._tmpdir.cleanup()

    def _api(self, user_id, role, name):
        api = self.ac.APIClient()
        api._user_id = user_id
        api._role = role
        api._username = name
        return api

    def _stock(self, product_id):
        db = self.ac._db()
        try:
            return db.execute("SELECT stock FROM products WHERE id=?", (product_id,)).fetchone()["stock"]
        finally:
            db.close()

    def _consumption(self, day, qty="0.75", product=None, token="tok-1"):
        return {
            "date": day,
            "department_id": self.dept,
            "reason": "Staff Consumption",
            "backdate_reason": "Transaction entered late",
            "notes": "QA",
            "taken_by": "Ada",
            "client_token": token,
            "items": [{"product_id": product or self.sugar, "quantity": qty}],
        }

    def test_cashier_backdate_does_not_post_until_another_admin_approves_once(self):
        cashier = self._api(self.cashier, "cashier", "Ada Cashier")
        pending = cashier.create_consumption(self._consumption(self.yesterday))
        self.assertTrue(pending.get("pending_approval"))
        self.assertEqual(pending["status"], "pending")
        self.assertIn("administrator approval", pending["warning"])
        self.assertEqual(self._stock(self.sugar), 10)
        changed = cashier.create_consumption(self._consumption(self.today, token="tok-1"))
        self.assertEqual(changed["business_date"], self.yesterday)
        self.assertTrue(changed.get("duplicate"))
        own = cashier.approve_dated_action(pending["id"])
        self.assertEqual(own.get("status"), 403)
        self.assertIn("own request", own.get("error", ""))
        self.assertEqual(self._stock(self.sugar), 10)
        db = self.ac._db()
        db.execute("UPDATE users SET role='admin' WHERE id=?", (self.cashier,))
        db.commit()
        db.close()
        promoted = self._api(self.cashier, "admin", "Ada Cashier")
        still = promoted.approve_dated_action(pending["id"])
        self.assertEqual(still.get("status"), 403)
        self.assertEqual(self._stock(self.sugar), 10)
        missing = self._api(self.admin, "admin", "Boss Admin").reject_dated_action(pending["id"], "")
        self.assertIn("reason", missing.get("error", "").lower())
        admin = self._api(self.admin, "admin", "Boss Admin")
        posted = admin.approve_dated_action(pending["id"])
        self.assertEqual(posted["status"], "approved")
        self.assertFalse(posted.get("already_approved"))
        self.assertAlmostEqual(self._stock(self.sugar), 9.25, places=2)
        again = admin.approve_dated_action(pending["id"])
        self.assertTrue(again.get("already_approved") or again.get("duplicate"))
        self.assertAlmostEqual(self._stock(self.sugar), 9.25, places=2)
        row = self.ac._db()
        saved = row.execute(
            "SELECT date, created_at FROM stock_consumptions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        row.close()
        self.assertEqual(saved["date"][:10], self.yesterday)
        self.assertNotEqual(saved["created_at"][:10], saved["date"][:10])

    def test_rejected_request_does_not_post_and_bad_quantities_are_refused(self):
        cashier = self._api(self.cashier, "cashier", "Ada Cashier")
        pending = cashier.create_consumption(self._consumption(self.yesterday, token="rej-1"))
        admin = self._api(self.admin, "admin", "Boss Admin")
        rejected = admin.reject_dated_action(pending["id"], "Wrong day")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(self._stock(self.sugar), 10)
        approved = admin.approve_dated_action(pending["id"])
        self.assertEqual(approved.get("status"), 409)
        self.assertEqual(self._stock(self.sugar), 10)
        for qty in ("0", "-1", "abc", "1.23456"):
            refused = cashier.create_consumption(
                self._consumption(self.today, qty=qty, token=f"bad-{qty}")
            )
            self.assertTrue(refused.get("error"), qty)
        pieces = cashier.create_consumption(
            self._consumption(self.today, qty="0.5", product=self.cup, token="piece")
        )
        self.assertIn("whole", pieces.get("error", "").lower())
        self.assertEqual(self._stock(self.cup), 8)
        quarters = cashier.create_consumption(
            self._consumption(self.today, qty="1.25", product=self.cup, token="piece-125")
        )
        self.assertIn("whole", quarters.get("error", "").lower())
        self.assertEqual(self._stock(self.cup), 8)
        explained = cashier.create_consumption({
            **self._consumption(self.yesterday, token="other-written"),
            "backdate_reason": "Other: the shop was closed",
        })
        self.assertTrue(explained.get("pending_approval"), explained)
        self.assertIn("shop was closed", explained.get("warning", "") + str(explained))
        self.assertEqual(self._stock(self.sugar), 10)
        listed = cashier.create_consumption({
            **self._consumption(self.yesterday, token="listed-reason"),
            "backdate_reason": "Transaction entered late",
        })
        self.assertTrue(listed.get("pending_approval"), listed)
        self.assertEqual(self._stock(self.sugar), 10)
        offline = cashier.create_consumption({
            **self._consumption(self.yesterday, token="off-1"),
            "offline": True,
        })
        self.assertIn("offline", offline.get("error", "").lower())
        self.assertEqual(self._stock(self.sugar), 10)
        db = self.ac._db()
        db.execute("INSERT INTO suppliers (name, is_active) VALUES ('Mill', 1)")
        db.commit()
        supplier = db.execute("SELECT id FROM suppliers").fetchone()["id"]
        db.close()
        refused_delivery = self._api(self.admin, "admin", "Boss Admin").receive_delivery(
            supplier,
            [
                {"product_id": self.cup, "quantity": "0.5", "unit_cost": 6},
                {"product_id": self.sugar, "quantity": "1.25", "unit_cost": 90},
            ],
            client_token="recv-piece-fraction",
        )
        self.assertIn("whole", refused_delivery.get("error", "").lower())
        self.assertEqual(self._stock(self.cup), 8)
        self.assertEqual(self._stock(self.sugar), 10)
        delivered = self._api(self.admin, "admin", "Boss Admin").receive_delivery(
            supplier,
            [
                {"product_id": self.cup, "quantity": "2", "unit_cost": 6},
                {"product_id": self.sugar, "quantity": "1.25", "unit_cost": 90},
            ],
            client_token="recv-decimal",
        )
        self.assertTrue(delivered.get("success") or delivered.get("receipt_id"), delivered)
        self.assertAlmostEqual(self._stock(self.cup), 10.0, places=2)
        self.assertAlmostEqual(self._stock(self.sugar), 11.25, places=2)

    def test_closed_period_and_future_date_are_refused(self):
        db = self.ac._db()
        db.execute(
            """CREATE TABLE IF NOT EXISTS accounting_periods (
                id INTEGER PRIMARY KEY, name TEXT, start_date TEXT, end_date TEXT, status TEXT
            )"""
        )
        db.execute(
            "INSERT INTO accounting_periods (name, start_date, end_date, status) VALUES (?,?,?,?)",
            ("Closed", self.yesterday, self.yesterday, "closed"),
        )
        db.commit()
        db.close()
        cashier = self._api(self.cashier, "cashier", "Ada Cashier")
        closed = cashier.create_consumption(self._consumption(self.yesterday, token="closed"))
        self.assertIn("closed", closed.get("error", "").lower())
        future = cashier.create_consumption(self._consumption("2999-01-01", token="future"))
        self.assertIn("future", future.get("error", "").lower())
        self.assertEqual(self._stock(self.sugar), 10)

    def test_stocktake_variance_is_applied_once(self):
        from desktop.utils.stocktake import apply_stocktake, record_count, start_stocktake
        db = self.ac._db()
        db.execute("UPDATE products SET stock=12.75 WHERE id=?", (self.sugar,))
        db.commit()
        opened = start_stocktake(db, "Morning")
        db.commit()
        saved = record_count(db, opened["id"], self.sugar, "11.50")
        self.assertTrue(saved.get("success"))
        self.assertEqual(db.execute("SELECT stock FROM products WHERE id=?", (self.sugar,)).fetchone()["stock"], 12.75)
        db.commit()
        applied = apply_stocktake(db, opened["id"], username="boss", user_id=self.admin)
        self.assertTrue(applied.get("success"))
        self.assertAlmostEqual(db.execute("SELECT stock FROM products WHERE id=?", (self.sugar,)).fetchone()["stock"], 11.5, places=2)
        movement = db.execute(
            "SELECT qty_change FROM stock_movements WHERE reference=?",
            (f"STK:{opened['id']}:{self.sugar}",),
        ).fetchone()
        self.assertEqual(round(movement["qty_change"], 2), -1.25)
        again = apply_stocktake(db, opened["id"], username="boss", user_id=self.admin)
        self.assertTrue(again.get("duplicate"))
        self.assertAlmostEqual(db.execute("SELECT stock FROM products WHERE id=?", (self.sugar,)).fetchone()["stock"], 11.5, places=2)
        piece_take = start_stocktake(db, "Piece count")
        db.commit()
        piece = record_count(db, piece_take["id"], self.cup, "1.5")
        self.assertIn("whole", piece.get("error", "").lower())
        self.assertEqual(db.execute("SELECT stock FROM products WHERE id=?", (self.cup,)).fetchone()["stock"], 8)
        whole = record_count(db, piece_take["id"], self.cup, "2")
        self.assertTrue(whole.get("success"), whole)
        self.assertEqual(db.execute("SELECT stock FROM products WHERE id=?", (self.cup,)).fetchone()["stock"], 8)
        stranger = self._api(self.cashier, "cashier", "Ada Cashier").apply_stocktake(opened["id"])
        self.assertEqual(stranger.get("status"), 403)
        db.close()


if __name__ == "__main__":
    unittest.main()
