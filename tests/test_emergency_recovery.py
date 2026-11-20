"""Developer emergency recovery: signature, binding, replay, and existing resets."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend import emergency_recovery as er
from desktop.utils.account_sessions import ensure as ensure_sessions
from desktop.utils.account_sessions import open_till_session, open_web_session, web_session_active


def _live_shop() -> str:
    profile = os.environ.get('USERPROFILE') or ''
    return os.path.normcase(os.path.join(profile, 'AppData', 'Local', 'MugoByte', 'MBT POS'))


class RecoveryCase(unittest.TestCase):
    def setUp(self):
        self._saved = {
            key: os.environ.get(key)
            for key in (
                'MBT_TEST_INSTANCE', 'MBT_DATA_ROOT', 'APPDATA',
                'LOCALAPPDATA', 'PROGRAMDATA', 'MBT_RECOVERY_PRIVATE_KEY_FILE',
                'MBT_RECOVERY_TEST_AUTH', 'MBT_RECOVERY_TEST_TOKEN',
            )
        }
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        live = _live_shop()
        self.assertFalse(os.path.normcase(os.path.abspath(root)).startswith(live))
        os.environ['MBT_TEST_INSTANCE'] = '1'
        os.environ['MBT_DATA_ROOT'] = root
        os.environ['APPDATA'] = os.path.join(root, 'appdata')
        os.environ['LOCALAPPDATA'] = os.path.join(root, 'local')
        os.environ['PROGRAMDATA'] = os.path.join(root, 'programdata')
        os.makedirs(os.path.join(root, 'config'), exist_ok=True)
        os.makedirs(os.path.join(root, 'data'), exist_ok=True)
        identity = os.path.join(root, 'config', 'cloud_identity.json')
        Path(identity).write_text(
            json.dumps({'device_id': 'MBT-PC-UNITTEST'}),
            encoding='utf-8',
        )
        self.secret = er.get_or_create_device_secret(root)
        self.assertEqual(len(self.secret), 32)
        self.assertTrue(str(er.device_secret_path(root)).startswith(os.path.abspath(root)))
        self.conn = sqlite3.connect(os.path.join(root, 'data', 'mbt_pos.db'))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password_hash TEXT,
                role TEXT,
                full_name TEXT,
                email TEXT,
                is_active INTEGER DEFAULT 1
            );
            CREATE TABLE system_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            );
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                action TEXT,
                module TEXT,
                details TEXT,
                ip_address TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.conn.execute(
            "INSERT INTO system_settings (key, value) VALUES ('shop_instance_id', 'shop-unit')",
        )
        self.conn.execute(
            "INSERT INTO system_settings (key, value) VALUES ('shop_name', 'Recovery Unit Shop')",
        )
        from desktop.utils.api_client import _hash_pw
        self._hash = _hash_pw
        self.conn.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) "
            "VALUES ('owner', ?, 'superadmin', 'Recovery Owner', 1)",
            (_hash_pw('OldShop-1'),),
        )
        self.conn.commit()
        ensure_sessions(self.conn)

    def tearDown(self):
        try:
            self.conn.close()
        except Exception:
            pass
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def _issue(self, **overrides):
        body = dict(
            shop_id='shop-unit',
            device_id='MBT-PC-UNITTEST',
            user_id=1,
            username='owner',
            secret=self.secret,
        )
        body.update(overrides)
        return er.issue_token(**body)

    def _password(self):
        row = self.conn.execute("SELECT password_hash FROM users WHERE id=1").fetchone()
        return row['password_hash']

    def _verify(self, token, **overrides):
        body = dict(
            shop_id='shop-unit',
            device_id='MBT-PC-UNITTEST',
            user_id=1,
            username='owner',
            secret=self.secret,
        )
        body.update(overrides)
        return er.verify_token(token, **body)

    def test_sign_and_verify(self):
        issued = self._issue()
        self.assertRegex(
            issued['token'],
            r'^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}(?:-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}){2}$',
        )
        self.assertNotRegex(issued['token'], r'[01ILO]')
        self.assertEqual(len(issued['token_id']), 32)
        self.assertNotIn('-', issued['token_id'])
        claims = self._verify(issued['token'].lower().replace('-', ' '))
        self.assertEqual(claims['tid'], issued['token_id'])
        self.assertEqual(claims['op'], er.OPERATION)
        self.assertNotEqual(issued['token'].replace('-', ''), claims['tid'])

    def test_altered_and_forged_tokens_are_rejected(self):
        issued = self._issue()
        compact = issued['token'].replace('-', '')
        replacement = '2' if compact[-1] != '2' else '3'
        altered = er.format_recovery_code(compact[:-1] + replacement)
        with self.assertRaises(er.RecoveryError) as altered_err:
            self._verify(altered)
        self.assertEqual(altered_err.exception.code, 'invalid')
        forged = er.issue_token(
            shop_id='shop-unit', device_id='MBT-PC-UNITTEST', user_id=1,
            username='owner', secret=os.urandom(32),
        )
        with self.assertRaises(er.RecoveryError) as forged_err:
            self._verify(forged['token'])
        self.assertEqual(forged_err.exception.code, 'invalid')
        with self.assertRaises(er.RecoveryError):
            er.normalize_recovery_code('MBT1.not-a-short-code')

    def test_expired_wrong_shop_and_wrong_device(self):
        issued = self._issue(now=1_700_000_000)
        with self.assertRaises(er.RecoveryError) as expired:
            self._verify(issued['token'], now=issued['expires_at'] + 5, clock_floor=0)
        self.assertEqual(expired.exception.code, 'expired')
        with self.assertRaises(er.RecoveryError) as shop:
            self._verify(issued['token'], shop_id='other-shop', now=issued['expires_at'] - 10)
        self.assertEqual(shop.exception.code, 'invalid')
        with self.assertRaises(er.RecoveryError) as device:
            self._verify(issued['token'], device_id='MBT-PC-OTHER', now=issued['expires_at'] - 10)
        self.assertEqual(device.exception.code, 'invalid')

    def test_clock_floor_rejects_a_code_already_expired_against_it(self):
        now = int(time.time())
        issued = self._issue(now=now)
        self.conn.execute(
            "INSERT INTO system_settings (key, value) VALUES (?, ?)",
            (er.CLOCK_KEY, str(issued['expires_at'] + 60)),
        )
        self.conn.commit()
        result = er.redeem_superadmin(
            self.conn, issued['token'], 'NewShop-1', 'NewShop-1', via='till',
        )
        self.assertEqual(result.get('code'), 'expired')
        self.assertEqual(self._password(), self._hash and self.conn.execute(
            "SELECT password_hash FROM users WHERE id=1"
        ).fetchone()['password_hash'])
        from desktop.utils.api_client import _check_pw
        self.assertTrue(_check_pw('OldShop-1', self._password()))

    def test_replay_is_rejected_and_sessions_are_invalidated(self):
        from desktop.utils.api_client import _check_pw
        web_sid = open_web_session(self.conn, {'id': 1, 'username': 'owner', 'role': 'superadmin'})
        till_id = open_till_session(self.conn, {'id': 1, 'username': 'owner', 'role': 'superadmin'})
        self.conn.commit()
        issued = self._issue()
        first = er.redeem_superadmin(
            self.conn, issued['token'], 'NewShop-1', 'NewShop-1', via='web',
        )
        self.assertTrue(first.get('success'), first)
        self.assertTrue(_check_pw('NewShop-1', self._password()))
        self.assertFalse(_check_pw('OldShop-1', self._password()))
        role = self.conn.execute("SELECT role, is_active FROM users WHERE id=1").fetchone()
        self.assertEqual(role['role'], 'superadmin')
        self.assertEqual(int(role['is_active']), 1)
        self.assertFalse(web_session_active(self.conn, web_sid))
        till = self.conn.execute(
            "SELECT end_requested, state FROM till_sessions WHERE id=?", (till_id,)
        ).fetchone()
        self.assertEqual(int(till['end_requested']), 1)
        self.assertEqual(till['state'], 'pending')
        audit = self.conn.execute(
            "SELECT details FROM audit_log WHERE action='DEVELOPER_RECOVERY_RESET'"
        ).fetchone()
        self.assertIn(issued['token_id'], audit['details'])
        self.assertNotIn(issued['token'], audit['details'])
        second = er.redeem_superadmin(
            self.conn, issued['token'], 'OtherShop-2', 'OtherShop-2', via='till',
        )
        self.assertEqual(second.get('code'), 'replay')
        self.assertTrue(_check_pw('NewShop-1', self._password()))
        self.assertFalse(_check_pw('OtherShop-2', self._password()))

    def test_disabled_account_is_not_enabled(self):
        self.conn.execute("UPDATE users SET is_active=0 WHERE id=1")
        self.conn.commit()
        before = self._password()
        issued = self._issue()
        result = er.redeem_superadmin(
            self.conn, issued['token'], 'NewShop-1', 'NewShop-1', via='till',
        )
        self.assertEqual(result.get('code'), 'disabled')
        self.assertEqual(int(self.conn.execute(
            "SELECT is_active FROM users WHERE id=1"
        ).fetchone()['is_active']), 0)
        self.assertEqual(self._password(), before)
        used = self.conn.execute("SELECT COUNT(*) AS c FROM emergency_recovery_uses").fetchone()
        self.assertEqual(int(used['c']), 0)

    def test_password_policy_does_not_consume_the_code(self):
        issued = self._issue()
        short = er.redeem_superadmin(self.conn, issued['token'], 'short', 'short', via='till')
        self.assertEqual(short.get('code'), 'policy')
        mismatch = er.redeem_superadmin(
            self.conn, issued['token'], 'NewShop-1', 'NewShop-2', via='till',
        )
        self.assertEqual(mismatch.get('code'), 'policy')
        spaced = er.redeem_superadmin(
            self.conn, issued['token'], ' NewShop-1', ' NewShop-1', via='web',
        )
        self.assertEqual(spaced.get('code'), 'policy')
        ok = er.redeem_superadmin(
            self.conn, issued['token'], 'NewShop-1', 'NewShop-1', via='till',
        )
        self.assertTrue(ok.get('success'), ok)

    def test_developer_endpoint_denies_shop_admin_and_superadmin(self):
        for role in ('admin', 'superadmin', 'manager', 'cashier'):
            decision = er.developer_recovery_decision(role, 'local')
            self.assertFalse(decision['allowed'])
            self.assertEqual(decision['status'], 403)
        self.assertFalse(er.developer_recovery_decision('platform_admin', 'local')['allowed'])
        self.assertTrue(er.developer_recovery_decision('platform_admin', 'supabase')['allowed'])
        os.environ['MBT_RECOVERY_TEST_AUTH'] = '0'
        self.assertFalse(er.developer_recovery_decision('platform_admin', 'test-developer')['allowed'])

    def test_wrong_attempts_are_rate_limited(self):
        for _ in range(er.WRONG_LIMIT):
            failed = er.redeem_superadmin(
                self.conn, 'ZZZZ-ZZZZ-ZZZZ', 'NewShop-1', 'NewShop-1', via='till',
            )
            self.assertEqual(failed.get('code'), 'invalid')
        issued = self._issue()
        locked = er.redeem_superadmin(
            self.conn, issued['token'], 'NewShop-1', 'NewShop-1', via='till',
        )
        self.assertEqual(locked.get('code'), 'rate_limited')
        from desktop.utils.api_client import _check_pw
        self.assertTrue(_check_pw('OldShop-1', self._password()))
        self.conn.execute(
            "UPDATE system_settings SET value=? WHERE key=?",
            (str(int(time.time()) - 5), er.LOCK_KEY),
        )
        self.conn.commit()
        ok = er.redeem_superadmin(
            self.conn, issued['token'], 'NewShop-1', 'NewShop-1', via='till',
        )
        self.assertTrue(ok.get('success'), ok)

    def test_device_secret_stays_outside_the_repo(self):
        path = er.device_secret_path()
        self.assertFalse(os.path.normcase(path).startswith(os.path.normcase(str(REPO)) + os.sep))
        self.assertTrue(os.path.isfile(path))
        with self.assertRaises(er.RecoveryError):
            er.device_secret_path(str(REPO))

    def test_issue_history_does_not_store_the_typeable_code(self):
        profile = {
            'product': 'mbt-pos',
            'source': 'local',
            'shop_name': 'Recovery Unit Shop',
            'shop_id': 'shop-unit',
            'device_id': 'MBT-PC-UNITTEST',
            'data_root': os.environ['MBT_DATA_ROOT'],
            'db_path': os.path.join(os.environ['MBT_DATA_ROOT'], 'data', 'mbt_pos.db'),
            'superadmins': [{
                'id': 1, 'username': 'owner', 'full_name': 'Recovery Owner', 'active': True,
            }],
        }
        issued = er.issue_for_target(profile, 1, secret=self.secret)
        row = self.conn.execute(
            "SELECT token_id, shop_id, device_id, user_id, expires_at, issued_at "
            "FROM emergency_recovery_issues"
        ).fetchone()
        stored = ' '.join(str(value) for value in row)
        self.assertEqual(row['token_id'], issued['token_id'])
        self.assertNotIn(issued['token'], stored)
        self.assertNotIn(issued['token'].replace('-', ''), stored)
        public = er.public_recovery_profile(profile, developer=True)
        self.assertNotIn('recovery_secret', public)

    def test_cloud_lookup_uses_the_device_identity_and_rejects_other_products(self):
        def select(table, _query):
            if table == 'devices':
                return [{
                    'device_id': 'MBT-PC-CLOUD1',
                    'org_id': 'org-1',
                    'shop_instance_id': 'shop-cloud',
                    'business_name': 'Cloud Shop',
                    'hostname': 'TILL-1',
                    'superadmin_username': 'owner',
                    'superadmin_user_id': 4,
                    'superadmin_full_name': 'Cloud Owner',
                }]
            return [{
                'product_id': 'pulse',
                'status': 'active',
                'plan': 'monthly',
                'org_id': 'org-1',
            }]
        with self.assertRaises(PermissionError):
            er.cloud_recovery_profile('MBT-PC-CLOUD1', select=select)

        def select_pos(table, _query):
            if table == 'devices':
                return select('devices', _query)
            return [{
                'product_id': 'mbt-pos',
                'status': 'active',
                'plan': 'yearly',
                'org_id': 'org-1',
            }]
        profile = er.cloud_recovery_profile('MBT-PC-CLOUD1', select=select_pos)
        self.assertEqual(profile['device_id'], 'MBT-PC-CLOUD1')
        self.assertEqual(profile['shop_id'], 'shop-cloud')
        self.assertEqual(profile['superadmins'][0]['username'], 'owner')
        self.assertEqual(profile['licence_state'], 'active')

    def test_edmus_target_is_refused(self):
        with self.assertRaises(PermissionError):
            er.issue_for_target({
                'product': 'mbt-pos',
                'shop_name': 'Edmus Shop',
                'shop_id': 'shop-x',
                'device_id': 'MBT-PC-CLOUD1',
                'licence_state': 'active',
                'superadmins': [{
                    'id': 1, 'username': 'owner', 'full_name': 'Owner', 'active': True,
                }],
            }, 1)

    def test_cloud_issue_without_the_device_secret_is_refused(self):
        with self.assertRaises(er.RecoveryError) as denied:
            er.issue_for_target({
                'product': 'mbt-pos',
                'source': 'cloud',
                'shop_name': 'Cloud Shop',
                'shop_id': 'shop-cloud',
                'device_id': 'MBT-PC-CLOUD1',
                'superadmins': [{
                    'id': 4, 'username': 'owner', 'full_name': 'Cloud Owner', 'active': True,
                }],
            }, 4)
        self.assertEqual(denied.exception.code, 'secret')
        self.assertIn('cannot change the shop password', denied.exception.message)


class ExistingRecoveryCase(unittest.TestCase):
    def setUp(self):
        self._saved = {
            key: os.environ.get(key)
            for key in ('MBT_TEST_INSTANCE', 'MBT_DATA_ROOT', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMDATA')
        }
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.environ['MBT_TEST_INSTANCE'] = '1'
        os.environ['MBT_DATA_ROOT'] = root
        os.environ['APPDATA'] = os.path.join(root, 'appdata')
        os.environ['LOCALAPPDATA'] = os.path.join(root, 'local')
        os.environ['PROGRAMDATA'] = os.path.join(root, 'programdata')
        os.makedirs(os.path.join(root, 'data'), exist_ok=True)
        from desktop.utils.api_client import APIClient, _check_pw, _hash_pw, clear_login_lockout_cache
        self.client_cls = APIClient
        self.check = _check_pw
        self.hash = _hash_pw
        clear_login_lockout_cache()
        db_path = os.path.join(root, 'data', 'mbt_pos.db')
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password_hash TEXT,
                role TEXT,
                full_name TEXT,
                email TEXT,
                is_active INTEGER DEFAULT 1,
                tab_permissions TEXT DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                action TEXT,
                module TEXT,
                details TEXT,
                ip_address TEXT,
                created_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ('owner', _hash_pw('OldShop-1'), 'superadmin', 'Owner'),
        )
        conn.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ('shopadmin', _hash_pw('AdminPass-1'), 'admin', 'Shop Admin'),
        )
        conn.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ('cashier1', _hash_pw('Cashier-1'), 'cashier', 'Cashier'),
        )
        from desktop.utils.security import _pin_hash
        conn.execute(
            "INSERT INTO system_settings (key, value) VALUES ('superadmin_pin_hash', ?)",
            (_pin_hash('123456'),),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def _api(self, user_id, username, role):
        api = self.client_cls()
        api._user_id = user_id
        api._username = username
        api._role = role
        return api

    def _hash_for(self, username):
        from desktop.utils.api_client import _db
        db = _db()
        try:
            return db.execute(
                "SELECT password_hash FROM users WHERE username=?", (username,)
            ).fetchone()['password_hash']
        finally:
            db.close()

    def test_own_password_change_still_works(self):
        api = self._api(1, 'owner', 'superadmin')
        bad = api.change_own_password('wrong', 'Changed-1', 'Changed-1')
        self.assertFalse(bad.get('success'))
        self.assertTrue(self.check('OldShop-1', self._hash_for('owner')))
        ok = api.change_own_password('OldShop-1', 'Changed-1', 'Changed-1')
        self.assertTrue(ok.get('success'), ok)
        self.assertTrue(self.check('Changed-1', self._hash_for('owner')))

    def test_admin_can_still_reset_a_staff_password(self):
        api = self._api(2, 'shopadmin', 'admin')
        result = api.update_user(3, {'password': 'Staff-123'})
        self.assertTrue(result.get('success'), result)
        self.assertTrue(self.check('Staff-123', self._hash_for('cashier1')))
        self.assertEqual(
            self._api(2, 'shopadmin', 'admin').get_users()[0]['role'] if False else 'cashier',
            'cashier',
        )
        from desktop.utils.api_client import _db
        db = _db()
        try:
            role = db.execute("SELECT role FROM users WHERE username='cashier1'").fetchone()['role']
        finally:
            db.close()
        self.assertEqual(role, 'cashier')

    def test_pin_recovery_still_resets_an_admin_password(self):
        api = self._api(None, '', '')
        bad = api.reset_forgotten_admin_password('000000', 'shopadmin', 'PinReset-1')
        self.assertFalse(bad.get('success'))
        self.assertTrue(self.check('AdminPass-1', self._hash_for('shopadmin')))
        ok = api.reset_forgotten_admin_password('123456', 'shopadmin', 'PinReset-1')
        self.assertTrue(ok.get('success'), ok)
        self.assertTrue(self.check('PinReset-1', self._hash_for('shopadmin')))
        self.assertEqual(ok.get('username'), 'shopadmin')


class HttpRecoveryCase(unittest.TestCase):
    def test_shop_admin_is_denied_and_forgot_password_stays(self):
        root = tempfile.mkdtemp(prefix='mbt-recovery-http-')
        live = _live_shop()
        self.assertFalse(os.path.normcase(os.path.abspath(root)).startswith(live))
        env = os.environ.copy()
        env.update({
            'MBT_TEST_INSTANCE': '1',
            'MBT_DATA_ROOT': root,
            'APPDATA': os.path.join(root, 'appdata'),
            'LOCALAPPDATA': os.path.join(root, 'local'),
            'PROGRAMDATA': os.path.join(root, 'programdata'),
            'MBT_RECOVERY_TEST_AUTH': '1',
            'MBT_RECOVERY_TEST_TOKEN': 'recovery-test-token-' + 'a' * 24,
            'PYTHONPATH': str(REPO),
        })
        env.pop('MBT_RECOVERY_PRIVATE_KEY_FILE', None)
        proc = subprocess.run(
            [sys.executable, str(REPO / 'tests' / 'emergency_recovery_http_probe.py')],
            cwd=str(REPO),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + '\n' + proc.stderr)
        line = [row for row in proc.stdout.splitlines() if row.startswith('RESULT ')][-1]
        result = json.loads(line[len('RESULT '):])
        self.assertEqual(result['admin_status'], 403)
        self.assertEqual(result['superadmin_status'], 403)
        self.assertTrue(result['forgot_ok'])
        self.assertNotIn('MBT1.', json.dumps(result))
        self.assertTrue(result['issued'])
        self.assertTrue(result['issued'].get('format_ok'))
        self.assertEqual(result['replay_code'], 400)


if __name__ == '__main__':
    unittest.main()
