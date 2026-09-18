"""v3.0.93 cloud hang resilience — circuit breaker + stale state migration."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch


class CircuitBreakerTests(unittest.TestCase):
    def test_backoff_opens(self):
        from backend.cloud.circuit_breaker import CircuitBreaker
        br = CircuitBreaker('t', backoff=(1, 2, 5), open_after=2)
        self.assertTrue(br.allow())
        w1 = br.record_failure()
        self.assertEqual(w1, 1)
        self.assertFalse(br.allow())
        # Force next window
        br._next_allowed = 0
        br.record_failure()
        self.assertTrue(br.is_open)
        br.record_success()
        self.assertFalse(br.is_open)
        self.assertTrue(br.allow())


class StaleCloudStateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self._td.name, 'cloud_config.json')
        self.state = os.path.join(self._td.name, 'cloud_backup_state.json')
        self.queue = os.path.join(self._td.name, 'cloud_offline_queue.json')
        with open(self.cfg, 'w', encoding='utf-8') as f:
            json.dump({
                'enabled': True,
                'supabase_url': 'https://mxfvbylmlynotvghnzqg.supabase.co',
                'project_ref': 'mxfvbylmlynotvghnzqg',
                'anon_key': 'x',
            }, f)
        with open(self.state, 'w', encoding='utf-8') as f:
            json.dump({
                'last_storage_path': 'https://uynfglgttkaibyeglsrt.supabase.co/storage/v1/x',
                'last_error': 'Failed host uynfglgttkaibyeglsrt.supabase.co',
            }, f)
        with open(self.queue, 'w', encoding='utf-8') as f:
            json.dump({
                'items': [
                    {
                        'type': 'backup_meta',
                        'storage_path': 'biz/dev/old.mbtenc',
                        'local_enc_path': '/tmp/x.mbtenc',
                        'meta': {
                            'supabase_url': 'https://uynfglgttkaibyeglsrt.supabase.co',
                            'project_ref': 'uynfglgttkaibyeglsrt',
                        },
                    },
                    {
                        'type': 'backup_meta',
                        'storage_path': 'biz/dev/latest.mbtenc',
                        'local_enc_path': '/tmp/y.mbtenc',
                        'meta': {
                            'supabase_url': 'https://mxfvbylmlynotvghnzqg.supabase.co',
                            'project_ref': 'mxfvbylmlynotvghnzqg',
                        },
                    },
                ]
            }, f)

    def tearDown(self):
        self._td.cleanup()

    def test_sanitize_drops_retired_queue_and_state(self):
        from backend.cloud_backup import migrate_stale_state as m
        with patch.object(m, 'active_supabase_host', return_value='mxfvbylmlynotvghnzqg.supabase.co'), \
             patch.object(m, 'offline_queue_path', return_value=self.queue), \
             patch.object(m, 'backup_state_path', return_value=self.state), \
             patch.object(m, 'load_json', side_effect=lambda p, d=None: (
                 json.load(open(p, encoding='utf-8')) if os.path.isfile(p) else (d or {})
             )), \
             patch.object(m, 'save_json', side_effect=lambda p, data: (
                 json.dump(data, open(p, 'w', encoding='utf-8'), indent=2)
             )):
            report = m.sanitize_stale_cloud_state()
        self.assertFalse(report['already_clean'])
        self.assertGreaterEqual(report['queue_abandoned'], 1)
        q = json.load(open(self.queue, encoding='utf-8'))
        self.assertEqual(len(q['items']), 1)
        self.assertIn('mxfvbylmlynotvghnzqg', q['items'][0]['meta']['supabase_url'])
        st = json.load(open(self.state, encoding='utf-8'))
        self.assertEqual(st.get('last_storage_path'), '')
        self.assertTrue(st.get('stale_project_migrated_at'))

    def test_dead_optional_hosts(self):
        from backend.cloud_backup.migrate_stale_state import is_stale_cloud_target
        self.assertTrue(is_stale_cloud_target('https://api.mugobyte.com/v1'))
        self.assertTrue(is_stale_cloud_target('https://licensing.mugobyte.com'))


class InternetMonitorDefaults(unittest.TestCase):
    def test_fail_fast_hosts(self):
        from backend.internet_monitor import CHECK_HOSTS, CONNECT_TIMEOUT
        self.assertEqual(len(CHECK_HOSTS), 2)
        self.assertLessEqual(CONNECT_TIMEOUT, 1.5)


if __name__ == '__main__':
    unittest.main()
