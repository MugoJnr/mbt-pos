"""Heartbeat must use the business's org, not a stale identity org_id."""
from __future__ import annotations

import importlib
import unittest
from unittest import mock


class TestResolveCloudIds(unittest.TestCase):
    def test_stale_identity_org_yields_to_business_org(self):
        ds = importlib.import_module('backend.cloud.device_service')
        ident = {
            'business_id': 'biz-edmus',
            'org_id': 'org-my-business',
        }
        saved = []

        def _select(table, query, **_kwargs):
            self.assertEqual(table, 'businesses')
            self.assertIn('biz-edmus', query)
            return [{'id': 'biz-edmus', 'org_id': 'org-edmus'}]

        with mock.patch.object(ds, '_quick_online', return_value=True), \
             mock.patch('backend.cloud_backup.paths.load_identity', return_value=ident), \
             mock.patch('backend.cloud.platform_service.service_select', side_effect=_select), \
             mock.patch('backend.cloud_backup.paths.save_identity', side_effect=lambda i: saved.append(dict(i))):
            business_id, org_id = ds._resolve_cloud_ids()

        self.assertEqual(business_id, 'biz-edmus')
        self.assertEqual(org_id, 'org-edmus')
        self.assertEqual(saved[0]['org_id'], 'org-edmus')
