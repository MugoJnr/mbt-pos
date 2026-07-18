"""
Unit tests for Automatic Daily Reports + Telegram queue/idempotency.

Run:
  python -m pytest tests/test_daily_reports.py -v
  python tests/test_daily_reports.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestDailyReportQueue(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = os.path.join(self._tmpdir.name, 'data')
        os.makedirs(self._data, exist_ok=True)
        # Point queue at temp data dir
        self._patches = [
            patch('backend.daily_report_queue.get_data_dir', return_value=self._data),
            patch('mbt_paths.get_data_dir', return_value=self._data),
        ]
        for p in self._patches:
            p.start()
        # Fresh module state
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
        # Second claim while SENDING should not reclaim same
        again = self.q.claim_next(self.bkey, self.q.TYPE_DAILY)
        self.assertIsNone(again)

    def test_mark_failed_retries_then_exhausted(self):
        d = str(date.today())
        row = self.q.enqueue(self.bkey, d)
        claimed = self.q.claim_next(self.bkey)
        st = self.q.mark_failed(claimed['id'], 'offline', retry=True)
        self.assertEqual(st, self.q.STATUS_RETRYING)
        # Exhaust attempts
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
        # Re-enqueue a does not clear SENT
        again = self.q.enqueue('shop:a', today)
        self.assertEqual(again['status'], self.q.STATUS_SENT)


class TestSchedulerSingleton(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = os.path.join(self._tmpdir.name, 'data')
        os.makedirs(self._data, exist_ok=True)
        self._patches = [
            patch('backend.daily_report_queue.get_data_dir', return_value=self._data),
        ]
        for p in self._patches:
            p.start()
        import backend.telegram_reporter as tr
        tr.stop_report_scheduler()
        self.tr = tr

    def tearDown(self):
        self.tr.stop_report_scheduler()
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()

    def test_duplicate_start_reuses_instance(self):
        api = MagicMock()
        cfg = lambda: {
            'telegram_bot_token': '',
            'telegram_chat_id': '',
            'auto_report_daily': '0',
            'shop_name': 'Dup Test',
        }
        s1 = self.tr.start_report_scheduler(api, cfg, is_online_getter=lambda: False)
        s2 = self.tr.start_report_scheduler(api, cfg, is_online_getter=lambda: False)
        self.assertIs(s1, s2)
        self.assertTrue(s1.is_alive())

    def test_config_validation_warns(self):
        warns = self.tr.validate_telegram_config({
            'auto_report_daily': '1',
            'telegram_bot_token': '',
            'telegram_chat_id': '',
        })
        self.assertTrue(any('token' in w.lower() or 'chat' in w.lower() for w in warns))


class TestOfflineQueueAndIdempotentSend(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = os.path.join(self._tmpdir.name, 'data')
        os.makedirs(self._data, exist_ok=True)
        self._patches = [
            patch('backend.daily_report_queue.get_data_dir', return_value=self._data),
        ]
        for p in self._patches:
            p.start()
        import backend.daily_report_queue as q
        import backend.telegram_reporter as tr
        q.init_db()
        tr.stop_report_scheduler()
        self.q = q
        self.tr = tr
        self.bkey = 'shop:offline-test'

    def tearDown(self):
        self.tr.stop_report_scheduler()
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()

    def test_offline_enqueue_then_send_when_online(self):
        """Simulate: enqueue while offline, deliver once online via _process_queue."""
        yesterday = str(date.today() - timedelta(days=1))
        self.q.enqueue(self.bkey, yesterday, reason='offline_buffer')
        self.assertFalse(self.q.is_sent(self.bkey, yesterday))

        api = MagicMock()
        api.get_sales.return_value = []
        cfg = {
            'telegram_bot_token': '123456789:AA-fake-token-for-unit-test-xxxx',
            'telegram_chat_id': '999',
            'shop_name': 'Offline Test',
            'currency_symbol': 'KES',
            'auto_report_daily': '1',
        }

        with patch.object(self.tr, '_deliver_range', return_value=(True, 'ok', 'x.xlsx')):
            sched = self.tr.ReportScheduler(
                api, lambda: cfg, is_online_getter=lambda: True,
            )
            # Bypass start thread — call process directly
            with patch(
                'backend.daily_report_queue.business_key_from_cfg',
                return_value=self.bkey,
            ):
                sched._process_queue(cfg, self.bkey)

        self.assertTrue(self.q.is_sent(self.bkey, yesterday))

        # Second process must not re-send
        send_calls = []

        def _track(*a, **k):
            send_calls.append(1)
            return True, 'ok', 'x.xlsx'

        with patch.object(self.tr, '_deliver_range', side_effect=_track):
            sched._process_queue(cfg, self.bkey)
        self.assertEqual(len(send_calls), 0)

    def test_token_redaction_in_helper(self):
        token = '1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw'
        redacted = self.tr._redact(
            f'https://api.telegram.org/bot{token}/sendDocument failed'
        )
        self.assertNotIn(token, redacted)
        self.assertIn('***', redacted)


class TestHealthSnapshot(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = os.path.join(self._tmpdir.name, 'data')
        os.makedirs(self._data, exist_ok=True)
        self._p = patch(
            'backend.daily_report_queue.get_data_dir', return_value=self._data,
        )
        self._p.start()
        import backend.daily_report_queue as q
        q.init_db()

    def tearDown(self):
        self._p.stop()
        self._tmpdir.cleanup()

    def test_health_has_required_keys(self):
        from backend.telegram_reporter import get_report_health, stop_report_scheduler
        stop_report_scheduler()
        h = get_report_health(lambda: {
            'shop_name': 'Health Shop',
            'telegram_chat_id': '',
            'auto_report_daily': '1',
        })
        for key in (
            'scheduler', 'telegram_connected', 'last_report_status',
            'delivery_pending', 'failed_attempts', 'config_warnings',
        ):
            self.assertIn(key, h)
        self.assertEqual(h['scheduler'], 'STOPPED')


if __name__ == '__main__':
    unittest.main(verbosity=2)
