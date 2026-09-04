"""Regression: period filters must not sum journal lines from outside the range.

The aggregate reports joined journal_lines by account and LEFT JOINed the
filtered journal_entries, so out-of-period lines survived with NULL entries and
were still summed — an empty period reported the full all-time figure.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from desktop.utils.accounting_engine import (
    ensure_accounting_schema, post_journal, trial_balance, profit_and_loss,
    balance_sheet,
)


class AccountingPeriodFilterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self._tmp.close()
        self.conn = sqlite3.connect(self._tmp.name)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT)")
        self.conn.execute(
            "INSERT INTO system_settings (key,value) VALUES ('currency_code','KES')")
        ensure_accounting_schema(self.conn)
        # One sale + COGS posted on 2020-06-15 only.
        post_journal(
            self.conn,
            [
                {'account_code': '1000', 'debit': 1000},
                {'account_code': '4000', 'credit': 1000},
                {'account_code': '5000', 'debit': 400},
                {'account_code': '1200', 'credit': 400},
            ],
            description='Historic sale',
            entry_date='2020-06-15',
            source_module='sales',
            source_id='hist-1',
            entry_type='sale',
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_pnl_empty_period_is_zero(self):
        pl = profit_and_loss(self.conn, '2021-01-01', '2021-12-31')
        self.assertEqual(pl['total_income'], 0.0)
        self.assertEqual(pl['total_cogs'], 0.0)
        self.assertEqual(pl['total_expenses'], 0.0)
        self.assertEqual(pl['net_profit'], 0.0)
        self.assertEqual(pl['income'], [])

    def test_pnl_period_before_data_is_zero(self):
        pl = profit_and_loss(self.conn, '2019-01-01', '2019-12-31')
        self.assertEqual(pl['total_income'], 0.0)
        self.assertEqual(pl['total_cogs'], 0.0)

    def test_pnl_covering_period_sees_data(self):
        pl = profit_and_loss(self.conn, '2020-01-01', '2020-12-31')
        self.assertEqual(pl['total_income'], 1000.0)
        self.assertEqual(pl['total_cogs'], 400.0)
        self.assertEqual(pl['gross_profit'], 600.0)

    def test_pnl_single_day_boundaries(self):
        exact = profit_and_loss(self.conn, '2020-06-15', '2020-06-15')
        self.assertEqual(exact['total_income'], 1000.0)
        day_before = profit_and_loss(self.conn, '2020-06-14', '2020-06-14')
        self.assertEqual(day_before['total_income'], 0.0)
        day_after = profit_and_loss(self.conn, '2020-06-16', '2020-06-16')
        self.assertEqual(day_after['total_income'], 0.0)

    def test_trial_balance_empty_window_has_no_accounts(self):
        tb = trial_balance(self.conn, as_of='2021-12-31', start='2021-01-01')
        self.assertEqual(tb['accounts'], [])
        self.assertEqual(tb['total_debit'], 0.0)
        self.assertEqual(tb['total_credit'], 0.0)

    def test_trial_balance_covering_window_balances(self):
        tb = trial_balance(self.conn, as_of='2020-12-31', start='2020-01-01')
        self.assertTrue(tb['balanced'])
        self.assertEqual(tb['total_debit'], tb['total_credit'])
        self.assertGreater(tb['total_debit'], 0.0)

    def test_balance_sheet_before_data_is_zero(self):
        bs = balance_sheet(self.conn, as_of='2019-12-31')
        self.assertEqual(bs['total_assets'], 0.0)
        self.assertEqual(bs['total_liabilities'], 0.0)
        self.assertEqual(bs['total_equity'], 0.0)

    def test_unposted_entry_is_excluded_from_reports(self):
        self.conn.execute(
            "UPDATE journal_entries SET status='draft' WHERE source_id='hist-1'")
        self.conn.commit()
        pl = profit_and_loss(self.conn, '2020-01-01', '2020-12-31')
        self.assertEqual(pl['total_income'], 0.0)
        bs = balance_sheet(self.conn, as_of='2020-12-31')
        self.assertEqual(bs['total_assets'], 0.0)

    def test_soft_deleted_entry_is_excluded_from_reports(self):
        self.conn.execute(
            "UPDATE journal_entries SET deleted_at='2020-07-01' "
            "WHERE source_id='hist-1'")
        self.conn.commit()
        pl = profit_and_loss(self.conn, '2020-01-01', '2020-12-31')
        self.assertEqual(pl['total_income'], 0.0)
        tb = trial_balance(self.conn, as_of='2020-12-31')
        self.assertEqual(tb['accounts'], [])


if __name__ == '__main__':
    unittest.main()
