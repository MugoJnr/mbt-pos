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

    def test_launcher_skips_wall_when_initialized(self):
        import launcher
        from licensing.license_engine import LicenseEngine
        from mbt_paths import get_project_root, get_init_flag_path

        eng = LicenseEngine(get_project_root())
        if not (os.path.exists(get_init_flag_path()) or eng.has_local_license_payload()):
            self.skipTest('shop not initialized')
        eng.store.set('offline_lock', True)
        self.assertTrue(launcher._shop_already_ready(eng))


if __name__ == '__main__':
    unittest.main()
