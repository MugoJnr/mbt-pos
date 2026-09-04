"""Focused regressions for post-3.0.80 hygiene fixes."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock


class ShopTimeFallbackTests(unittest.TestCase):
    def test_shop_tzinfo_never_none(self):
        from desktop.utils.shop_time import shop_tzinfo

        tz = shop_tzinfo()
        self.assertIsNotNone(tz)
        now = datetime.now(tz)
        self.assertEqual(now.utcoffset(), timedelta(hours=3))

    def test_shop_now_uses_fixed_utc3_when_zoneinfo_missing(self):
        import desktop.utils.shop_time as st

        with mock.patch.object(st, 'shop_tzinfo', return_value=st._NAIROBI_FIXED):
            now = st.shop_now()
        self.assertEqual(now.utcoffset(), timedelta(hours=3))


class AppVersionStampTests(unittest.TestCase):
    def test_write_and_ensure_installed_version_stamp(self):
        from backend import app_version as av

        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, 'MugoByte', 'MBT POS')
            os.makedirs(root, exist_ok=True)
            with mock.patch.object(av, 'brand_data_root', return_value=root):
                with mock.patch.object(av, 'resolve_app_version', return_value='3.0.82'):
                    payload = av.write_installed_version_stamp('3.0.82', exe_path=r'C:\Program Files\MugoByte\MBT POS\MBT_POS.exe')
                    path = av.installed_version_path()
                    self.assertTrue(os.path.isfile(path))
                    data = json.loads(open(path, encoding='utf-8').read())
                    self.assertEqual(data['version'], '3.0.82')
                    self.assertEqual(payload['version'], '3.0.82')
                    # Same version → no rewrite needed
                    self.assertIsNone(av.ensure_installed_version_stamp('3.0.82'))
                    # Stale stamp → refresh
                    open(path, 'w', encoding='utf-8').write(json.dumps({'version': '3.0.75'}))
                    refreshed = av.ensure_installed_version_stamp('3.0.82')
                    self.assertEqual(refreshed['version'], '3.0.82')

    def test_resolve_app_version_skips_unknown(self):
        from backend import app_version as av

        with mock.patch.object(av, 'read_version_json', return_value='3.0.82'):
            with mock.patch.dict('sys.modules', {'desktop.main': mock.Mock(APP_VERSION='unknown')}):
                # Force import path that prefers version.json when APP_VERSION is unknown
                ver = av.resolve_app_version('unknown')
        self.assertEqual(ver, '3.0.82')


class DeviceVersionResolverTests(unittest.TestCase):
    def test_get_device_info_uses_resolver(self):
        from backend.cloud.device_service import DeviceService

        svc = DeviceService(lambda: {})
        with mock.patch(
            'backend.cloud_backup.device_manager.get_or_create_device_id',
            return_value='MBT-PC-TEST',
        ):
            with mock.patch('backend.cloud.device_service._safe_hostname', return_value='HOST'):
                with mock.patch('licensing.license_engine.LicenseEngine') as eng:
                    eng.return_value.device_id = 'fp'
                    with mock.patch('backend.app_version.resolve_app_version', return_value='3.0.82'):
                        info = svc.get_device_info()
        self.assertEqual(info['mbt_version'], '3.0.82')


class ListBackupsForOrgTests(unittest.TestCase):
    def test_scopes_to_org_businesses(self):
        from backend.cloud import platform_service as ps

        calls = []

        def fake_select(table, query='', **kwargs):
            calls.append((table, query))
            if table == 'businesses':
                return [{'id': 'biz-1', 'name': 'EDMUS'}]
            if table == 'backups':
                return [{
                    'id': 'bak-1',
                    'business_id': 'biz-1',
                    'device_id': 'MBT-PC-52E6',
                    'size_bytes': 10,
                    'status': 'ok',
                    'created_at': '2026-09-04T00:00:00Z',
                }]
            return []

        with mock.patch.object(ps, 'service_select', side_effect=fake_select):
            rows = ps.list_backups_for_org('org-1', limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['org_name'], 'EDMUS')
        self.assertEqual(rows[0]['business_name'], 'EDMUS')
        self.assertTrue(any(t == 'backups' for t, _ in calls))


class MarkInstallFinishedStampTests(unittest.TestCase):
    def test_success_writes_stamp(self):
        from backend import updater

        stamped = {}

        with mock.patch.object(updater, 'load_install_state', return_value={}):
            with mock.patch.object(updater, 'save_install_state'):
                with mock.patch('backend.app_version.write_installed_version_stamp', side_effect=lambda v, **k: stamped.setdefault('v', v)):
                    updater.mark_install_finished('3.0.82', True)
        self.assertEqual(stamped.get('v'), '3.0.82')


if __name__ == '__main__':
    unittest.main()
