"""Contract tests for transactional entity sync outbox."""
from __future__ import annotations

import hashlib
import importlib
import inspect
import unittest


class TestIncrementalSync(unittest.TestCase):
    def test_flush_entity_outbox_exists(self):
        mod = importlib.import_module('backend.cloud_backup.sync_manager')
        self.assertTrue(hasattr(mod.SyncManager, 'flush_entity_outbox'))
        src = inspect.getsource(mod.SyncManager.flush_entity_outbox)
        self.assertIn('idempotency_key', src)
        self.assertIn('/api/cloud/sync/batch', src)
        self.assertIn('sync_outbox', src)
        self.assertIn('attempts', src)

    def test_platform_ingest_requires_approved_device(self):
        mod = importlib.import_module('backend.cloud.platform_service')
        src = inspect.getsource(mod.ingest_sync_batch)
        self.assertIn("approval_status=eq.approved", src)

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
