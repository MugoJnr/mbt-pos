"""Desktop local-API role gates flagged by the live access audit.

`APIClient` talks straight to SQLite, so the gate has to live in the client
itself — hiding a tab is not a refusal. These tests prove the backend refuses.
"""
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

from roles import default_tab_permissions  # noqa: E402

ROLES = ('cashier', 'viewer', 'manager', 'admin', 'superadmin')


class DesktopApiRoleGates(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'desktop.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path',
                  return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()

        import desktop.utils.api_client as ac

        ac._SCHEMA_READY = False
        self.ac = ac

        db = ac._db()
        self.user_id = {}
        for role in ROLES:
            db.execute(
                "INSERT INTO users "
                "(username,password_hash,full_name,role,is_active,tab_permissions) "
                "VALUES (?,?,?,?,1,?)",
                (f'{role}_local', 'x:y', f'{role.title()} Local', role,
                 json.dumps(default_tab_permissions(role))),
            )
            self.user_id[role] = int(
                db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute(
            "INSERT INTO audit_log (user_id,username,action,module,details) "
            "VALUES (?,?,?,?,?)",
            (self.user_id['admin'], 'admin_local', 'SEED', 'test', 'seed row'),
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key,value) VALUES (?,?)",
            ('shop_name', 'Original Shop'),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self._tmpdir.cleanup()

    def _api(self, role: str):
        api = self.ac.APIClient()
        api._user_id = self.user_id[role]
        api._username = f'{role}_local'
        api._role = role
        return api

    def _setting(self, key: str):
        db = self.ac._db()
        try:
            row = db.execute(
                "SELECT value FROM system_settings WHERE key=?", (key,)
            ).fetchone()
            return row['value'] if row else None
        finally:
            db.close()

    # ── settings.edit ────────────────────────────────────────────────────────

    def test_shop_settings_writes_require_settings_edit(self):
        for role in ('cashier', 'viewer', 'manager'):
            result = self._api(role).update_settings({'shop_name': f'By {role}'})
            self.assertIn('error', result, role)
            self.assertIn('shop_name', result['error'])
        self.assertEqual(self._setting('shop_name'), 'Original Shop')
        for role in ('admin', 'superadmin'):
            result = self._api(role).update_settings({'shop_name': f'By {role}'})
            self.assertTrue(result.get('success'), result)
        self.assertEqual(self._setting('shop_name'), 'By superadmin')

    def test_denied_settings_write_is_audited(self):
        self._api('cashier').update_settings({'shop_name': 'Nope'})
        db = self.ac._db()
        try:
            actions = {
                row['action'] for row in db.execute(
                    "SELECT action FROM audit_log").fetchall()
            }
        finally:
            db.close()
        self.assertIn('UPDATE_SETTINGS_DENIED', actions)

    def test_per_device_ui_preferences_stay_writable_for_every_role(self):
        for role in ROLES:
            result = self._api(role).update_settings({'theme': 'light'})
            self.assertTrue(result.get('success'), f'{role}: {result}')
        self.assertEqual(self._setting('theme'), 'light')

    def test_report_schedule_follows_reports_export(self):
        denied = self._api('cashier').update_settings(
            {'auto_report_daily': '1'})
        self.assertIn('error', denied)
        allowed = self._api('manager').update_settings(
            {'auto_report_daily': '1'})
        self.assertTrue(allowed.get('success'), allowed)
        self.assertEqual(self._setting('auto_report_daily'), '1')

    def test_unattended_system_context_may_still_persist_markers(self):
        api = self.ac.APIClient()  # no signed-in actor (setup wizard/scheduler)
        self.assertTrue(
            api.update_settings({'last_db_backup_at': '2026-01-01'}).get('success'))

    # ── users.view / audit.view ──────────────────────────────────────────────

    def test_user_listing_requires_users_view(self):
        for role in ('cashier', 'viewer'):
            self.assertEqual(self._api(role).get_users(), [], role)
        for role in ('manager', 'admin', 'superadmin'):
            self.assertEqual(len(self._api(role).get_users()), len(ROLES), role)

    def test_audit_listing_requires_audit_view(self):
        for role in ('cashier', 'viewer', 'manager'):
            self.assertEqual(self._api(role).get_audit_log(), [], role)
        for role in ('admin', 'superadmin'):
            self.assertTrue(self._api(role).get_audit_log(), role)

    def test_denied_list_calls_are_audited(self):
        self._api('cashier').get_users()
        self._api('manager').get_audit_log()
        db = self.ac._db()
        try:
            actions = {
                row['action'] for row in db.execute(
                    "SELECT action FROM audit_log").fetchall()
            }
        finally:
            db.close()
        self.assertIn('USERS_VIEW_DENIED', actions)
        self.assertIn('AUDIT_VIEW_DENIED', actions)

    # ── 12. accurate denial messages ─────────────────────────────────────────

    def test_create_user_denial_names_the_real_reason(self):
        payload = {
            'username': 'new_cashier',
            'password': 'Sup3r!secret',
            'role': 'cashier',
        }
        for role in ('cashier', 'viewer', 'manager'):
            error = self._api(role).create_user(dict(payload))['error']
            self.assertIn('does not have permission', error, role)
            self.assertNotIn('Super Admin', error, role)

        owner_only = self._api('admin').create_user({
            'username': 'new_owner',
            'password': 'Sup3r!secret',
            'role': 'superadmin',
        })
        self.assertIn('Super Admin', owner_only['error'])

        self.assertTrue(
            self._api('admin').create_user(dict(payload)).get('success'))

    def test_update_user_denial_names_the_real_reason(self):
        target = self.user_id['cashier']
        for role in ('cashier', 'viewer', 'manager'):
            error = self._api(role).update_user(
                target, {'full_name': 'Renamed'})['error']
            self.assertIn('does not have permission', error, role)
            self.assertNotIn('Super Admin', error, role)
        self.assertTrue(
            self._api('admin').update_user(
                target, {'full_name': 'Renamed'}).get('success'))
        owner_only = self._api('admin').update_user(
            target, {'role': 'superadmin'})
        self.assertIn('Super Admin', owner_only['error'])


if __name__ == '__main__':
    unittest.main()
