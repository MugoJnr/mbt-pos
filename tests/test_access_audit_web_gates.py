"""Five-role HTTP gates for the defects found by the live access audit.

Covers the notes IDOR, viewer web writes, backup run/status coherence, the
inventory export cost leak, navigation modules, the duplicate-username
conflict and the anonymous cloud-config payload.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from roles import default_tab_permissions  # noqa: E402

ROLES = ('cashier', 'viewer', 'manager', 'admin', 'superadmin')


class WebAccessAuditGates(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'audit.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path',
                  return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()

        import desktop.utils.api_client as ac
        import backend.app as backend

        ac._SCHEMA_READY = False
        self.ac = ac
        self.backend = backend
        self._old_backend_path = backend.DB_PATH
        backend.DB_PATH = self._db_path

        db = ac._db()
        self.user_id = {}
        for role in ROLES:
            db.execute(
                "INSERT INTO users "
                "(username,password_hash,full_name,role,is_active,tab_permissions) "
                "VALUES (?,?,?,?,1,?)",
                (f'{role}_gate', 'x:y', f'{role.title()} Gate', role,
                 json.dumps(default_tab_permissions(role))),
            )
            self.user_id[role] = int(
                db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute(
            "INSERT INTO products (name,sku,price,cost_price,stock,min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ('Audit Widget', 'AUD-1', 100, 40, 10, 2),
        )
        # One note per role so cross-owner access can be proven.
        self.note_id = {}
        for role in ROLES:
            db.execute(
                "INSERT INTO notes (user_id,title,content,pinned) VALUES (?,?,?,0)",
                (self.user_id[role], f'{role} note', 'body'),
            )
            self.note_id[role] = int(
                db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.commit()
        db.close()

        self.client = backend.app.test_client()
        self.headers = {role: self._auth(role) for role in ROLES}

    def tearDown(self):
        self.backend.DB_PATH = self._old_backend_path
        for item in self._patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self._tmpdir.cleanup()

    def _auth(self, role: str) -> dict:
        token = self.backend.jwt.encode({
            'user_id': self.user_id[role],
            'username': f'{role}_gate',
            'role': role,
            'iat': int(time.time()),
            'exp': int(time.time()) + 600,
        }, self.backend.SECRET_KEY, algorithm='HS256')
        return {'Authorization': f'Bearer {token}'}

    def _note_titles(self, role: str):
        response = self.client.get('/api/notes', headers=self.headers[role])
        self.assertEqual(response.status_code, 200, response.get_json())
        return {row['title'] for row in response.get_json()}

    # ── 1. notes IDOR ────────────────────────────────────────────────────────

    def test_note_listing_is_scoped_to_the_actor_permission(self):
        # notes.own without notes.view_all sees only its own row.
        self.assertEqual(self._note_titles('cashier'), {'cashier note'})
        for role in ('viewer', 'manager', 'admin', 'superadmin'):
            self.assertEqual(
                len(self._note_titles(role)), len(ROLES),
                f'{role} should see every note',
            )

    def test_viewer_is_read_only_on_notes(self):
        headers = self.headers['viewer']
        self.assertEqual(self.client.post(
            '/api/notes', json={'title': 'nope'}, headers=headers,
        ).status_code, 403)
        self.assertEqual(self.client.put(
            f"/api/notes/{self.note_id['viewer']}",
            json={'title': 'nope'}, headers=headers,
        ).status_code, 403)
        self.assertEqual(self.client.delete(
            f"/api/notes/{self.note_id['viewer']}", headers=headers,
        ).status_code, 403)
        self._assert_note_count(len(ROLES))

    def test_cross_owner_note_mutation_is_refused_for_non_admins(self):
        for role in ('cashier', 'manager'):
            target = self.note_id['admin']
            update = self.client.put(
                f'/api/notes/{target}',
                json={'title': 'hijacked'}, headers=self.headers[role])
            self.assertEqual(update.status_code, 403, update.get_json())
            delete = self.client.delete(
                f'/api/notes/{target}', headers=self.headers[role])
            self.assertEqual(delete.status_code, 403, delete.get_json())
        db = self.ac._db()
        title = db.execute(
            "SELECT title FROM notes WHERE id=?",
            (self.note_id['admin'],),
        ).fetchone()['title']
        db.close()
        self.assertEqual(title, 'admin note')
        self._assert_note_count(len(ROLES))

    def test_owners_and_shop_admins_may_mutate_within_policy(self):
        own = self.client.put(
            f"/api/notes/{self.note_id['cashier']}",
            json={'title': 'mine', 'content': 'ok'},
            headers=self.headers['cashier'])
        self.assertEqual(own.status_code, 200, own.get_json())
        for role in ('admin', 'superadmin'):
            response = self.client.put(
                f"/api/notes/{self.note_id['manager']}",
                json={'title': f'edited by {role}', 'content': 'ok'},
                headers=self.headers[role])
            self.assertEqual(response.status_code, 200, response.get_json())
        created = self.client.post(
            '/api/notes', json={'title': 'new'},
            headers=self.headers['manager'])
        self.assertEqual(created.status_code, 200, created.get_json())
        self.assertEqual(self.client.delete(
            f"/api/notes/{created.get_json()['id']}",
            headers=self.headers['manager'],
        ).status_code, 200)

    def test_missing_note_is_not_found_rather_than_silent_success(self):
        response = self.client.delete(
            '/api/notes/999999', headers=self.headers['superadmin'])
        self.assertEqual(response.status_code, 404, response.get_json())

    def _assert_note_count(self, expected: int):
        db = self.ac._db()
        try:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM notes").fetchone()[0], expected)
        finally:
            db.close()

    # ── 2. viewer web writes ─────────────────────────────────────────────────

    def test_customer_creation_follows_debt_intent(self):
        expected = {
            'cashier': 200, 'viewer': 403, 'manager': 200,
            'admin': 200, 'superadmin': 200,
        }
        for role, code in expected.items():
            response = self.client.post(
                '/api/customers',
                json={'name': f'Customer {role}', 'phone': f'07{role}'},
                headers=self.headers[role])
            self.assertEqual(response.status_code, code,
                             f'{role}: {response.get_json()}')

    def test_customer_edit_requires_customer_manage(self):
        seed = self.client.post(
            '/api/customers', json={'name': 'Editable'},
            headers=self.headers['manager'])
        cid = seed.get_json()['customer_id']
        expected = {
            'cashier': 403, 'viewer': 403, 'manager': 200,
            'admin': 200, 'superadmin': 200,
        }
        for role, code in expected.items():
            response = self.client.put(
                f'/api/customers/{cid}', json={'name': f'By {role}'},
                headers=self.headers[role])
            self.assertEqual(response.status_code, code,
                             f'{role}: {response.get_json()}')

    def test_read_only_viewer_cannot_change_shared_notification_state(self):
        self.client.get('/api/notifications', headers=self.headers['admin'])
        expected = {
            'cashier': 200, 'viewer': 403, 'manager': 200,
            'admin': 200, 'superadmin': 200,
        }
        for role, code in expected.items():
            response = self.client.post(
                '/api/notifications/read-all', headers=self.headers[role])
            self.assertEqual(response.status_code, code,
                             f'{role}: {response.get_json()}')
        single = self.client.post(
            '/api/notifications/1/read', headers=self.headers['viewer'])
        self.assertEqual(single.status_code, 403, single.get_json())

    # ── 6. backup run/status coherence ───────────────────────────────────────

    def test_backup_run_and_status_share_one_gate(self):
        expected = {
            'cashier': 403, 'viewer': 403, 'manager': 200,
            'admin': 200, 'superadmin': 200,
        }
        for role, code in expected.items():
            status = self.client.get(
                '/api/backup/status', headers=self.headers[role])
            self.assertEqual(status.status_code, code,
                             f'{role} status: {status.get_json()}')
        for role in ('cashier', 'viewer'):
            run = self.client.post(
                '/api/backup/run', json={'reason': 'test'},
                headers=self.headers[role])
            self.assertEqual(run.status_code, 403, run.get_json())

    # ── 7. inventory export cost exposure ────────────────────────────────────

    def test_inventory_export_requires_valuation_access(self):
        expected = {
            'cashier': 403, 'viewer': 200, 'manager': 200,
            'admin': 200, 'superadmin': 200,
        }
        for role, code in expected.items():
            response = self.client.get(
                '/api/reports/export?inventory=1&format=csv',
                headers=self.headers[role])
            self.assertEqual(response.status_code, code,
                             f'{role}: {response.status_code}')
        allowed = self.client.get(
            '/api/reports/export?inventory=1&format=csv',
            headers=self.headers['manager'])
        self.assertIn(b'Cost', allowed.data)

    def test_cashier_keeps_own_sales_export(self):
        response = self.client.get(
            '/api/reports/export?format=csv&start=2000-01-01&end=2999-12-31',
            headers=self.headers['cashier'])
        self.assertEqual(response.status_code, 200)

    # ── 5. navigation modules ────────────────────────────────────────────────

    def test_nav_modules_hide_admin_surfaces_from_low_roles(self):
        def modules(role):
            response = self.client.get(
                '/api/nav/modules', headers=self.headers[role])
            self.assertEqual(response.status_code, 200, response.get_json())
            return set(response.get_json()['modules'])

        cashier = modules('cashier')
        self.assertEqual(cashier, {'dashboard', 'sales', 'inventory'})

        viewer = modules('viewer')
        self.assertNotIn('users', viewer)
        self.assertNotIn('settings', viewer)
        self.assertNotIn('backup', viewer)
        self.assertNotIn('audit', viewer)
        self.assertIn('reports', viewer)

        manager = modules('manager')
        self.assertIn('users', manager)
        self.assertIn('backup', manager)
        self.assertNotIn('audit', manager)
        self.assertNotIn('security', manager)
        self.assertNotIn('license', manager)

        admin = modules('admin')
        self.assertIn('audit', admin)
        self.assertIn('diagnostics', admin)
        self.assertNotIn('security', admin)
        self.assertNotIn('license', admin)

        superadmin = modules('superadmin')
        self.assertTrue({'security', 'license'} <= superadmin)

    def test_live_monitor_is_reporting_data(self):
        expected = {
            'cashier': 403, 'viewer': 200, 'manager': 200,
            'admin': 200, 'superadmin': 200,
        }
        for role, code in expected.items():
            response = self.client.get('/api/live', headers=self.headers[role])
            self.assertEqual(response.status_code, code,
                             f'{role}: {response.status_code}')

    # ── 8. duplicate username conflict ───────────────────────────────────────

    def test_duplicate_username_is_a_conflict_not_an_auth_failure(self):
        headers = self.headers['superadmin']
        payload = {
            'username': 'cashier_gate',
            'password': 'Sup3r!secret',
            'role': 'cashier',
            'full_name': 'Clash',
        }
        response = self.client.post(
            '/api/users', json=payload, headers=headers)
        self.assertEqual(response.status_code, 409, response.get_json())
        body = response.get_json() or {}
        self.assertEqual(body.get('code'), 'username_taken')
        self.assertIn('cashier_gate', body.get('error', ''))
        # The session must survive the conflict.
        after = self.client.get('/api/nav/modules', headers=headers)
        self.assertEqual(after.status_code, 200, after.get_json())
        db = self.ac._db()
        try:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM users WHERE username='cashier_gate'"
            ).fetchone()[0], 1)
        finally:
            db.close()

    # ── 10. anonymous cloud config ───────────────────────────────────────────

    def test_cloud_config_hides_project_identifiers_from_guests(self):
        import backend.cloud.platform_service as ps
        cfg = {
            'supabase_url': 'https://example.supabase.co',
            'anon_key': 'anon-value',
            'project_ref': 'exampleref',
            'bucket': 'mbt-backups',
            'enabled': True,
        }
        with patch.object(ps, 'load_cloud_config', return_value=cfg), \
                patch.object(ps, 'is_cloud_configured', return_value=True):
            guest = self.client.get('/api/cloud/config')
            self.assertEqual(guest.status_code, 200)
            body = guest.get_json() or {}
            self.assertEqual(set(body), {'configured', 'enabled'})
            self.assertTrue(body['configured'])
            serialized = guest.get_data(as_text=True)
            for secret in ('anon-value', 'exampleref', 'example.supabase.co'):
                self.assertNotIn(secret, serialized)

            authed = self.client.get(
                '/api/cloud/config', headers=self.headers['admin'])
            abody = authed.get_json() or {}
            self.assertEqual(abody.get('project_ref'), 'exampleref')
            self.assertNotIn('anon_key', abody)


if __name__ == '__main__':
    unittest.main()
