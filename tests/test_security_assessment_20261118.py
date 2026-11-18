"""Authorised attacks against disposable shops and licence files.

No live shop database, no production seat, and no secret values in assertions.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _marker_db(path: str, marker: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute('CREATE TABLE shop (name TEXT)')
        conn.execute('INSERT INTO shop (name) VALUES (?)', (marker,))
        conn.commit()
    finally:
        conn.close()


class RestoreSafetyTests(unittest.TestCase):
    def test_damaged_backup_does_not_replace_the_shop(self):
        from backend.cloud_backup.restore_manager import RestoreError, install_verified_snapshot

        folder = tempfile.mkdtemp()
        live = os.path.join(folder, 'mbt_pos.db')
        bad = os.path.join(folder, 'bad.db')
        _marker_db(live, 'keep-me')
        with open(bad, 'wb') as handle:
            handle.write(b'not a database' * 80)
        with self.assertRaises(RestoreError):
            install_verified_snapshot(live, bad)
        conn = sqlite3.connect(live)
        try:
            name = conn.execute('SELECT name FROM shop').fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(name, 'keep-me')
        self.assertFalse(os.path.exists(live + '.incoming'))

    def test_good_snapshot_replaces_and_keeps_the_previous_file(self):
        from backend.cloud_backup.restore_manager import install_verified_snapshot

        folder = tempfile.mkdtemp()
        live = os.path.join(folder, 'mbt_pos.db')
        snap = os.path.join(folder, 'snap.db')
        _marker_db(live, 'old-shop')
        _marker_db(snap, 'restored-shop')
        pre = install_verified_snapshot(live, snap)
        conn = sqlite3.connect(live)
        try:
            name = conn.execute('SELECT name FROM shop').fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(name, 'restored-shop')
        old = sqlite3.connect(pre)
        try:
            previous = old.execute('SELECT name FROM shop').fetchone()[0]
        finally:
            old.close()
        self.assertEqual(previous, 'old-shop')


class ShopAttackTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'shop.db')
        os.environ['MBT_DATA_ROOT'] = self._tmpdir.name
        os.environ['APPDATA'] = self._tmpdir.name
        os.environ['LOCALAPPDATA'] = self._tmpdir.name
        os.environ['PROGRAMDATA'] = self._tmpdir.name
        os.environ['MBT_TEST_INSTANCE'] = '1'
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ('owner', ac._hash_pw('owner-pass-2026'), 'superadmin', 'Owner'),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ('cashier', ac._hash_pw('cashier-pass-2026'), 'cashier', 'Cashier'),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, is_active) "
            "VALUES ('Attack Soap', 'ATK-SOAP', 80, 40, 6, 1)"
        )
        db.commit()
        self.product_id = db.execute("SELECT id FROM products WHERE sku='ATK-SOAP'").fetchone()['id']
        self.cashier_id = db.execute("SELECT id FROM users WHERE username='cashier'").fetchone()['id']
        self.owner_id = db.execute("SELECT id FROM users WHERE username='owner'").fetchone()['id']
        db.close()
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        appmod._login_attempts.clear()
        self.appmod = appmod
        self.client = appmod.app.test_client()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self._tmpdir.cleanup()

    def _login(self, username, password):
        response = self.client.post('/api/auth/login', json={'username': username, 'password': password})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        return body['token'], {'Authorization': f"Bearer {body['token']}"}

    def test_sql_injection_does_not_sign_in(self):
        response = self.client.post(
            '/api/auth/login',
            json={'username': "' OR 1=1 --", 'password': 'x'},
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('token', response.get_json())

    def test_repeated_bad_passwords_are_limited(self):
        last = None
        for _ in range(12):
            last = self.client.post(
                '/api/auth/login',
                json={'username': 'cashier', 'password': 'wrong-password'},
            )
        self.assertEqual(last.status_code, 429)

    def test_cashier_cannot_promote_themselves(self):
        _token, headers = self._login('cashier', 'cashier-pass-2026')
        response = self.client.put(
            f'/api/users/{self.cashier_id}',
            headers=headers,
            json={'role': 'superadmin', 'permission_grants': ['users.edit', 'reports.view_all']},
        )
        self.assertEqual(response.status_code, 403, response.get_json())
        db = self.ac._db()
        try:
            role = db.execute('SELECT role FROM users WHERE id=?', (self.cashier_id,)).fetchone()['role']
        finally:
            db.close()
        self.assertEqual(role, 'cashier')

    def test_cashier_cannot_post_a_sale_as_the_owner(self):
        _token, headers = self._login('cashier', 'cashier-pass-2026')
        response = self.client.post(
            '/api/sales',
            headers=headers,
            json={
                'items': [{
                    'product_id': self.product_id,
                    'quantity': 1,
                    'unit_price': 80,
                    'total': 80,
                }],
                'total': 80,
                'amount_paid': 80,
                'cashier_id': self.owner_id,
                'payment_method': 'cash',
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        db = self.ac._db()
        try:
            row = db.execute('SELECT cashier_id FROM sales ORDER BY id DESC LIMIT 1').fetchone()
        finally:
            db.close()
        self.assertEqual(int(row['cashier_id']), int(self.cashier_id))

    def test_logged_out_token_cannot_be_reused(self):
        token, headers = self._login('cashier', 'cashier-pass-2026')
        gone = self.client.post('/api/auth/logout', headers=headers)
        self.assertEqual(gone.status_code, 200, gone.get_json())
        again = self.client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(again.status_code, 401, again.get_json())

    def test_token_without_a_session_is_rejected(self):
        import jwt
        token = jwt.encode(
            {
                'user_id': self.cashier_id,
                'username': 'cashier',
                'role': 'superadmin',
                'exp': int(time.time()) + 3600,
            },
            self.appmod.SECRET_KEY,
            algorithm='HS256',
        )
        response = self.client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(response.status_code, 401, response.get_json())

    def test_forged_role_claim_does_not_change_the_account(self):
        import jwt
        from desktop.utils.account_sessions import open_web_session

        db = self.ac._db()
        try:
            user = dict(db.execute('SELECT * FROM users WHERE id=?', (self.cashier_id,)).fetchone())
            sid = open_web_session(db, user, '127.0.0.1')
            db.commit()
        finally:
            db.close()
        token = jwt.encode(
            {
                'user_id': self.cashier_id,
                'username': 'cashier',
                'role': 'superadmin',
                'sid': sid,
                'exp': int(time.time()) + 3600,
            },
            self.appmod.SECRET_KEY,
            algorithm='HS256',
        )
        response = self.client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['role'], 'cashier')
        blocked = self.client.get(
            '/api/license/status',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(blocked.status_code, 403)

    def test_public_cloud_config_has_no_service_key(self):
        from backend.cloud.platform_service import cloud_public_config
        payload = cloud_public_config()
        self.assertNotIn('service_key', payload)
        self.assertNotIn('service_role', payload)


class LicenceTamperTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'license.db')
        self._device = 'a' * 40
        self._other = 'b' * 40
        import licensing.license_engine as le
        self.le = le
        self.le._MASTER_SECRET_CACHE = None
        self.le._LEGACY_SECRET_CANDIDATES = None
        self._patches = [
            patch.object(le, '_hidden_db_path', return_value=self._db_path),
            patch.object(le, 'resolve_device_id', return_value=self._device),
            patch.object(le, '_get_device_fingerprint', return_value=self._device),
            patch.object(le, '_get_legacy_wmic_fingerprint', return_value=''),
            patch.object(le, '_cheap_device_id_candidates', return_value=[self._device]),
            patch.object(le, '_sync_cloud_identity_fingerprint'),
            patch('mbt_paths.get_project_root', return_value=self._tmpdir.name),
        ]
        for item in self._patches:
            item.start()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self.le._MASTER_SECRET_CACHE = None
        self._tmpdir.cleanup()

    def _plant(self, device: str, **overrides):
        now = int(time.time())
        lic = {
            'device_id': device,
            'plan': 'monthly',
            'issued_at': now - 86400,
            'expires_at': now + 30 * 86400,
            'duration_days': 30,
            'activated_at': now - 86400,
            'issued_by': 'unit-test',
            'source': 'mbt_cloud',
            'version': 2,
        }
        lic.update(overrides)
        store = self.le.LicenseStore(device)
        store.set('license_token', self.le.encrypt_payload(lic, device))
        store.set('highest_ts_seen', now)
        store.set('last_checked_ts', now)
        store.set('tampered', False)
        store.set('revoked', False)

    def test_editing_the_encrypted_record_does_not_extend_the_licence(self):
        self._plant(self._device)
        store = self.le.LicenseStore(self._device)
        token = str(store.get('license_token') or '')
        store.set('license_token', token[:-8] + 'xxxxxxxx')
        engine = self.le.LicenseEngine()
        self.assertFalse(engine.is_valid)
        self.assertEqual(engine.state, self.le.STATE_TAMPERED)
        reason = self.le.protected_write_block_reason(engine)
        self.assertTrue(reason)
        self.assertIn('unchanged', reason.lower())

    def test_a_copied_licence_does_not_validate_on_another_device(self):
        self._plant(self._other)
        engine = self.le.LicenseEngine()
        self.assertFalse(engine.is_valid)
        self.assertEqual(engine.state, self.le.STATE_TAMPERED)
        reason = self.le.protected_write_block_reason(engine)
        self.assertIn('computer', reason.lower())

    def test_revoked_flag_blocks_even_when_the_token_is_still_present(self):
        now = int(time.time())
        self._plant(self._device, expires_at=now + 10 * 86400)
        store = self.le.LicenseStore(self._device)
        store.set('revoked', True)
        store.set('license_token', '')
        engine = self.le.LicenseEngine()
        self.assertFalse(engine.is_valid)
        reason = self.le.protected_write_block_reason(engine)
        self.assertIn('revoked', reason.lower())


if __name__ == '__main__':
    unittest.main()
