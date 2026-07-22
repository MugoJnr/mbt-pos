"""S02: failed-login lockout (5 attempts → 60s), persisted in system_settings."""
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


class LoginLockoutTests(unittest.TestCase):
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
        pw = ac._hash_pw('correct-horse')
        db.execute(
            "INSERT INTO users (username, password_hash, role, is_active) "
            "VALUES (?,?,?,1)",
            ('lockuser', pw, 'cashier'),
        )
        db.commit()
        db.close()

    def tearDown(self):
        self.ac.clear_login_lockout_cache()
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_five_failures_lock_then_expire(self):
        for i in range(4):
            res = self.api.login('lockuser', 'wrong')
            self.assertNotIn('token', res)
            self.assertFalse(res.get('locked'))
            self.assertEqual(res.get('attempts_remaining'), 4 - i)

        res = self.api.login('lockuser', 'wrong')
        self.assertTrue(res.get('locked'))
        self.assertIn('Locked', res.get('error', ''))

        res = self.api.login('lockuser', 'correct-horse')
        self.assertTrue(res.get('locked'))
        self.assertNotIn('token', res)

        key = 'lockuser'
        self.ac._LOGIN_ATTEMPTS[key]['locked_until'] = time.time() - 1
        ok = self.api.login('lockuser', 'correct-horse')
        self.assertIn('token', ok)
        self.assertNotIn(key, self.ac._LOGIN_ATTEMPTS)

    def test_success_clears_partial_failures(self):
        self.api.login('lockuser', 'wrong')
        self.api.login('lockuser', 'wrong')
        ok = self.api.login('lockuser', 'correct-horse')
        self.assertIn('token', ok)
        self.assertNotIn('lockuser', self.ac._LOGIN_ATTEMPTS)

    def test_lockout_survives_cache_clear(self):
        for _ in range(5):
            self.api.login('lockuser', 'wrong')
        self.assertTrue(self.api.login('lockuser', 'x').get('locked'))
        self.ac.clear_login_lockout_cache()
        api2 = self.ac.APIClient()
        res = api2.login('lockuser', 'correct-horse')
        self.assertTrue(res.get('locked'), res)
        self.assertNotIn('token', res)


if __name__ == '__main__':
    unittest.main()
