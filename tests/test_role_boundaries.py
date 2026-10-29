"""Shop API must not leak secrets or let an Admin take a Super Admin account."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class RoleBoundaryTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "roles.db")
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
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("owner", ac._hash_pw("owner-pass"), "superadmin", "Owner"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("shop-admin", ac._hash_pw("admin-pass"), "admin", "Shop Admin"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("cashier", ac._hash_pw("cashier-pass"), "cashier", "Cashier"),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock, is_active) "
            "VALUES ('Role Soap', 'ROLE-SOAP', 20, 8, 4, 1, 1)"
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES ('superadmin_pin_hash', 'hash-value', '')"
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES ('telegram_bot_token', 'token-value', '')"
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES ('currency_symbol', 'KES', '')"
        )
        db.commit()
        self.product_id = db.execute("SELECT id FROM products WHERE sku='ROLE-SOAP'").fetchone()["id"]
        self.owner_id = db.execute("SELECT id FROM users WHERE username='owner'").fetchone()["id"]
        db.close()
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        self.client = appmod.app.test_client()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _login(self, username, password):
        response = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.get_json())
        return {"Authorization": f"Bearer {response.get_json()['token']}"}

    def test_profile_and_settings_hide_secrets(self):
        headers = self._login("cashier", "cashier-pass")
        me = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(me.status_code, 200, me.get_json())
        body = me.get_json()
        self.assertEqual(body["role"], "cashier")
        self.assertNotIn("password_hash", body)
        settings = self.client.get("/api/settings", headers=headers)
        self.assertEqual(settings.status_code, 200, settings.get_json())
        shown = settings.get_json()
        self.assertEqual(shown.get("currency_symbol"), "KES")
        self.assertEqual(shown.get("pin_configured"), "1")
        self.assertNotIn("superadmin_pin_hash", shown)
        self.assertNotIn("telegram_bot_token", shown)
        self.assertNotIn("hash-value", str(shown))
        self.assertNotIn("token-value", str(shown))

    def test_admin_cannot_take_over_superadmin_or_pin(self):
        headers = self._login("shop-admin", "admin-pass")
        takeover = self.client.put(
            f"/api/users/{self.owner_id}",
            headers=headers,
            json={"password": "stolen-pass", "role": "superadmin"},
        )
        self.assertEqual(takeover.status_code, 403, takeover.get_json())
        still = self.client.post("/api/auth/login", json={"username": "owner", "password": "owner-pass"})
        self.assertEqual(still.status_code, 200)
        pin = self.client.put("/api/settings", headers=headers, json={"superadmin_pin_hash": "new-hash"})
        self.assertEqual(pin.status_code, 400, pin.get_json())
        promote = self.client.post(
            "/api/users",
            headers=headers,
            json={"username": "second-owner", "password": "second-pass", "role": "superadmin"},
        )
        self.assertEqual(promote.status_code, 403, promote.get_json())

    def test_only_an_administrator_can_remove_a_product_or_other_staff(self):
        open_delete = self.client.delete(f"/api/products/{self.product_id}")
        self.assertEqual(open_delete.status_code, 401)
        api = self.ac.APIClient()
        api._role = "member"
        api._user_id = 9
        api._username = "member"
        denied = api.delete_product(self.product_id)
        self.assertEqual(denied.get("status"), 403)
        cashier_headers = self._login("cashier", "cashier-pass")
        cashier_removed = self.client.delete(
            f"/api/products/{self.product_id}", headers=cashier_headers,
        )
        self.assertEqual(cashier_removed.status_code, 403, cashier_removed.get_json())
        cashier = self.ac.APIClient()
        cashier._role = "cashier"
        cashier._username = "cashier"
        db = self.ac._db()
        cashier._user_id = db.execute(
            "SELECT id FROM users WHERE username='cashier'"
        ).fetchone()["id"]
        db.close()
        staff_blocked = cashier.update_user(self.owner_id, {"is_active": 0})
        self.assertTrue(staff_blocked.get("error"))
        db = self.ac._db()
        still_active = db.execute(
            "SELECT is_active FROM products WHERE id=?", (self.product_id,)
        ).fetchone()["is_active"]
        owner_active = db.execute(
            "SELECT is_active FROM users WHERE id=?", (self.owner_id,)
        ).fetchone()["is_active"]
        cashier_id = cashier._user_id
        db.close()
        self.assertEqual(int(still_active), 1)
        self.assertEqual(int(owner_active), 1)

        admin_headers = self._login("shop-admin", "admin-pass")
        removed = self.client.delete(f"/api/products/{self.product_id}", headers=admin_headers)
        self.assertEqual(removed.status_code, 200, removed.get_json())
        admin = self.ac.APIClient()
        admin._role = "admin"
        admin._username = "shop-admin"
        db = self.ac._db()
        admin._user_id = db.execute(
            "SELECT id FROM users WHERE username='shop-admin'"
        ).fetchone()["id"]
        db.close()
        deactivated = admin.update_user(cashier_id, {"is_active": 0})
        self.assertTrue(deactivated.get("success"), deactivated)
        own = admin.update_user(admin._user_id, {"is_active": 0})
        self.assertEqual(own.get("status"), 400)
        owner = admin.delete_user(self.owner_id)
        self.assertEqual(owner.get("status"), 403)
        db = self.ac._db()
        active = db.execute(
            "SELECT is_active FROM products WHERE id=?", (self.product_id,)
        ).fetchone()["is_active"]
        cashier_row = db.execute(
            "SELECT is_active FROM users WHERE id=?", (cashier_id,)
        ).fetchone()["is_active"]
        admin_row = db.execute(
            "SELECT is_active FROM users WHERE id=?", (admin._user_id,)
        ).fetchone()["is_active"]
        owner_row = db.execute(
            "SELECT is_active FROM users WHERE id=?", (self.owner_id,)
        ).fetchone()["is_active"]
        db.close()
        self.assertEqual(int(active), 0)
        self.assertEqual(int(cashier_row), 0)
        self.assertEqual(int(admin_row), 1)
        self.assertEqual(int(owner_row), 1)

    def test_open_role_gaps_are_locked(self):
        db = self.ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("viewer", self.ac._hash_pw("viewer-pass"), "viewer", "Viewer"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("desk-manager", self.ac._hash_pw("manager-pass"), "manager", "Desk Manager"),
        )
        db.commit()
        db.close()
        viewer = self._login("viewer", "viewer-pass")
        cashier = self._login("cashier", "cashier-pass")
        admin = self._login("shop-admin", "admin-pass")
        manager = self._login("desk-manager", "manager-pass")
        owner = self._login("owner", "owner-pass")

        sale = self.client.post(
            "/api/sales",
            headers=viewer,
            json={"items": [{"product_id": self.product_id, "quantity": 1, "price": 20}], "total": 20, "amount_paid": 20},
        )
        self.assertEqual(sale.status_code, 403, sale.get_json())

        products = self.client.get("/api/products", headers=cashier)
        self.assertEqual(products.status_code, 200, products.get_json())
        self.assertNotIn("cost_price", products.get_json()[0])
        admin_products = self.client.get("/api/products", headers=admin)
        self.assertIn("cost_price", admin_products.get_json()[0])

        self.assertEqual(self.client.get("/api/reports/data", headers=cashier).status_code, 403)
        self.assertEqual(self.client.get("/api/live", headers=cashier).status_code, 403)
        self.assertEqual(self.client.get("/api/notifications", headers=cashier).status_code, 403)
        self.assertEqual(self.client.get("/api/health/detail", headers=cashier).status_code, 403)
        self.assertEqual(self.client.get("/api/backup/status", headers=manager).status_code, 403)
        self.assertEqual(self.client.get("/api/branches", headers=manager).status_code, 403)
        self.assertEqual(self.client.get("/api/ai/insights", headers=cashier).status_code, 403)
        self.assertNotEqual(self.client.get("/api/ai/insights", headers=manager).status_code, 403)
        self.assertEqual(self.client.get("/api/license/status", headers=admin).status_code, 403)
        self.assertNotEqual(self.client.get("/api/license/status", headers=owner).status_code, 403)
        self.assertEqual(
            self.client.put("/api/settings", headers=manager, json={"shop_name": "Nope"}).status_code,
            403,
        )
        journal = self.client.post("/api/finance/journals", headers=cashier, json={"lines": []})
        self.assertEqual(journal.status_code, 403, journal.get_json())
        debt = self.client.get("/api/debt/invoices", headers=cashier)
        self.assertEqual(debt.status_code, 200, debt.get_json())
        self.assertEqual(debt.get_json(), [])
        admin_backup = self.client.get("/api/backup/status", headers=admin)
        self.assertNotEqual(admin_backup.status_code, 403, admin_backup.get_json())

    def test_unknown_role_is_denied(self):
        from desktop.utils.security import has_permission
        self.assertFalse(has_permission({}, 'sales.create'))
        self.assertFalse(has_permission({'role': 'member'}, 'sales.create'))
        self.assertFalse(has_permission({'role': 'cashier'}, 'sales.void'))

    def test_cashier_cannot_see_other_sales_notes_or_sync(self):
        from datetime import date
        db = self.ac._db()
        cashier_id = db.execute("SELECT id FROM users WHERE username='cashier'").fetchone()['id']
        owner_id = db.execute("SELECT id FROM users WHERE username='owner'").fetchone()['id']
        today = date.today().isoformat()
        db.execute(
            "INSERT INTO sales (receipt_number, cashier_id, cashier_name, total, sale_date, status) "
            "VALUES ('RCP-OWN', ?, 'cashier', 10, ?, 'completed')",
            (cashier_id, today),
        )
        db.execute(
            "INSERT INTO sales (receipt_number, cashier_id, cashier_name, total, sale_date, status) "
            "VALUES ('RCP-OTHER', ?, 'owner', 99, ?, 'completed')",
            (owner_id, today),
        )
        db.execute(
            "INSERT INTO notes (user_id, title, content) VALUES (?, 'Owner note', 'private')",
            (owner_id,),
        )
        note_id = db.execute("SELECT id FROM notes WHERE title='Owner note'").fetchone()['id']
        other_sale = db.execute("SELECT id FROM sales WHERE receipt_number='RCP-OTHER'").fetchone()['id']
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("viewer", self.ac._hash_pw("viewer-pass"), "viewer", "Viewer"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("lead", self.ac._hash_pw("lead-pass"), "manager", "Lead"),
        )
        db.execute(
            "INSERT INTO sync_queue (action_type, payload, status) VALUES ('sale', '{}', 'pending')"
        )
        db.commit()
        db.close()
        cashier = self._login("cashier", "cashier-pass")
        sales = self.client.get(f"/api/sales?start={today}&end={today}", headers=cashier)
        self.assertEqual(sales.status_code, 200, sales.get_json())
        numbers = {row['receipt_number'] for row in sales.get_json()}
        self.assertEqual(numbers, {'RCP-OWN'})
        hidden = self.client.get(f"/api/sales/{other_sale}", headers=cashier)
        self.assertEqual(hidden.status_code, 403)
        notes = self.client.get("/api/notes", headers=cashier)
        self.assertEqual(notes.status_code, 200, notes.get_json())
        self.assertEqual(notes.get_json(), [])
        stolen = self.client.delete(f"/api/notes/{note_id}", headers=cashier)
        self.assertEqual(stolen.status_code, 403)
        queued = self.client.post("/api/sync/mark-sent", headers=cashier, json={"ids": [1]})
        self.assertEqual(queued.status_code, 403)
        viewer = self._login("viewer", "viewer-pass")
        write = self.client.post("/api/notes", headers=viewer, json={"title": "no", "content": "no"})
        self.assertEqual(write.status_code, 403)
        lead = self._login("lead", "lead-pass")
        audit = self.client.get("/api/audit", headers=lead)
        self.assertEqual(audit.status_code, 403)
        db = self.ac._db()
        still = db.execute("SELECT status FROM sync_queue").fetchone()['status']
        kept = db.execute("SELECT id FROM notes WHERE id=?", (note_id,)).fetchone()
        db.close()
        self.assertEqual(still, 'pending')
        self.assertIsNotNone(kept)

    def test_last_superadmin_cannot_be_removed(self):
        headers = self._login("owner", "owner-pass")
        changed = self.client.put(
            f"/api/users/{self.owner_id}",
            headers=headers,
            json={"is_active": 0},
        )
        self.assertEqual(changed.status_code, 400, changed.get_json())
        still = self.client.post("/api/auth/login", json={"username": "owner", "password": "owner-pass"})
        self.assertEqual(still.status_code, 200)

    def test_shop_https_origin_is_allowed_and_another_site_is_not(self):
        same = self.client.post(
            "/api/auth/login",
            json={"username": "cashier", "password": "wrong-password"},
            headers={"Origin": "https://edmus.mugobyte.com"},
            base_url="http://edmus.mugobyte.com",
        )
        self.assertEqual(same.status_code, 401, same.get_json())
        other = self.client.post(
            "/api/auth/login",
            json={"username": "cashier", "password": "wrong-password"},
            headers={"Origin": "https://evil.example"},
            base_url="http://edmus.mugobyte.com",
        )
        self.assertEqual(other.status_code, 403, other.get_json())

    def test_disabled_account_cannot_log_in(self):
        db = self.ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,0)",
            ("closed", self.ac._hash_pw("closed-pass"), "cashier", "Closed"),
        )
        db.commit()
        db.close()
        blocked = self.client.post("/api/auth/login", json={"username": "closed", "password": "closed-pass"})
        self.assertIn(blocked.status_code, (401, 403))


class CashierInventoryValueTests(unittest.TestCase):
    def test_a_cashier_is_not_given_the_inventory_value(self):
        from web.web_routes import _user_can
        cashier = {
            "role": "cashier",
            "tab_permissions": ["dashboard", "sales", "inventory"],
        }
        self.assertFalse(_user_can("inventory_value", cashier))
        self.assertFalse(_user_can("inventory_value", {
            "role": "viewer",
            "tab_permissions": ["inventory", "reports"],
        }))
        self.assertTrue(_user_can("inventory_value", {"role": "admin"}))
        self.assertTrue(_user_can("inventory_value", {
            "role": "manager",
            "tab_permissions": ["inventory"],
        }))


if __name__ == "__main__":
    unittest.main()
