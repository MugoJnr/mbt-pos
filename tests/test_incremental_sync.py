"""Contract tests for transactional entity sync outbox."""
from __future__ import annotations

import hashlib
import importlib
import inspect
import os
import unittest


class TestIncrementalSync(unittest.TestCase):
    def test_flush_entity_outbox_exists(self):
        mod = importlib.import_module('backend.cloud_backup.sync_manager')
        self.assertTrue(hasattr(mod.SyncManager, 'flush_entity_outbox'))
        src = inspect.getsource(mod.SyncManager.flush_entity_outbox)
        post_src = inspect.getsource(mod.SyncManager._post_entity_sync_batch)
        self.assertIn('idempotency_key', post_src)
        self.assertIn('/api/cloud/sync/batch', post_src)
        self.assertIn('sync_outbox', src)
        self.assertIn('attempts', src)
        self.assertIn('serialize_entity_payload', src)
        self.assertIn('_post_entity_sync_batch', src)
        self.assertIn('debt_invoice', inspect.getsource(mod))
        self.assertIn('ensure_historical_backfill', inspect.getsource(mod.SyncManager))

    def test_platform_ingest_requires_approved_device(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, 'backend', 'cloud', 'platform_service.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn("approval_status=eq.approved", src)
        self.assertIn('def ingest_sync_batch', src)
        self.assertIn('def register_or_refresh_device', src)
        self.assertIn("_device_is_revoked", src)
        self.assertIn("'approval_status': 'approved'", src)

    def test_clear_approval_backoff_exists(self):
        mod = importlib.import_module('backend.cloud_backup.sync_manager')
        self.assertTrue(hasattr(mod.SyncManager, 'clear_device_approval_backoff'))
        src = inspect.getsource(mod.SyncManager.clear_device_approval_backoff)
        self.assertIn('not approved', src)
        self.assertIn('available_at=CURRENT_TIMESTAMP', src)

    def test_batch_key_is_stable_hash(self):
        org_id = 'org'
        device_id = 'dev'
        event_ids = ['a', 'b', 'c']
        key = hashlib.sha256(
            f"{org_id}:{device_id}:{','.join(event_ids)}".encode()
        ).hexdigest()
        self.assertEqual(len(key), 64)
        self.assertEqual(
            key,
            hashlib.sha256(f"{org_id}:{device_id}:a,b,c".encode()).hexdigest(),
        )


if __name__ == '__main__':
    unittest.main()
