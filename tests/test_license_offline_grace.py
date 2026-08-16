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

    def test_activation_survives_wiped_config_hmac_secret(self):
        """Shop PCs must stay licensed after config/.activation_hmac_secret is gone."""
        import launcher

        cfg_dir = os.path.join(self._tmpdir.name, 'config')
        os.makedirs(cfg_dir, exist_ok=True)
        hmac_path = os.path.join(cfg_dir, '.activation_hmac_secret')
        with open(hmac_path, 'w', encoding='utf-8') as f:
            f.write('legacy-config-hmac-secret-value-not-used-after-wipe-xxxx')

        ok, message = self.engine.activate_from_cloud(
            plan='pro',
            duration_days=365,
            license_key='MBT-PRO-TEST-PERSIST',
        )
        self.assertTrue(ok, message)
        self.assertTrue(self.engine.is_valid)

        os.remove(hmac_path)
        self.le._MASTER_SECRET_CACHE = None
        self.le._LEGACY_SECRET_CANDIDATES = None

        eng2 = self.le.LicenseEngine()
        self.assertTrue(eng2.is_valid, 'license must decrypt without config HMAC secret')
        self.assertTrue(eng2.has_local_license_payload())
        self.assertTrue(launcher._shop_already_ready(eng2))
        crypto = os.path.join(os.path.dirname(self._db_path), 'crypto.secret')
        self.assertTrue(os.path.isfile(crypto), 'secret must be co-located with lc.db')

    def test_clock_rollback_after_restart_keeps_license(self):
        """Windows clock lag after reboot must not show the activation screen."""
        import launcher

        ok, message = self.engine.activate_from_cloud(
            plan='trial',
            duration_days=30,
            license_key='MBT-TRI-TEST-CLOCK',
        )
        self.assertTrue(ok, message)
        now = int(time.time())
        self.engine.store.set('highest_ts_seen', now + 10_000)
        self.engine.store.set('last_checked_ts', now + 10_000)
        self.engine.store.set('tampered', True)

        self.engine.revalidate()
        self.assertTrue(self.engine.is_valid)
        self.assertNotEqual(self.engine.state, self.le.STATE_TAMPERED)
        self.assertTrue(launcher._shop_already_ready(self.engine))

        eng2 = self.le.LicenseEngine()
        self.assertTrue(eng2.is_valid)
        self.assertTrue(launcher._shop_already_ready(eng2))


class LicenseCloudDeviceIdPersistTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'license.db')
        os.environ['MBT_ACTIVATION_HMAC_SECRET'] = 'unit-test-activation-hmac-secret-value-xxxx'
        import licensing.license_engine as le

        self.le = le
        le._MASTER_SECRET_CACHE = None
        le._LEGACY_SECRET_CANDIDATES = None
        self._fp = 'a' * 40
        self._patches = [
            patch.object(le, '_hidden_db_path', return_value=self._db_path),
            patch.object(le, '_get_device_fingerprint', return_value=self._fp),
            patch.object(le, '_get_legacy_wmic_fingerprint', return_value='c' * 40),
            patch.object(le, '_cloud_identity_device_ids', return_value=['MBT-PC-52E5']),
            patch('mbt_paths.get_project_root', return_value=self._tmpdir.name),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        os.environ.pop('MBT_ACTIVATION_HMAC_SECRET', None)
        self.le._MASTER_SECRET_CACHE = None
        self.le._LEGACY_SECRET_CANDIDATES = None
        self._tmpdir.cleanup()

    def test_mbt_pc_bound_token_survives_relaunch(self):
        """Older Edmus tokens used MBT-PC-XXXX as the HMAC device id."""
        import launcher

        cloud_id = 'MBT-PC-52E5'
        now = int(time.time())
        lic = {
            'device_id': cloud_id,
            'plan': 'trial',
            'issued_at': now,
            'expires_at': now + 30 * 86400,
            'duration_days': 30,
            'activated_at': now,
            'issued_by': 'MugoByte Platform',
            'license_key': 'MBT-TRI-TEST-EDMUS',
            'source': 'mbt_cloud',
            'version': 2,
        }
        store = self.le.LicenseStore(cloud_id)
        store.set('license_token', self.le.encrypt_payload(lic, cloud_id))
        store.set('tampered', False)

        engine = self.le.LicenseEngine()
        self.assertTrue(engine.is_valid, 'must decrypt MBT-PC-bound token on relaunch')
        self.assertTrue(launcher._shop_already_ready(engine))
        self.assertEqual(engine.device_id, self._fp)

        engine2 = self.le.LicenseEngine()
        self.assertTrue(engine2.is_valid)
        self.assertEqual(engine2.device_id, self._fp)


if __name__ == '__main__':
    unittest.main()
