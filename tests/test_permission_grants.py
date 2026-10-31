"""Individual grants and denials. Role defaults stay the baseline."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from desktop.utils.security import (
    clean_permission_change,
    effective_actions,
    has_permission,
    redact_cost_fields,
)


class PermissionGrantTests(unittest.TestCase):
    def test_unknown_action_is_denied(self):
        self.assertFalse(has_permission({"role": "superadmin"}, "not.a.real.action"))

    def test_grant_adds_only_that_action(self):
        user = {"role": "cashier", "permission_grants": ["reports.view_all"], "permission_denials": []}
        self.assertTrue(has_permission(user, "reports.view_all"))
        self.assertFalse(has_permission(user, "inventory.adjust_stock"))
        self.assertFalse(has_permission(user, "sales.void"))
        self.assertTrue(has_permission(user, "sales.create"))

    def test_denial_removes_a_role_default(self):
        user = {"role": "cashier", "permission_grants": [], "permission_denials": ["inventory.receive"]}
        self.assertFalse(has_permission(user, "inventory.receive"))
        self.assertTrue(has_permission(user, "sales.create"))

    def test_denial_beats_grant(self):
        user = {
            "role": "cashier",
            "permission_grants": ["reports.view_all"],
            "permission_denials": ["reports.view_all"],
        }
        self.assertFalse(has_permission(user, "reports.view_all"))

    def test_superadmin_denial_is_ignored(self):
        user = {"role": "superadmin", "permission_denials": ["sales.void", "license.manage"]}
        self.assertTrue(has_permission(user, "sales.void"))
        self.assertTrue(has_permission(user, "license.manage"))

    def test_locked_action_cannot_be_granted(self):
        user = {"role": "cashier", "permission_grants": ["inventory.adjust_stock", "users.delete"]}
        self.assertFalse(has_permission(user, "inventory.adjust_stock"))
        self.assertFalse(has_permission(user, "users.delete"))

    def test_admin_cannot_grant_a_locked_action(self):
        cleaned = clean_permission_change(
            {"role": "admin"},
            "cashier",
            ["reports.view_all", "inventory.adjust_stock", "users.delete"],
            ["inventory.receive"],
        )
        self.assertEqual(cleaned["permission_grants"], ["reports.view_all"])
        self.assertEqual(cleaned["permission_denials"], ["inventory.receive"])

    def test_admin_cannot_grant_a_permission_they_lack(self):
        cleaned = clean_permission_change(
            {"role": "admin"},
            "cashier",
            ["sales.edit"],
            [],
        )
        self.assertEqual(cleaned["permission_grants"], [])

    def test_supplier_manage_grant_does_not_add_unrelated_actions(self):
        user = {"role": "cashier", "permission_grants": ["supplier.manage"]}
        actions = effective_actions(user)
        self.assertIn("supplier.manage", actions)
        self.assertNotIn("sales.void", actions)
        self.assertNotIn("users.edit", actions)


class PermissionSaveTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "grants.db")
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
        db.commit()
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()

    def test_saved_grant_is_read_back_by_id(self):
        api = self.ac.APIClient()
        api._user_id = 2
        api._role = "admin"
        saved = api.update_user(3, {"permission_grants": ["reports.view_all"], "permission_denials": ["inventory.receive"]})
        self.assertTrue(saved.get("success"), saved)
        self.assertTrue(has_permission({"id": 3}, "reports.view_all"))
        self.assertFalse(has_permission({"id": 3}, "inventory.receive"))
        self.assertFalse(has_permission({"id": 3}, "sales.void"))

    def test_user_cannot_edit_own_grants(self):
        api = self.ac.APIClient()
        api._user_id = 2
        api._role = "admin"
        saved = api.update_user(2, {"permission_grants": ["sales.void"]})
        self.assertEqual(saved.get("status"), 400)

    def test_inactive_account_fails_closed(self):
        db = self.ac._db()
        db.execute("UPDATE users SET is_active=0 WHERE id=3")
        db.commit()
        db.close()
        self.assertFalse(has_permission({"id": 3}, "sales.create"))

    def test_cost_history_is_removed_but_the_invoice_total_stays(self):
        payload = {
            "grand_total": 35,
            "lines": [{"quantity": 1, "unit_cost": 35, "line_total": 35, "cost_price": 35}],
        }
        redact_cost_fields(payload)
        self.assertEqual(payload["grand_total"], 35)
        self.assertNotIn("unit_cost", payload["lines"][0])
        self.assertNotIn("line_total", payload["lines"][0])
        self.assertNotIn("cost_price", payload["lines"][0])
        self.assertEqual(payload["lines"][0]["quantity"], 1)

    def test_user_cannot_change_own_role(self):
        api = self.ac.APIClient()
        api._user_id = 2
        api._role = "admin"
        saved = api.update_user(2, {"role": "manager"})
        self.assertEqual(saved.get("status"), 400)
        db = self.ac._db()
        role = db.execute("SELECT role FROM users WHERE id=2").fetchone()["role"]
        db.close()
        self.assertEqual(role, "admin")

    def test_admin_cannot_edit_another_admin(self):
        db = self.ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("other-admin", self.ac._hash_pw("admin-pass"), "admin", "Other Admin"),
        )
        db.commit()
        other_id = db.execute("SELECT id FROM users WHERE username='other-admin'").fetchone()["id"]
        db.close()
        api = self.ac.APIClient()
        api._user_id = 2
        api._role = "admin"
        saved = api.update_user(other_id, {"permission_grants": ["reports.view_all"]})
        self.assertEqual(saved.get("status"), 403)

    def test_business_day_grant_does_not_add_a_void(self):
        db = self.ac._db()
        db.execute("UPDATE users SET permission_grants=? WHERE id=3", (json.dumps(["sales.business_day"]),))
        db.commit()
        db.close()
        api = self.ac.APIClient()
        api._role = "cashier"
        api._user_id = 3
        day, backdated, _created = api._resolve_sale_date({"sale_date": "2020-01-02"})
        self.assertEqual(day, "2020-01-02")
        self.assertTrue(backdated)
        self.assertFalse(has_permission({"id": 3}, "sales.void"))

    def test_grant_reaches_supplier_backdate_without_other_admin_rights(self):
        db = self.ac._db()
        db.execute("UPDATE users SET permission_grants=? WHERE id=3", (json.dumps(["supplier.manage"]),))
        db.commit()
        db.close()
        from desktop.utils.supplier_payables import _admin
        api = self.ac.APIClient()
        api._role = "cashier"
        api._user_id = 3
        self.assertIsNone(_admin(api))
        self.assertFalse(has_permission({"id": 3}, "users.delete"))
        self.assertFalse(has_permission({"id": 3}, "inventory.adjust_stock"))


if __name__ == "__main__":
    unittest.main()
