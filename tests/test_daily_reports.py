"""
Unit tests for Automatic Daily Reports queue + idempotency.

Telegram delivery has been permanently removed. These tests cover the
filesystem queue that now feeds Portal / email report delivery.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestDailyReportQueue(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = os.path.join(self._tmpdir.name, 'data')
        os.makedirs(self._data, exist_ok=True)
        self._patches = [
            patch('backend.daily_report_queue.get_data_dir', return_value=self._data),
            patch('mbt_paths.get_data_dir', return_value=self._data),
        ]
        for p in self._patches:
            p.start()
        import backend.daily_report_queue as q
        q.init_db()
        self.q = q
        self.bkey = 'shop:test-shop'

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()

    def test_enqueue_idempotent_sent(self):
        today = str(date.today())
        r1 = self.q.enqueue(self.bkey, today, self.q.TYPE_DAILY, reason='t1')
        self.assertEqual(r1['status'], self.q.STATUS_PENDING)
        self.q.mark_sent(r1['id'], '/tmp/r.xlsx')
        r2 = self.q.enqueue(self.bkey, today, self.q.TYPE_DAILY, reason='t2')
        self.assertEqual(r2['status'], self.q.STATUS_SENT)
        self.assertTrue(self.q.is_sent(self.bkey, today))

    def test_claim_pending_to_sending(self):
        d = str(date.today() - timedelta(days=1))
        self.q.enqueue(self.bkey, d, reason='catchup')
        claimed = self.q.claim_next(self.bkey, self.q.TYPE_DAILY)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed['status'], self.q.STATUS_SENDING)
        self.assertEqual(claimed['attempts'], 1)
        again = self.q.claim_next(self.bkey, self.q.TYPE_DAILY)
        self.assertIsNone(again)

    def test_mark_failed_retries_then_exhausted(self):
        d = str(date.today())
        self.q.enqueue(self.bkey, d)
        claimed = self.q.claim_next(self.bkey)
        st = self.q.mark_failed(claimed['id'], 'offline', retry=True)
        self.assertEqual(st, self.q.STATUS_RETRYING)
        for _ in range(self.q.MAX_ATTEMPTS):
            c = self.q.claim_next(self.bkey)
            if not c:
                break
            self.q.mark_failed(c['id'], 'fail', retry=True)
        final = self.q.get_row(self.bkey, d)
        self.assertIn(final['status'], (self.q.STATUS_FAILED, self.q.STATUS_RETRYING))
        if final['attempts'] >= self.q.MAX_ATTEMPTS:
            self.assertEqual(final['status'], self.q.STATUS_FAILED)

    def test_catchup_enqueues_missing_days(self):
        rows = self.q.enqueue_catchup(self.bkey, days=3, include_today=True)
        self.assertGreaterEqual(len(rows), 1)
        dates = {r['report_date'] for r in rows}
        self.assertIn(str(date.today()), dates)

    def test_one_sent_per_business_date(self):
        today = str(date.today())
        a = self.q.enqueue('shop:a', today)
        b = self.q.enqueue('shop:b', today)
        self.q.mark_sent(a['id'])
        self.q.mark_sent(b['id'])
        self.assertTrue(self.q.is_sent('shop:a', today))
        self.assertTrue(self.q.is_sent('shop:b', today))
        again = self.q.enqueue('shop:a', today)
        self.assertEqual(again['status'], self.q.STATUS_SENT)

    def test_no_telegram_reporter_module(self):
        import importlib.util
        self.assertIsNone(importlib.util.find_spec('backend.telegram_reporter'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
