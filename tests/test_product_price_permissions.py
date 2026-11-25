"""Product publishing, price approval, and each person's scroll interval."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ProductPricePermissionTests(unittest.TestCase):
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
        ac._SCHEMA_READY = False
        self.ac = ac
        db = ac._db()
        people = (
            ("admin", "admin", "Admin"),
            ("owner", "superadmin", "Owner"),
            ("manager", "manager", "Manager"),
            ("cashier", "cashier", "Cashier"),
            ("viewer", "viewer", "Viewer"),
        )
        for username, role, name in people:
            db.execute(
                "INSERT INTO users (username, password_hash, role, full_name, is_active) "
                "VALUES (?,?,?,?,1)",
                (username, ac._hash_pw("test-only"), role, name),
            )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('wheel_scroll_interval', '9')"
        )
        db.commit()
        self.ids = {
            row["username"]: row["id"]
            for row in db.execute("SELECT id, username FROM users").fetchall()
        }
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()

    def _api(self, username):
        api = self.ac.APIClient()
        api._user_id = self.ids[username]
        api._username = username
        api._role = {
            "admin": "admin",
            "owner": "superadmin",
            "manager": "manager",
            "cashier": "cashier",
            "viewer": "viewer",
        }[username]
        return api

    def _count(self, name=None):
        db = self.ac._db()
        try:
            if name:
                return db.execute(
                    "SELECT COUNT(*) FROM products WHERE name=?", (name,)
                ).fetchone()[0]
            return db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        finally:
            db.close()

    def _product(self, pid):
        db = self.ac._db()
        try:
            return dict(db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())
        finally:
            db.close()

    def _history(self, pid):
        db = self.ac._db()
        try:
            return {
                "sales": [tuple(row) for row in db.execute(
                    "SELECT id, total, discount, status FROM sales ORDER BY id"
                ).fetchall()],
                "items": [tuple(row) for row in db.execute(
                    "SELECT sale_id, product_id, quantity, unit_price, discount, total "
                    "FROM sale_items ORDER BY id"
                ).fetchall()],
                "layers": [tuple(row) for row in db.execute(
                    "SELECT product_id, original_qty, remaining_qty, unit_cost, "
                    "purchase_unit_cost, sell_price FROM cost_layers WHERE product_id=? ORDER BY id",
                    (pid,),
                ).fetchall()],
                "receipts": [tuple(row) for row in db.execute(
                    "SELECT id, grand_total FROM stock_receipts ORDER BY id"
                ).fetchall()],
                "receipt_lines": [tuple(row) for row in db.execute(
                    "SELECT product_id, quantity, unit_cost, line_total FROM stock_receipt_lines ORDER BY id"
                ).fetchall()],
                "stock": db.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()[0],
                "cost": db.execute("SELECT cost_price FROM products WHERE id=?", (pid,)).fetchone()[0],
            }
        finally:
            db.close()

    def test_admin_and_owner_price_does_not_rewrite_history(self):
        for username in ("admin", "owner"):
            with self.subTest(username=username):
                api = self._api(username)
                created = api.create_product({
                    "name": f"History {username}",
                    "price": 100,
                    "cost_price": 40,
                    "stock": 8,
                    "unit": "pcs",
                })
                self.assertTrue(created.get("success"), created)
                self.assertFalse(created.get("pending_approval"))
                pid = created["id"]
                sold = self._api("cashier").create_sale({
                    "items": [{"product_id": pid, "quantity": 1, "unit_price": 100, "discount": 0}],
                    "subtotal": 100, "discount": 0, "tax": 0, "total": 100,
                    "payment_method": "Cash", "amount_paid": 100, "change_amount": 0,
                })
                self.assertTrue(sold.get("success") or sold.get("id"), sold)
                db = self.ac._db()
                db.execute(
                    "INSERT INTO stock_receipts (receipt_number, grand_total, username) VALUES (?,?,?)",
                    (f"GRN-{username}", 320, username),
                )
                receipt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                db.execute(
                    "INSERT INTO stock_receipt_lines (receipt_id, product_id, product_name, quantity, unit_cost, line_total) "
                    "VALUES (?,?,?,?,?,?)",
                    (receipt_id, pid, f"History {username}", 8, 40, 320),
                )
                db.commit()
                db.close()
                before = self._history(pid)
                changed = api.update_product(pid, {"price": 175})
                self.assertTrue(changed.get("success"), changed)
                self.assertFalse(changed.get("pending_approval"))
                after = self._history(pid)
                self.assertEqual(after["sales"], before["sales"])
                self.assertEqual(after["items"], before["items"])
                self.assertEqual(after["layers"], before["layers"])
                self.assertEqual(after["receipts"], before["receipts"])
                self.assertEqual(after["receipt_lines"], before["receipt_lines"])
                self.assertEqual(after["stock"], before["stock"])
                self.assertEqual(after["cost"], before["cost"])
                self.assertEqual(self._product(pid)["price"], 175)
                self.assertEqual(self._product(pid)["unit"], "pcs")

    def test_manager_publish_and_price_wait_for_admin(self):
        admin = self._api("admin")
        manager = self._api("manager")
        live = admin.create_product({"name": "Live Soap", "price": 50, "cost_price": 20, "stock": 4, "unit": "pcs"})
        self.assertTrue(live.get("success"), live)
        pid = live["id"]
        queued = manager.update_product(pid, {"price": 80, "unit": "kg", "allow_decimal_qty": 1})
        self.assertTrue(queued.get("pending_approval"), queued)
        card = self._product(pid)
        self.assertEqual(card["price"], 50)
        self.assertEqual(card["unit"], "pcs")
        self.assertNotEqual(card.get("allow_decimal_qty"), 1)
        own = manager.execute_approval(queued["request_id"], "reject", note="no")
        self.assertEqual(own.get("status"), 403)
        rejected = admin.execute_approval(queued["request_id"], "reject", note="no")
        self.assertEqual(rejected.get("status"), "rejected")
        card = self._product(pid)
        self.assertEqual(card["price"], 50)
        self.assertEqual(card["unit"], "pcs")
        again = manager.update_product(pid, {"price": 90, "unit": "kg", "allow_decimal_qty": 1})
        self.assertEqual(again.get("request_id"), queued["request_id"])
        self.assertTrue(again.get("replaced_request"))
        self.assertEqual(self._product(pid)["price"], 50)
        approved = admin.execute_approval(queued["request_id"], "approve", note="yes")
        self.assertTrue(approved.get("success"), approved)
        card = self._product(pid)
        self.assertEqual(card["price"], 90)
        self.assertEqual(card["unit"], "kg")
        self.assertEqual(card["allow_decimal_qty"], 1)
        self.assertEqual(card["stock"], 4)
        self.assertEqual(card["cost_price"], 20)
        duplicate = admin.execute_approval(queued["request_id"], "approve", note="again")
        self.assertTrue(duplicate.get("duplicate") or duplicate.get("success"))
        self.assertEqual(self._count("Live Soap"), 1)

    def test_manager_resubmit_does_not_duplicate_the_product(self):
        manager = self._api("manager")
        admin = self._api("admin")
        first = manager.create_product({"name": "Pending Meal", "price": 10, "unit": "pcs", "stock": 3})
        self.assertTrue(first.get("pending_approval"), first)
        self.assertIsNone(first.get("id"))
        self.assertEqual(self._count("Pending Meal"), 0)
        second = manager.create_product({"name": "Pending Meal", "price": 12, "unit": "pcs", "stock": 3})
        self.assertEqual(second.get("request_id"), first["request_id"])
        self.assertEqual(self._count("Pending Meal"), 0)
        admin.execute_approval(first["request_id"], "reject", note="fix the price")
        self.assertEqual(self._count("Pending Meal"), 0)
        third = manager.create_product({"name": "Pending Meal", "price": 15, "unit": "pcs", "stock": 3})
        self.assertEqual(third.get("request_id"), first["request_id"])
        published = admin.execute_approval(first["request_id"], "approve", note="publish")
        self.assertTrue(published.get("success"), published)
        self.assertEqual(self._count("Pending Meal"), 1)
        row = self.ac._db().execute("SELECT price, stock FROM products WHERE name='Pending Meal'").fetchone()
        self.ac._db().close()
        self.assertEqual(row["price"], 15)
        self.assertEqual(row["stock"], 3)
        again = admin.execute_approval(first["request_id"], "approve", note="publish")
        self.assertTrue(again.get("duplicate") or again.get("status") == "approved")
        self.assertEqual(self._count("Pending Meal"), 1)

    def test_cashier_can_sell_and_request_but_not_change_the_product(self):
        admin = self._api("admin")
        cashier = self._api("cashier")
        viewer = self._api("viewer")
        created = admin.create_product({"name": "Till Item", "price": 30, "cost_price": 10, "stock": 5, "unit": "pcs"})
        pid = created["id"]
        sale = cashier.create_sale({
            "items": [{"product_id": pid, "quantity": 1, "unit_price": 30, "discount": 0}],
            "subtotal": 30, "discount": 0, "tax": 0, "total": 30,
            "payment_method": "Cash", "amount_paid": 30, "change_amount": 0,
        })
        self.assertTrue(sale.get("success") or sale.get("id"), sale)
        self.assertEqual(cashier.create_product({"name": "Nope", "price": 1}).get("status"), 403)
        self.assertEqual(cashier.update_product(pid, {"price": 99, "unit": "kg"}).get("status"), 403)
        request = cashier.request_sale_correction({
            "type": "price_override",
            "product_id": pid,
            "product_name": "Till Item",
            "amount": 20,
            "reason": "Customer was quoted 20",
        })
        self.assertTrue(request.get("pending_approval"), request)
        discount = cashier.request_sale_correction({
            "type": "large_discount",
            "product_name": "Till Item",
            "amount": 5,
            "reason": "Loyalty discount",
        })
        self.assertTrue(discount.get("success"), discount)
        self.assertEqual(self._product(pid)["price"], 30)
        self.assertEqual(self._product(pid)["unit"], "pcs")
        self.assertEqual(cashier.execute_approval(request["id"], "approve").get("status"), 403)
        approved = admin.execute_approval(request["id"], "approve", note="noted")
        self.assertTrue(approved.get("success"), approved)
        self.assertEqual(self._product(pid)["price"], 30)
        self.assertEqual(viewer.create_product({"name": "Hidden", "price": 1}).get("status"), 403)
        self.assertEqual(viewer.update_product(pid, {"price": 1}).get("status"), 403)
        self.assertEqual(viewer.create_sale({
            "items": [{"product_id": pid, "quantity": 1, "unit_price": 30}],
            "subtotal": 30, "total": 30, "payment_method": "Cash", "amount_paid": 30,
        }).get("status"), 403)
        self.assertEqual(viewer.execute_approval(discount["id"], "approve").get("status"), 403)
        self.assertEqual(viewer.request_sale_correction({
            "type": "large_discount", "amount": 1, "reason": "Should fail now",
        }).get("status"), 403)
        self.assertEqual(self._product(pid)["price"], 30)

    def test_direct_price_grant_applies_and_stops_when_revoked(self):
        admin = self._api("admin")
        manager = self._api("manager")
        created = admin.create_product({"name": "Granted", "price": 10, "cost_price": 4, "stock": 2, "unit": "pcs"})
        pid = created["id"]
        waiting = manager.update_product(pid, {"price": 18})
        self.assertTrue(waiting.get("pending_approval"), waiting)
        self.assertEqual(self._product(pid)["price"], 10)
        db = self.ac._db()
        db.execute(
            "UPDATE users SET permission_grants=? WHERE id=?",
            ('["inventory.direct_price"]', self.ids["manager"]),
        )
        db.commit()
        db.close()
        direct = manager.update_product(pid, {"price": 18})
        self.assertTrue(direct.get("success"), direct)
        self.assertFalse(direct.get("pending_approval"))
        self.assertEqual(self._product(pid)["price"], 18)
        self.assertEqual(self._product(pid)["cost_price"], 4)
        self.assertEqual(self._product(pid)["stock"], 2)
        db = self.ac._db()
        db.execute("UPDATE users SET permission_grants='[]' WHERE id=?", (self.ids["manager"],))
        db.commit()
        db.close()
        revoked = manager.update_product(pid, {"price": 40})
        self.assertTrue(revoked.get("pending_approval"), revoked)
        self.assertEqual(self._product(pid)["price"], 18)

    def test_scroll_interval_belongs_to_one_user(self):
        cashier = self._api("cashier")
        viewer = self._api("viewer")
        admin = self._api("admin")
        self.assertEqual(cashier.read_wheel_scroll()["wheel_scroll_interval"], 3)
        saved = cashier.save_wheel_scroll(8)
        self.assertEqual(saved.get("wheel_scroll_interval"), 8)
        self.assertEqual(viewer.save_wheel_scroll(2).get("wheel_scroll_interval"), 2)
        self.assertEqual(cashier.read_wheel_scroll()["wheel_scroll_interval"], 8)
        self.assertEqual(viewer.read_wheel_scroll()["wheel_scroll_interval"], 2)
        self.assertEqual(cashier.save_wheel_scroll(0).get("status"), 400)
        self.assertEqual(cashier.read_wheel_scroll()["wheel_scroll_interval"], 8)
        shop = admin.update_settings({"shop_name": "Disposable QA", "wheel_scroll_interval": 4})
        self.assertTrue(shop.get("success"), shop)
        self.assertEqual(admin.read_wheel_scroll()["wheel_scroll_interval"], 4)
        self.assertEqual(cashier.read_wheel_scroll()["wheel_scroll_interval"], 8)
        db = self.ac._db()
        try:
            stored = db.execute(
                "SELECT value FROM system_settings WHERE key='wheel_scroll_interval'"
            ).fetchone()[0]
            cashier_value = db.execute(
                "SELECT wheel_scroll_interval FROM users WHERE id=?", (self.ids["cashier"],)
            ).fetchone()[0]
            viewer_value = db.execute(
                "SELECT wheel_scroll_interval FROM users WHERE id=?", (self.ids["viewer"],)
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(stored, "9")
        self.assertEqual(cashier_value, 8)
        self.assertEqual(viewer_value, 2)


if __name__ == "__main__":
    unittest.main()
