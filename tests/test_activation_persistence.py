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
        self.devices = []

    def _rows(self, table, query):
        if table == 'licenses':
            if 'MBT-TRI-TEST' in query or 'id=eq.L1' in query:
                return [dict(self.licenses['LIC1'])]
            return []
        if table == 'devices':
            out = []
            for row in self.devices:
                if 'device_id=eq.' in query:
                    want = query.split('device_id=eq.')[1].split('&')[0]
                    from urllib.parse import unquote
                    if row.get('device_id') != unquote(want):
                        continue
                if 'hardware_fingerprint=eq.' in query:
                    want = query.split('hardware_fingerprint=eq.')[1].split('&')[0]
                    from urllib.parse import unquote
                    if row.get('hardware_fingerprint') != unquote(want):
                        continue
                out.append(dict(row))
            return out
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
        if table == 'licenses':
            self.licenses['LIC1'].update(patch)

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

    def test_new_mbc_pc_id_matches_via_hardware_fingerprint(self):
        s = _FakeLicenseServer()
        hw = 'c' * 40
        s.devices = [{'device_id': 'MBT-PC-52E5', 'hardware_fingerprint': hw}]
        ok, msg, _ = s.activate('MBT-TRI-TEST', 'MBT-PC-52E5', 'org1')
        self.assertTrue(ok, msg)
        ok2, msg2, _ = s.activate(
            'MBT-TRI-TEST', 'MBT-PC-DEAD', 'org1',
            device_aliases=[hw],
        )
        self.assertTrue(ok2, msg2)
        self.assertIn('already', msg2.lower())
        self.assertEqual(s.licenses['LIC1']['activated_devices'], 1)

    def test_reserved_old_mbt_pc_allows_new_id_via_fingerprint(self):
        s = _FakeLicenseServer()
        hw = 'd' * 40
        s.licenses['LIC1']['reserved_device_id'] = 'MBT-PC-52E5'
        s.licenses['LIC1']['claim_status'] = 'reserved'
        s.devices = [{'device_id': 'MBT-PC-52E5', 'hardware_fingerprint': hw}]
        ok, msg, _ = s.activate(
            'MBT-TRI-TEST', 'MBT-PC-DEAD', 'org1',
            device_aliases=[hw],
        )
        self.assertTrue(ok, msg)
        self.assertEqual(s.licenses['LIC1']['activated_devices'], 1)

    def test_assign_does_not_demote_claimed(self):
        s = _FakeLicenseServer()
        s.activate('MBT-TRI-TEST', 'MBT-PC-52E5', 'org1')
        s.licenses['LIC1']['claim_status'] = 'claimed'
        s.licenses['LIC1']['reserved_device_id'] = 'MBT-PC-52E5'
        ok, msg, row = s.assign_license(
            'L1', assigned_email='edmus.cloud@gmail.com',
        )
        self.assertTrue(ok, msg)
        self.assertEqual(row['claim_status'], 'claimed')
        self.assertEqual(s.licenses['LIC1']['claim_status'], 'claimed')

    def test_assign_rejects_email_without_at(self):
        s = _FakeLicenseServer()
        ok, msg, _ = s.assign_license('L1', assigned_email='not-an-email')
        self.assertFalse(ok)
        self.assertIn('email', msg.lower())


class EmailClaimReuseTests(unittest.TestCase):
    def test_pick_license_reuses_full_seat_on_same_device(self):
        from licensing.cloud_onboarding import _pick_license

        lic = {
            'status': 'active',
            'assigned_email': 'edmus.cloud@gmail.com',
            'reserved_device_id': 'MBT-PC-52E5',
            'activated_devices': 1,
            'max_devices': 1,
            'license_key': 'MBT-TRI-KEEP',
        }
        chosen = _pick_license(
            [lic],
            '50057578b04c341371688631804b222466e7fde8',
            identity_email='edmus.cloud@gmail.com',
            aliases=['MBT-PC-52E5'],
        )
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen['license_key'], 'MBT-TRI-KEEP')

    def test_claim_full_seat_remirrors_same_device(self):
        from backend.cloud import platform_service as ps

        class _Srv:
            def find_licenses_for_email(self, email, org_id=None, product_id=None):
                return [{
                    'id': 'L1',
                    'license_key': 'MBT-TRI-KEEP',
                    'status': 'active',
                    'org_id': 'org-edmus',
                    'assigned_email': email,
                    'reserved_device_id': 'MBT-PC-52E5',
                    'activated_devices': 1,
                    'max_devices': 1,
                    'product_id': 'mbt-pos',
                }]

            def _activation_device_ids(self, device_id, aliases):
                ids = []
                for raw in (device_id, *(aliases or [])):
                    if raw and raw not in ids:
                        ids.append(raw)
                return ids

            def _expand_device_aliases(self, ids):
                return list(ids)

            def _find_active_activation(self, license_id, ids):
                return {'id': 'A1', 'device_id': 'MBT-PC-52E5'}

        captured = {}

        def _activate(key, device_id, org_id=None, **kw):
            captured['key'] = key
            return {'ok': True, 'license': {'license_key': key, 'org_id': org_id}}

        with patch.object(ps, 'get_license_server', return_value=_Srv()), \
             patch.object(ps, 'activate_license_on_device', side_effect=_activate):
            result = ps.claim_license_for_identity(
                email='edmus.cloud@gmail.com',
                device_id='MBT-PC-52E5',
            )
        self.assertTrue(result.get('ok'))
        self.assertEqual(captured['key'], 'MBT-TRI-KEEP')

    def test_claim_full_seat_other_device_rejected(self):
        from backend.cloud import platform_service as ps
        from backend.cloud_backup.supabase_client import SupabaseError

        class _FullOther:
            def find_licenses_for_email(self, email, org_id=None, product_id=None):
                return [{
                    'id': 'L1',
                    'license_key': 'MBT-TRI-KEEP',
                    'status': 'active',
                    'reserved_device_id': 'MBT-PC-52E5',
                    'activated_devices': 1,
                    'max_devices': 1,
                    'product_id': 'mbt-pos',
                }]

            def _activation_device_ids(self, device_id, aliases):
                return [device_id]

            def _expand_device_aliases(self, ids):
                return list(ids)

            def _find_active_activation(self, license_id, ids):
                return None

        with patch.object(ps, 'get_license_server', return_value=_FullOther()):
            with self.assertRaises(SupabaseError) as ctx:
                ps.claim_license_for_identity(
                    email='edmus.cloud@gmail.com',
                    device_id='MBT-PC-OTHER',
                )
        self.assertIn('no free device seat', str(ctx.exception).lower())


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

    def test_pro_narrow_square_rebalance(self):
        from desktop.pos.layouts.splitters import (
            NARROW_SHELL, _mins_for, default_sizes, LAYOUT_CHECKOUT_PRO,
        )
        avail = 992
        self.assertLessEqual(avail, NARROW_SHELL)
        mins = _mins_for(LAYOUT_CHECKOUT_PRO, 3, avail)
        self.assertEqual(sum(mins), avail)
        self.assertGreater(mins[2], mins[0])  # pay rail ≥ catalog on square
        sizes = default_sizes(LAYOUT_CHECKOUT_PRO, avail, 3)
        self.assertEqual(sum(sizes), avail)
        self.assertGreaterEqual(sizes[2], int(avail * 0.30))


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
