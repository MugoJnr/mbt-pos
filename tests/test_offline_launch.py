"""
Regression: offline shop launch must not hang on Portal/time APIs.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class OfflineLaunchTests(unittest.TestCase):
    def test_trusted_time_fails_open_fast(self):
        from licensing import license_engine as le
        import requests

        le._TRUSTED_TIME_CACHE['ts'] = None
        le._TRUSTED_TIME_CACHE['fetched_at'] = 0.0
        le._TRUSTED_TIME_CACHE['fail_until'] = 0.0

        def boom(*_a, **_k):
            raise requests.exceptions.ConnectTimeout('offline')

        with mock.patch('requests.get', side_effect=boom):
            t0 = time.time()
            self.assertIsNone(le._fetch_trusted_time(allow_network=True))
            self.assertLess(time.time() - t0, 1.0)
            # Negative cache — second call is instant
            t0 = time.time()
            self.assertIsNone(le._fetch_trusted_time(allow_network=True))
            self.assertLess(time.time() - t0, 0.05)

    def test_evaluate_state_never_calls_network(self):
        from licensing import license_engine as le
        from licensing.license_engine import LicenseEngine
        from mbt_paths import get_project_root

        le._TRUSTED_TIME_CACHE['ts'] = None
        le._TRUSTED_TIME_CACHE['fetched_at'] = 0.0
        le._TRUSTED_TIME_CACHE['fail_until'] = 0.0

        with mock.patch('requests.get', side_effect=AssertionError('network forbidden')):
            t0 = time.time()
            eng = LicenseEngine(get_project_root())
            _ = eng.is_valid
            _ = eng.days_remaining
            self.assertLess(time.time() - t0, 5.0)

    def test_offline_lock_does_not_brick_local_license(self):
        from licensing.license_engine import LicenseEngine, STATE_CRITICAL
        from mbt_paths import get_project_root

        eng = LicenseEngine(get_project_root())
        if not eng.has_local_license_payload():
            self.skipTest('no local license on this PC')
        eng.store.set('offline_lock', True)
        eng.store.set('requires_online', True)
        self.assertTrue(eng.is_valid)
        self.assertEqual(eng.state, STATE_CRITICAL)

    def test_launcher_skips_wall_with_valid_local_license(self):
        import launcher
        from licensing.license_engine import LicenseEngine
        from mbt_paths import get_project_root, get_init_flag_path

        eng = LicenseEngine(get_project_root())
        if not (os.path.exists(get_init_flag_path()) or eng.has_local_license_payload()):
            self.skipTest('shop not initialized')
        eng.store.set('offline_lock', True)
        self.assertTrue(launcher._shop_already_ready(eng))

    def test_initialization_marker_without_license_does_not_bypass_gate(self):
        import launcher

        engine = mock.MagicMock()
        engine.is_valid = False
        engine._license_data = None
        engine.has_local_license_payload.return_value = False
        engine.store.get.return_value = False
        with mock.patch('launcher.os.path.exists', return_value=True), \
             mock.patch(
                 'licensing.license_engine._read_raw_license_token',
                 return_value='',
             ), \
             mock.patch(
                 'licensing.license_engine._resolve_inner_license_token',
                 return_value=(None, None),
             ):
            self.assertFalse(launcher._shop_already_ready(engine))

    def test_frozen_build_rejects_locally_signed_key_even_with_env_override(self):
        from licensing.license_engine import LicenseEngine

        engine = mock.MagicMock()
        with mock.patch(
            'licensing.license_engine.decode_license_key',
            return_value={'device_id': 'local-forged'},
        ), mock.patch.dict(
            os.environ, {'MBT_ALLOW_LOCAL_KEYS': '1'},
        ), mock.patch.object(sys, 'frozen', True, create=True):
            ok, message = LicenseEngine.activate_with_key(
                engine, 'locally-signed-forged-key')
        self.assertFalse(ok)
        self.assertIn('no longer accepted', message)
        engine._activate_local_signed_key.assert_not_called()

    def test_service_select_skips_supabase_dns_when_offline(self):
        from backend.cloud import platform_service as ps

        calls = []

        class FakeSession:
            def get(self, *a, **k):
                calls.append(('get', a, k))
                raise AssertionError('must not hit supabase when offline')

        class FakeClient:
            configured = True
            anon = 'anon'
            service = ''
            _session = FakeSession()

            def _url(self, path):
                return 'https://example.supabase.co' + path

        ps._SVC_CLIENT = FakeClient()
        ps._SVC_CONFIG_KEY = ('x',)
        with mock.patch('backend.cloud.platform_service.network_up', return_value=False):
            t0 = time.time()
            self.assertEqual(ps.service_select('devices', 'select=id&limit=1'), [])
            self.assertLess(time.time() - t0, 0.5)
        self.assertEqual(calls, [])

    def test_refresh_session_fails_fast_offline(self):
        from backend.cloud_backup.supabase_client import SupabaseClient, SupabaseError

        client = SupabaseClient(config={
            'supabase_url': 'https://example.supabase.co',
            'anon_key': 'anon',
            'service_key': '',
            'bucket': 'b',
        })
        with mock.patch(
            'backend.cloud_backup.supabase_client.load_identity',
            return_value={'refresh_token': 'rt', 'auth_state': ''},
        ), mock.patch(
            'backend.cloud_backup.supabase_client._require_network',
            side_effect=SupabaseError('Offline — MugoByte Cloud unreachable', 503),
        ):
            t0 = time.time()
            with self.assertRaises(SupabaseError):
                client.refresh_session()
            self.assertLess(time.time() - t0, 0.5)

    def test_splash_boot_starts_cloud_off_main_thread(self):
        main_path = os.path.join(ROOT, 'desktop', 'main.py')
        src = open(main_path, encoding='utf-8').read()
        self.assertIn("name='CloudBoot'", src)
        self.assertIn('_boot_cloud_and_payments', src)
        self.assertIn('threading.Thread(target=_boot_cloud_and_payments', src)
        # Heartbeat must live inside the background boot helper, not sync on splash
        idx = src.index('def _boot_cloud_and_payments')
        end = src.index('threading.Thread(target=_boot_cloud_and_payments', idx)
        boot = src[idx:end]
        self.assertIn('start_heartbeat', boot)
        self.assertIn('start_poller', boot)

    def test_payments_cloud_skips_dns_when_offline(self):
        from desktop.payments.cloud_client import PaymentsCloudClient

        client = PaymentsCloudClient('https://payments.mugobyte.com')
        with mock.patch(
            'backend.cloud.net_gate.network_up', return_value=False
        ), mock.patch(
            'urllib.request.urlopen',
            side_effect=AssertionError('must not hit payments host when offline'),
        ):
            t0 = time.time()
            out = client._request('GET', '/health')
            self.assertLess(time.time() - t0, 0.5)
        self.assertFalse(out.get('ok'))
        self.assertEqual(out.get('error_code'), 'NETWORK')


if __name__ == '__main__':
    unittest.main()
