"""Password, PIN, sessions, stock-reduction PIN, and finance routes on an isolated database."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class AccountFinanceGapTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'gap.db')
        os.environ['MBT_DATA_ROOT'] = self._tmpdir.name
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) "
            "VALUES (?,?,?,?,1)",
            ('owner', ac._hash_pw('owner-pass'), 'superadmin', 'Owner'),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES ('Gap Soap', 'GAP-SOAP', 50, 20, 10, 1)"
        )
        db.commit()
        self.owner_id = db.execute(
            "SELECT id FROM users WHERE username='owner'"
        ).fetchone()['id']
        self.product_id = db.execute(
            "SELECT id FROM products WHERE sku='GAP-SOAP'"
        ).fetchone()['id']
        db.close()
        self.api._user_id = self.owner_id
        self.api._username = 'owner'
        self.api._role = 'superadmin'

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_own_password_rejects_wrong_current_and_accepts_new(self):
        bad = self.api.change_own_password('nope', 'new-pass', 'new-pass')
        self.assertIn('incorrect', bad.get('error', '').lower())
        short = self.api.change_own_password('owner-pass', 'x', 'x')
        self.assertIn('6', short.get('error', ''))
        mismatch = self.api.change_own_password('owner-pass', 'new-pass', 'other-pass')
        self.assertIn('match', mismatch.get('error', '').lower())
        ok = self.api.change_own_password('owner-pass', 'new-pass', 'new-pass')
        self.assertTrue(ok.get('success'), ok)
        failed = self.api.login('owner', 'owner-pass')
        self.assertIn('error', failed)
        signed = self.api.login('owner', 'new-pass')
        self.assertIn('token', signed)
        self.assertTrue(signed.get('till_session_id'))

    def test_till_end_is_pending_until_the_till_accepts_it(self):
        signed = self.api.login('owner', 'owner-pass')
        sid = signed['till_session_id']
        from desktop.utils.account_sessions import list_till_sessions, request_till_end
        db = self.ac._db()
        try:
            self.assertEqual(list_till_sessions(db)[0]['state'], 'signed_in')
            pending = request_till_end(db, sid)
            db.commit()
            self.assertEqual(pending['state'], 'pending')
        finally:
            db.close()
        self.api._till_session_id = sid
        self.assertTrue(self.api.poll_till_logout())
        self.assertFalse(self.api.poll_till_logout())

    def test_web_session_revoke_blocks_the_token(self):
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        client = appmod.app.test_client()
        login = client.post('/api/auth/login', json={'username': 'owner', 'password': 'owner-pass'})
        self.assertEqual(login.status_code, 200, login.get_json())
        token = login.get_json()['token']
        headers = {'Authorization': f'Bearer {token}'}
        listed = client.get('/api/sessions', headers=headers)
        self.assertEqual(listed.status_code, 200, listed.get_json())
        sessions = listed.get_json()['sessions']
        self.assertEqual(len(sessions), 1)
        revoked = client.post(f"/api/sessions/{sessions[0]['id']}/revoke", headers=headers)
        self.assertEqual(revoked.status_code, 200, revoked.get_json())
        me = client.get('/api/auth/me', headers=headers)
        self.assertEqual(me.status_code, 401)

    def test_password_route_and_pin_route(self):
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        client = appmod.app.test_client()
        login = client.post('/api/auth/login', json={'username': 'owner', 'password': 'owner-pass'})
        headers = {'Authorization': f"Bearer {login.get_json()['token']}"}
        changed = client.post('/api/account/password', headers=headers, json={
            'current_password': 'owner-pass',
            'new_password': 'route-pass',
            'confirm_password': 'route-pass',
        })
        self.assertEqual(changed.status_code, 200, changed.get_json())
        again = client.post('/api/auth/login', json={'username': 'owner', 'password': 'owner-pass'})
        self.assertEqual(again.status_code, 401)
        fresh = client.post('/api/auth/login', json={'username': 'owner', 'password': 'route-pass'})
        headers = {'Authorization': f"Bearer {fresh.get_json()['token']}"}
        pin = client.post('/api/account/pin', headers=headers, json={
            'current_pin': '',
            'new_pin': '246810',
            'confirm_pin': '246810',
        })
        self.assertEqual(pin.status_code, 200, pin.get_json())
        wrong = client.post('/api/account/pin', headers=headers, json={
            'current_pin': '000000',
            'new_pin': '135790',
            'confirm_pin': '135790',
        })
        self.assertEqual(wrong.status_code, 403)

    def test_stock_reduction_review_requires_pin(self):
        self.api.change_superadmin_pin('', '246810', '246810')
        asked = self.api.request_stock_adjustment(self.product_id, 7, 'Count was short')
        self.assertTrue(asked.get('success'), asked)
        self.api._role = 'manager'
        blocked = self.api.review_stock_adjustment(asked['id'], 'approved', 'ok', pin='')
        self.assertEqual(blocked.get('status'), 403)
        db = self.ac._db()
        try:
            stock = db.execute("SELECT stock FROM products WHERE id=?", (self.product_id,)).fetchone()['stock']
        finally:
            db.close()
        self.assertEqual(float(stock), 10)
        self.api._role = 'superadmin'
        approved = self.api.review_stock_adjustment(asked['id'], 'approved', 'ok', pin='')
        self.assertTrue(approved.get('success'), approved)
        db = self.ac._db()
        try:
            stock = db.execute("SELECT stock FROM products WHERE id=?", (self.product_id,)).fetchone()['stock']
        finally:
            db.close()
        self.assertEqual(float(stock), 7)

    def test_expense_posts_and_reverses_without_erasing_history(self):
        created = self.api.accounting_create_expense({
            'amount': 80,
            'description': 'Gap cleaning',
            'vendor_name': 'QA',
            'expense_date': '2026-10-23',
            'account_code': '6000',
            'pay_from_code': '1000',
        })
        self.assertTrue(created.get('success'), created)
        pnl = self.api.accounting_pnl('2026-10-01', '2026-10-31')
        self.assertGreaterEqual(float(pnl.get('total_expenses') or 0), 80)
        trial = self.api.accounting_trial_balance('2026-10-31')
        self.assertTrue(trial.get('balanced'), trial)
        unbalanced = self.api.accounting_post_manual({
            'description': 'Unbalanced',
            'entry_date': '2026-10-23',
            'lines': [
                {'account_code': '6000', 'debit': 10, 'memo': 'only debit'},
            ],
        })
        self.assertTrue(unbalanced.get('error'))
        reversed_row = self.api.accounting_reverse_expense(created['id'], 'Entered twice')
        self.assertTrue(reversed_row.get('success'), reversed_row)
        rows = self.api.accounting_expenses('2026-10-01', '2026-10-31')
        original = next(row for row in rows if row['id'] == created['id'])
        self.assertEqual(original['status'], 'reversed')
        self.assertIsNone(original.get('deleted_at'))

    def test_pin_failures_are_shared_across_clients(self):
        self.api.change_superadmin_pin('', '246810', '246810')
        for _ in range(8):
            self.api.change_superadmin_pin('000000', '135790', '135790')
        other = self.ac.APIClient()
        other._user_id = self.owner_id
        other._username = 'owner'
        other._role = 'superadmin'
        blocked = other.change_superadmin_pin('246810', '135790', '135790')
        self.assertEqual(blocked.get('status'), 429, blocked)

    def test_publish_without_conflict_updates_existing_version(self):
        from backend.cloud.update_center import UpdateCenter

        class Response:
            def __init__(self, status, payload):
                self.status_code = status
                self._payload = payload
                self.content = b'1' if payload is not None else b''
                self.text = ''

            def json(self):
                return self._payload

        class Session:
            def __init__(self):
                self.posts = []
                self.patches = []

            def get(self, url, headers=None, params=None, timeout=None):
                return Response(200, [{'id': 4, 'version': '9.9.9'}])

            def patch(self, url, headers=None, params=None, json=None, timeout=None):
                self.patches.append(json)
                return Response(200, [json])

            def post(self, url, headers=None, params=None, json=None, timeout=None):
                self.posts.append(json)
                return Response(201, [json])

        class Client:
            def __init__(self):
                self._session = Session()

            def _url(self, path):
                return 'https://example.test' + path

            def _headers(self, use_service=False):
                return {}

        center = UpdateCenter.__new__(UpdateCenter)
        client = Client()
        saved = center._publish_without_conflict_target(client, {
            'version': '9.9.9',
            'checksum_sha256': 'a' * 64,
        })
        self.assertEqual(saved['version'], '9.9.9')
        self.assertEqual(len(client._session.patches), 1)
        self.assertEqual(client._session.posts, [])


class InstallerChecksumPolicyTests(unittest.TestCase):
    def test_missing_wrong_and_matching_checksums(self):
        import hashlib

        from backend.updater import verify_installer_checksum

        fd, path = tempfile.mkstemp(suffix='.exe')
        short = path + '.short'
        try:
            os.write(fd, b'MBT-POS-installer-bytes')
            os.close(fd)
            digest = hashlib.sha256(b'MBT-POS-installer-bytes').hexdigest()
            ok, detail = verify_installer_checksum(path, '')
            self.assertFalse(ok)
            self.assertEqual(detail, 'missing_checksum')
            ok, detail = verify_installer_checksum(path, 'b' * 64)
            self.assertFalse(ok)
            self.assertTrue(detail.startswith('checksum_mismatch:'))
            with open(path, 'rb') as src, open(short, 'wb') as dst:
                dst.write(src.read(4))
            ok, _detail = verify_installer_checksum(short, digest)
            self.assertFalse(ok)
            ok, detail = verify_installer_checksum(path, digest)
            self.assertTrue(ok)
            self.assertEqual(detail, digest)
        finally:
            if os.path.exists(path):
                os.remove(path)
            if os.path.exists(short):
                os.remove(short)
