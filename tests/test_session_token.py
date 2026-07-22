"""S03: JWT session token set / decode / expiry rejection."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SessionTokenTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'test.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self._db_path),
        ]
        for p in self._patches:
            p.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        ac.clear_login_lockout_cache()
        self.ac = ac
        self.api = ac.APIClient()
        db = ac._db()
        pw = ac._hash_pw('secret')
        db.execute(
            "INSERT INTO users (username, password_hash, role, is_active, full_name) "
            "VALUES (?,?,?,1,?)",
            ('tokuser', pw, 'manager', 'Token User'),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_login_token_sets_context(self):
        res = self.api.login('tokuser', 'secret')
        self.assertIn('token', res)
        self.assertEqual(self.api._username, 'tokuser')
        self.assertEqual(self.api._role, 'manager')
        self.assertIsNotNone(self.api._user_id)

    def test_expired_token_does_not_set_context(self):
        import jwt
        token = jwt.encode(
            {
                'user_id': 1,
                'username': 'tokuser',
                'role': 'manager',
                'exp': time.time() - 10,
            },
            self.ac.SECRET_KEY,
            algorithm='HS256',
        )
        api2 = self.ac.APIClient()
        api2.set_token(token)
        # decode fails on expired → context stays unset
        self.assertIsNone(api2._user_id)
        self.assertIsNone(api2._username)


if __name__ == '__main__':
    unittest.main()
