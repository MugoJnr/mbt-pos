"""I05/I06 smoke: invalid key rejection + offline grace window (EXISTS code path)."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest.mock import patch


class LicenseOfflineGraceTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'license.db')
        self._device = 'b' * 40
        import licensing.license_engine as le

        self.le = le
        self._patches = [
            patch.object(le, '_hidden_db_path', return_value=self._db_path),
            patch.object(le, 'resolve_device_id', return_value=self._device),
            patch('mbt_paths.get_project_root', return_value=self._tmpdir.name),
        ]
        for p in self._patches:
            p.start()
        self.engine = le.LicenseEngine()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()

    def test_invalid_key_rejected(self):
        ok, msg = self.engine.activate_with_key('NOT-A-VALID-KEY')
        self.assertFalse(ok)
        self.assertTrue(msg)
        self.assertIn('invalid', msg.lower())

    def test_offline_grace_allows_within_window(self):
        ok, message = self.engine.activate_from_cloud(
            plan='trial',
            duration_days=30,
            license_key='MBT-TRI-TEST-GRACE',
        )
        self.assertTrue(ok, message)
        now = int(time.time())
        self.engine.store.set('last_cloud_ok_ts', now - 2 * 86400)  # 2 days offline
        allowed, msg = self.engine.enforce_offline_grace(grace_days=7)
        self.assertTrue(allowed, msg)
        self.assertFalse(bool(self.engine.store.get('offline_lock')))

    def test_offline_grace_locks_after_exceeded(self):
        ok, message = self.engine.activate_from_cloud(
            plan='trial',
            duration_days=30,
            license_key='MBT-TRI-TEST-GRACE-LOCK',
        )
        self.assertTrue(ok, message)
        now = int(time.time())
        self.engine.store.set('last_cloud_ok_ts', now - 10 * 86400)  # 10 days
        allowed, msg = self.engine.enforce_offline_grace(grace_days=7)
        self.assertFalse(allowed, msg)
        self.assertTrue(bool(self.engine.store.get('offline_lock')))
        self.assertTrue(bool(self.engine.store.get('requires_online')))


if __name__ == '__main__':
    unittest.main()
