"""Activation persistence: same device must not consume extra seats."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.cloud.license_server import CloudLicenseServer


class _FakeLicenseServer(CloudLicenseServer):
    def __init__(self):
        super().__init__()
        self.licenses = {
            'LIC1': {
                'id': 'L1',
                'license_key': 'MBT-TRI-TEST',
                'plan': 'trial',
                'status': 'active',
                'max_devices': 1,
                'activated_devices': 0,
                'expires_at': None,
                'assigned_email': '',
                'reserved_device_id': '',
                'product_id': 'mbt-pos',
            }
        }
        self.activations = []
        self.updates = []

    def _rows(self, table, query):
        if table == 'licenses':
            if 'MBT-TRI-TEST' in query:
                return [dict(self.licenses['LIC1'])]
            return []
        if table == 'license_activations':
            out = []
            for row in self.activations:
                if row.get('license_id') != 'L1' or not row.get('is_active'):
                    continue
                if 'device_id=eq.' in query:
                    want = query.split('device_id=eq.')[1].split('&')[0]
                    from urllib.parse import unquote
                    want = unquote(want)
                    if row.get('device_id') != want:
                        continue
                out.append(dict(row))
            return out
        return []

    def _insert(self, table, row, **_kw):
        if table == 'license_activations':
            self.activations.append(dict(row))

    def _update(self, table, query, patch):
        self.updates.append((table, query, dict(patch)))
        if table == 'licenses' and 'activated_devices' in patch:
            self.licenses['LIC1']['activated_devices'] = patch['activated_devices']

    def _log_history(self, *a, **k):
        pass


class ActivationSeatTests(unittest.TestCase):
    def test_same_device_second_activate_does_not_increment(self):
        s = _FakeLicenseServer()
        ok, msg, _ = s.activate('MBT-TRI-TEST', 'MBT-PC-AAAA', 'org1')
        self.assertTrue(ok, msg)
        self.assertEqual(s.licenses['LIC1']['activated_devices'], 1)
        ok2, msg2, _ = s.activate('MBT-TRI-TEST', 'MBT-PC-AAAA', 'org1')
        self.assertTrue(ok2, msg2)
        self.assertIn('already', msg2.lower())
        self.assertEqual(s.licenses['LIC1']['activated_devices'], 1)
        self.assertEqual(len(s.activations), 1)

    def test_hardware_alias_reuses_seat(self):
        s = _FakeLicenseServer()
        hw = 'a' * 40
        ok, msg, _ = s.activate('MBT-TRI-TEST', hw, 'org1')
        self.assertTrue(ok, msg)
        ok2, msg2, _ = s.activate(
            'MBT-TRI-TEST', 'MBT-PC-NEW1', 'org1',
            device_aliases=[hw],
        )
        self.assertTrue(ok2, msg2)
        self.assertIn('already', msg2.lower())
        self.assertEqual(s.licenses['LIC1']['activated_devices'], 1)

    def test_second_physical_device_blocked_at_max(self):
        s = _FakeLicenseServer()
        s.activate('MBT-TRI-TEST', 'DEV-A', 'org1')
        ok, msg, _ = s.activate('MBT-TRI-TEST', 'DEV-B', 'org1')
        self.assertFalse(ok)
        self.assertIn('limit', msg.lower())


class SplitterScaleTests(unittest.TestCase):
    def test_pro_mins_scale_below_960(self):
        from desktop.pos.layouts.splitters import _mins_for, LAYOUT_CHECKOUT_PRO
        wide = _mins_for(LAYOUT_CHECKOUT_PRO, 3, 1200)
        self.assertEqual(sum(wide), 960)
        narrow = _mins_for(LAYOUT_CHECKOUT_PRO, 3, 720)
        self.assertLessEqual(sum(narrow), 720)
        self.assertGreaterEqual(narrow[1], 220)
        self.assertGreaterEqual(narrow[2], 200)
        self.assertEqual(sum(narrow), 720)

    def test_default_sizes_fit_1024_shell(self):
        from desktop.pos.layouts.splitters import default_sizes, LAYOUT_CHECKOUT_PRO
        sizes = default_sizes(LAYOUT_CHECKOUT_PRO, 800, 3)
        self.assertEqual(sum(sizes), 800)
        self.assertTrue(all(s > 0 for s in sizes))


class RestartPersistenceTests(unittest.TestCase):
    def test_local_license_survives_new_engine(self):
        import os
        import tempfile
        from unittest.mock import patch
        from licensing import license_engine as le

        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db = os.path.join(tmp.name, 'lc.db')
        did = 'b' * 40
        patches = [
            patch.object(le, '_hidden_db_path', return_value=db),
            patch.object(le, 'resolve_device_id', return_value=did),
            patch.object(le, '_get_device_fingerprint', return_value=did),
            patch.object(le, '_read_cached_device_id', return_value=did),
        ]
        for p in patches:
            p.start()
        try:
            e1 = le.LicenseEngine()
            ok, msg = e1.activate_from_cloud(plan='pro', duration_days=365, license_key='MBT-PRO-X')
            self.assertTrue(ok, msg)
            e2 = le.LicenseEngine()
            self.assertTrue(e2.is_valid)
            self.assertNotEqual(e2.state, le.STATE_UNACTIVATED)
        finally:
            for p in patches:
                p.stop()
            tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
