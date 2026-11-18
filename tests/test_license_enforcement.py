"""Regression: expiry, startup, offline lock, device bind, backup vs licence store.

Disposable fixtures only. No live shop database and no portal credentials.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest.mock import patch


def _plant(le, device: str, **overrides) -> None:
    now = int(time.time())
    lic = {
        'device_id': device,
        'plan': 'trial',
        'issued_at': now - 10 * 86400,
        'expires_at': now + 30 * 86400,
        'duration_days': 30,
        'activated_at': now - 10 * 86400,
        'issued_by': 'unit-test',
        'source': 'mbt_cloud',
        'version': 2,
    }
    lic.update(overrides)
    store = le.LicenseStore(device)
    store.set('license_token', le.encrypt_payload(lic, device))
    store.set('highest_ts_seen', now)
    store.set('last_checked_ts', now)
    store.set('tampered', False)
    store.set('revoked', False)


class _DisposableLicence(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'license.db')
        self._device = 'd' * 40
        self._flag = os.path.join(self._tmpdir.name, 'data', '.initialized')
        os.makedirs(os.path.dirname(self._flag), exist_ok=True)
        import licensing.license_engine as le

        self.le = le
        self.le._MASTER_SECRET_CACHE = None
        self.le._LEGACY_SECRET_CANDIDATES = None
        self.le._TRUSTED_TIME_CACHE['ts'] = None
        self.le._TRUSTED_TIME_CACHE['fetched_at'] = 0.0
        self.le._TRUSTED_TIME_CACHE['fail_until'] = 0.0
        self._patches = [
            patch.object(le, '_hidden_db_path', return_value=self._db_path),
            patch.object(le, 'resolve_device_id', return_value=self._device),
            patch.object(le, '_get_device_fingerprint', return_value=self._device),
            patch.object(le, '_get_legacy_wmic_fingerprint', return_value=''),
            patch.object(le, '_cheap_device_id_candidates', return_value=[self._device]),
            patch.object(le, '_sync_cloud_identity_fingerprint'),
            patch('mbt_paths.get_project_root', return_value=self._tmpdir.name),
            patch('mbt_paths.get_init_flag_path', return_value=self._flag),
        ]
        for item in self._patches:
            item.start()
        self.engine = le.LicenseEngine()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self.le._MASTER_SECRET_CACHE = None
        self.le._LEGACY_SECRET_CANDIDATES = None
        self._tmpdir.cleanup()


class ExpiryAndStartupTests(_DisposableLicence):
    def test_expired_licence_cannot_open_protected_operations(self):
        import launcher
        from desktop.utils.api_client import APIClient

        now = int(time.time())
        _plant(
            self.le, self._device,
            expires_at=now - 86400,
            issued_at=now - 40 * 86400,
            activated_at=now - 40 * 86400,
        )
        with open(self._flag, 'w', encoding='utf-8') as handle:
            handle.write('setup')
        engine = self.le.LicenseEngine()
        self.assertFalse(engine.is_valid)
        self.assertEqual(engine.state, self.le.STATE_EXPIRED)
        self.assertFalse(launcher._shop_already_ready(engine))
        reason = self.le.protected_write_block_reason(engine)
        self.assertIn('expired', reason.lower())
        self.assertIn('unchanged', reason.lower())

        sale = APIClient().create_sale({'items': [{'product_id': 1, 'qty': 1}]})
        self.assertTrue(sale.get('license_block'))
        self.assertIn('expired', sale.get('error', '').lower())
        stock = APIClient().adjust_stock(1, 5, reason='count')
        self.assertTrue(stock.get('license_block'))
        returned = APIClient().return_sale(1, [{'sale_item_id': 1, 'quantity': 1}], 'expired')
        self.assertTrue(returned.get('license_block'))
        edited = APIClient().edit_sale(1, {'reason': 'expired', 'items': []})
        self.assertTrue(edited.get('license_block'))
        taken = APIClient().apply_stocktake(1)
        self.assertTrue(taken.get('license_block'))
        self.assertTrue(os.path.isfile(self._db_path))

    def test_licence_file_and_setup_flag_cannot_bypass_expiry(self):
        import launcher
        from desktop.wizard.setup_wizard import device_has_persisted_license

        now = int(time.time())
        _plant(self.le, self._device, expires_at=now - 3600)
        with open(self._flag, 'w', encoding='utf-8') as handle:
            handle.write('already-setup')
        self.assertTrue(self.le._read_raw_license_token())
        engine = self.le.LicenseEngine()
        self.assertFalse(engine.is_valid)
        self.assertFalse(launcher._shop_already_ready(engine))
        self.assertFalse(device_has_persisted_license())

    def test_garbage_token_plus_setup_flag_is_not_authorization(self):
        import launcher

        store = self.le.LicenseStore(self._device)
        store.set('license_token', 'raw-token-not-a-licence')
        with open(self._flag, 'w', encoding='utf-8') as handle:
            handle.write('already-setup')
        engine = self.le.LicenseEngine()
        self.assertFalse(engine.is_valid)
        self.assertFalse(launcher._shop_already_ready(engine))
        self.assertTrue(self.le.protected_write_block_reason(engine))

    def test_valid_licence_still_works_and_same_computer_relaunch(self):
        import launcher

        ok, message = self.engine.activate_from_cloud(
            plan='trial',
            duration_days=30,
            license_key='MBT-TRI-TEST-VALID',
        )
        self.assertTrue(ok, message)
        self.assertTrue(self.engine.is_valid)
        self.assertGreater(self.engine.days_remaining, 20)
        self.assertEqual(self.le.protected_write_block_reason(self.engine), '')
        self.assertTrue(launcher._shop_already_ready(self.engine))

        relaunch = self.le.LicenseEngine()
        self.assertTrue(relaunch.is_valid)
        self.assertEqual(relaunch.device_id, self._device)
        self.assertTrue(launcher._shop_already_ready(relaunch))
        sale = __import__(
            'desktop.utils.api_client', fromlist=['APIClient']
        ).APIClient().create_sale({})
        self.assertFalse(sale.get('license_block'))

    def test_check_license_ignores_ready_flag_when_engine_is_invalid(self):
        import launcher

        engine = unittest.mock.Mock()
        engine.is_valid = False
        engine.device_id = 'test-device'
        engine.revalidate = unittest.mock.Mock()
        with patch('licensing.license_engine.LicenseEngine', return_value=engine), \
                patch('licensing.license_engine.ensure_license_store_ready', return_value='x'), \
                patch('licensing.activation_ui.show_activation_screen', return_value=False) as screen, \
                patch.object(launcher, '_shop_already_ready', return_value=True):
            with self.assertRaises(SystemExit):
                launcher.check_license()
        screen.assert_called_once()

        engine.revalidate.reset_mock()
        with patch('licensing.license_engine.LicenseEngine', return_value=engine), \
                patch('licensing.license_engine.ensure_license_store_ready', return_value='x'), \
                patch('licensing.activation_ui.show_activation_screen', return_value=True), \
                patch.object(launcher, '_shop_already_ready', return_value=True):
            with self.assertRaises(SystemExit):
                launcher.check_license()
        engine.revalidate.assert_called()


class OfflineEnforcementTests(_DisposableLicence):
    def _activate(self):
        ok, message = self.engine.activate_from_cloud(
            plan='trial',
            duration_days=30,
            license_key='MBT-TRI-TEST-OFFLINE',
        )
        self.assertTrue(ok, message)

    def test_offline_lock_survives_restarts_and_allowance_is_not_reset(self):
        import launcher

        self._activate()
        now = int(time.time())
        stamp = now - 10 * 86400
        self.engine.store.set('last_cloud_ok_ts', stamp)
        self.engine.store.set('offline_lock', True)
        self.engine.store.set('requires_online', True)

        self.assertTrue(launcher._shop_already_ready(self.engine))
        self.assertTrue(bool(self.engine.store.get('offline_lock')))

        for _ in range(3):
            eng = self.le.LicenseEngine()
            self.assertTrue(bool(eng.store.get('offline_lock')))
            self.assertEqual(int(eng.store.get('last_cloud_ok_ts')), stamp)
            launcher._shop_already_ready(eng)
            self.assertTrue(bool(eng.store.get('offline_lock')))
            self.assertEqual(int(eng.store.get('last_cloud_ok_ts')), stamp)
            allowed, _msg = eng.enforce_offline_grace(grace_days=7)
            self.assertFalse(allowed)
            self.assertTrue(bool(eng.store.get('offline_lock')))
            self.assertEqual(int(eng.store.get('last_cloud_ok_ts')), stamp)

    def test_temporary_network_failure_inside_existing_grace_still_allows(self):
        self._activate()
        now = int(time.time())
        stamp = now - 2 * 86400
        self.engine.store.set('last_cloud_ok_ts', stamp)
        self.engine.store.set('offline_lock', False)
        allowed, _msg = self.engine.enforce_offline_grace(grace_days=7)
        self.assertTrue(allowed)
        self.assertTrue(self.engine.is_valid)
        eng = self.le.LicenseEngine()
        self.assertEqual(int(eng.store.get('last_cloud_ok_ts')), stamp)
        allowed_again, _msg = eng.enforce_offline_grace(grace_days=7)
        self.assertTrue(allowed_again)
        self.assertTrue(eng.is_valid)
        self.assertNotEqual(eng.state, self.le.STATE_EXPIRED)

    def test_clock_rollback_does_not_extend_authorization_or_clear_lock(self):
        now = int(time.time())
        _plant(
            self.le, self._device,
            expires_at=now - 3 * 86400,
            issued_at=now - 40 * 86400,
            activated_at=now - 40 * 86400,
        )
        store = self.le.LicenseStore(self._device)
        store.set('highest_ts_seen', now)
        store.set('last_checked_ts', now)
        stamp = now - 10 * 86400
        store.set('last_cloud_ok_ts', stamp)
        store.set('offline_lock', True)

        rolled = now - 30 * 86400
        with patch('licensing.license_engine.time.time', return_value=rolled):
            engine = self.le.LicenseEngine()
            self.assertFalse(engine.is_valid)
            self.assertEqual(engine.state, self.le.STATE_EXPIRED)
            self.assertEqual(engine.days_remaining, 0)
            self.assertTrue(bool(engine.store.get('offline_lock')))
            allowed, _msg = engine.enforce_offline_grace(grace_days=7)
            self.assertFalse(allowed)
            self.assertTrue(bool(engine.store.get('offline_lock')))
            self.assertEqual(int(engine.store.get('last_cloud_ok_ts')), stamp)


class DeviceAndBackupTests(_DisposableLicence):
    def test_copied_licence_does_not_validate_on_another_device(self):
        import launcher

        other = 'e' * 40
        now = int(time.time())
        _plant(self.le, other, expires_at=now + 30 * 86400)
        engine = self.le.LicenseEngine()
        self.assertEqual(engine.device_id, self._device)
        self.assertFalse(engine.is_valid)
        self.assertEqual(engine.state, self.le.STATE_TAMPERED)
        self.assertFalse(launcher._shop_already_ready(engine))
        reason = self.le.protected_write_block_reason(engine)
        self.assertIn('computer', reason.lower())

    def test_shop_db_restore_does_not_replace_licence_store(self):
        import sqlite3
        import zipfile
        from backend.db_backup import create_db_backup_zip

        shop = os.path.join(self._tmpdir.name, 'mbt_pos.db')
        conn = sqlite3.connect(shop)
        conn.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)')
        conn.execute("INSERT INTO t (name) VALUES ('shop')")
        conn.commit()
        conn.close()

        _plant(self.le, self._device)
        before_handle = open(self._db_path, 'rb')
        try:
            before = before_handle.read()
        finally:
            before_handle.close()
        zip_path, _size, _digest = create_db_backup_zip(shop)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                names = zf.namelist()
                self.assertIn('mbt_pos.db', names)
                self.assertNotIn('lc.db', names)
                self.assertFalse(any(name.endswith('license.db') for name in names))
            restored = os.path.join(self._tmpdir.name, 'restored.db')
            with zipfile.ZipFile(zip_path, 'r') as zf:
                with zf.open('mbt_pos.db') as src, open(restored, 'wb') as dst:
                    dst.write(src.read())
            after_handle = open(self._db_path, 'rb')
            try:
                after = after_handle.read()
            finally:
                after_handle.close()
            self.assertEqual(after, before)
            self.assertTrue(self.le.LicenseEngine().is_valid)
        finally:
            try:
                os.remove(zip_path)
            except OSError:
                pass

    def test_transfer_device_rebinding_is_local_mock_only(self):
        """Portal transfer of a real Edmus licence is not executed."""
        from backend.cloud.license_server import CloudLicenseServer

        calls = {'update': [], 'insert': []}
        server = CloudLicenseServer.__new__(CloudLicenseServer)

        def _update(table, filt, payload):
            calls['update'].append((table, filt, dict(payload)))

        def _rows(_table, _query):
            return [{'org_id': 'org-disposable'}]

        def _insert(table, payload, upsert=False, on_conflict=''):
            calls['insert'].append((table, dict(payload), upsert, on_conflict))

        server._update = _update
        server._rows = _rows
        server._insert = _insert
        server._sync_activated_devices = lambda _license_id: None
        server._log_history = lambda *_a, **_k: None

        with patch(
            'backend.cloud.license_server.generate_activation_token',
            return_value='disposable-token',
        ):
            ok, message = server.transfer_device(
                'lic-disposable', 'device-old', 'device-new', actor='unit-test',
            )
        self.assertTrue(ok)
        self.assertIn('transferred', message.lower())
        self.assertEqual(calls['update'][0][0], 'license_activations')
        self.assertIn('device-old', calls['update'][0][1])
        self.assertFalse(calls['update'][0][2]['is_active'])
        inserted = calls['insert'][0][1]
        self.assertEqual(inserted['device_id'], 'device-new')
        self.assertTrue(inserted['is_active'])
        self.assertNotEqual(inserted['device_id'], 'device-old')


class ShopApiWriteGateTests(_DisposableLicence):
    def test_http_sale_blocked_when_expired_and_login_stays_available(self):
        from backend.app import app

        now = int(time.time())
        _plant(self.le, self._device, expires_at=now - 86400)
        client = app.test_client()
        sale = client.post('/api/sales', json={'items': [{'product_id': 1}]})
        self.assertEqual(sale.status_code, 403)
        body = sale.get_json() or {}
        self.assertTrue(body.get('license_block'))
        self.assertIn('expired', str(body.get('error') or '').lower())

        login = client.post('/api/auth/login', json={'username': 'nobody', 'password': 'x'})
        self.assertNotEqual(login.status_code, 403)
        listing = client.get('/api/products')
        self.assertNotEqual(listing.status_code, 403)


if __name__ == '__main__':
    unittest.main()
