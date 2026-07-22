"""Focused tests for automatic device approval and revoked-device blocking."""
from __future__ import annotations

import importlib
import unittest
from unittest import mock


class TestDeviceAutoOnboarding(unittest.TestCase):
    def setUp(self):
        self.ps = importlib.import_module('backend.cloud.platform_service')

    def test_new_device_is_auto_approved(self):
        inserted = {}

        def _insert(table, row, **_kwargs):
            self.assertEqual(table, 'devices')
            self.assertEqual(row.get('approval_status'), 'approved')
            self.assertTrue(row.get('is_active'))
            inserted.update(row)
            return {**row, 'id': 'dev-uuid-1'}

        with mock.patch.object(self.ps, '_find_org_device', return_value=None), \
             mock.patch.object(self.ps, 'service_insert', side_effect=_insert), \
             mock.patch.object(self.ps, '_log_device_event'), \
             mock.patch.dict('sys.modules', {'backend.cloud.notification_engine': mock.Mock()}):
            row = self.ps.register_or_refresh_device(
                'org-1',
                device_id='pc-aaa',
                business_id='biz-1',
                computer_name='Front Desk',
                actor_user_id='user-1',
            )
        self.assertEqual(row['approval_status'], 'approved')
        self.assertEqual(inserted['approval_status'], 'approved')
        self.assertTrue(row['is_active'])

    def test_pending_device_is_auto_approved_on_refresh(self):
        existing = {
            'id': 'dev-uuid-2',
            'org_id': 'org-1',
            'device_id': 'pc-bbb',
            'approval_status': 'pending',
            'is_active': True,
        }
        updates = []

        def _update(_table, _query, patch):
            updates.append(patch)
            return patch

        with mock.patch.object(self.ps, '_find_org_device', return_value=existing), \
             mock.patch.object(self.ps, 'service_update', side_effect=_update), \
             mock.patch.object(self.ps, '_log_device_event') as log_event:
            row = self.ps.register_or_refresh_device(
                'org-1',
                device_id='pc-bbb',
                actor_user_id='user-1',
            )
        self.assertEqual(row['approval_status'], 'approved')
        self.assertEqual(updates[0]['approval_status'], 'approved')
        self.assertTrue(updates[0]['is_active'])
        self.assertEqual(log_event.call_args.args[2], 'approved')

    def test_rejected_device_remains_blocked(self):
        existing = {
            'id': 'dev-uuid-3',
            'org_id': 'org-1',
            'device_id': 'pc-ccc',
            'approval_status': 'rejected',
            'is_active': False,
        }
        updates = []

        def _update(_table, _query, patch):
            updates.append(patch)
            return patch

        with mock.patch.object(self.ps, '_find_org_device', return_value=existing), \
             mock.patch.object(self.ps, 'service_update', side_effect=_update), \
             mock.patch.object(self.ps, '_log_device_event'):
            row = self.ps.register_or_refresh_device(
                'org-1',
                device_id='pc-ccc',
                computer_name='Stolen Laptop',
                actor_user_id='user-1',
            )
        self.assertEqual(row['approval_status'], 'rejected')
        self.assertFalse(row['is_active'])
        self.assertNotIn('approval_status', updates[0])
        self.assertNotIn('is_active', updates[0])
        self.assertEqual(updates[0].get('computer_name'), 'Stolen Laptop')

    def test_deactivated_device_remains_blocked(self):
        existing = {
            'id': 'dev-uuid-4',
            'org_id': 'org-1',
            'device_id': 'pc-ddd',
            'approval_status': 'deactivated',
            'is_active': False,
        }
        updates = []

        with mock.patch.object(self.ps, '_find_org_device', return_value=existing), \
             mock.patch.object(self.ps, 'service_update', side_effect=lambda *_a, **_k: updates.append(_a[2]) or _a[2]), \
             mock.patch.object(self.ps, '_log_device_event'):
            row = self.ps.register_or_refresh_device(
                'org-1',
                device_id='pc-ddd',
                actor_user_id='user-1',
            )
        self.assertEqual(row['approval_status'], 'deactivated')
        self.assertFalse(row['is_active'])
        self.assertNotIn('approval_status', updates[0])

    def test_verify_org_access_is_enforced_when_requested(self):
        with mock.patch.object(
            self.ps, 'require_org_access', side_effect=PermissionError('denied')
        ) as require_access:
            with self.assertRaises(PermissionError):
                self.ps.register_or_refresh_device(
                    'org-1',
                    device_id='pc-eee',
                    actor_user_id='user-x',
                    verify_org_access=True,
                )
        require_access.assert_called_once()

    def test_device_is_revoked_helper(self):
        self.assertTrue(self.ps._device_is_revoked({'approval_status': 'rejected'}))
        self.assertTrue(self.ps._device_is_revoked({'approval_status': 'deactivated'}))
        self.assertFalse(self.ps._device_is_revoked({'approval_status': 'approved'}))
        self.assertFalse(self.ps._device_is_revoked({'approval_status': 'pending'}))
        self.assertFalse(self.ps._device_is_revoked(None))


class TestAuthServiceKickoffContracts(unittest.TestCase):
    def test_register_path_kicks_off_analytics_after_approval(self):
        auth = importlib.import_module('backend.cloud_backup.auth_service')
        with open(auth.__file__, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('_kickoff_analytics_after_registration', src)
        self.assertIn('clear_device_approval_backoff', src)
        self.assertIn('ensure_historical_backfill', src)
        self.assertIn('verify_org_access=True', src)


if __name__ == '__main__':
    unittest.main()
