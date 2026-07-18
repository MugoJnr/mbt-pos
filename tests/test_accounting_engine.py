"""Unit tests for double-entry journal balance + COA seed."""
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from desktop.utils.accounting_engine import (
    ensure_accounting_schema, post_journal, reverse_journal,
    UnbalancedJournalError, trial_balance, profit_and_loss,
    find_posted_entry, list_accounts,
)


class AccountingEngineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self._tmp.close()
        self.conn = sqlite3.connect(self._tmp.name)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT)"
        )
        self.conn.execute(
            "INSERT INTO system_settings (key,value) VALUES ('currency_code','KES')"
        )
        ensure_accounting_schema(self.conn)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        try:
            os.unlink(self._tmp.name)
        except Exception:
            pass

    def test_coa_seeded(self):
        accts = list_accounts(self.conn)
        codes = {a['code'] for a in accts}
        for required in ('1000', '1100', '1200', '4000', '5000', '6100'):
            self.assertIn(required, codes)

    def test_rejects_unbalanced(self):
        with self.assertRaises(UnbalancedJournalError):
            post_journal(
                self.conn,
                [
                    {'account_code': '1000', 'debit': 100},
                    {'account_code': '4000', 'credit': 90},
                ],
                description='bad',
                source_module='test',
                source_id='1',
                entry_type='test',
            )

    def test_balanced_post_and_idempotent(self):
        r1 = post_journal(
            self.conn,
            [
                {'account_code': '1000', 'debit': 250},
                {'account_code': '4000', 'credit': 250},
            ],
            description='Cash sale',
            source_module='sales',
            source_id='99',
            entry_type='sale',
            username='tester',
        )
        self.conn.commit()
        self.assertTrue(r1.get('success'))
        self.assertEqual(r1['total_debit'], 250.0)
        self.assertEqual(r1['total_credit'], 250.0)
        r2 = post_journal(
            self.conn,
            [
                {'account_code': '1000', 'debit': 250},
                {'account_code': '4000', 'credit': 250},
            ],
            description='Cash sale again',
            source_module='sales',
            source_id='99',
            entry_type='sale',
        )
        self.assertTrue(r2.get('idempotent'))
        self.assertEqual(r1['journal_id'], r2['journal_id'])

    def test_reverse_balances_to_zero(self):
        r = post_journal(
            self.conn,
            [
                {'account_code': '6100', 'debit': 40},
                {'account_code': '1200', 'credit': 40},
            ],
            description='Consumption',
            source_module='consumption',
            source_id='7',
            entry_type='consumption',
        )
        rev = reverse_journal(
            self.conn, r['journal_id'], reason='void',
            source_module='consumption', source_id='7',
            entry_type='consumption_void',
        )
        self.conn.commit()
        self.assertTrue(rev.get('success'))
        tb = trial_balance(self.conn)
        self.assertTrue(tb['balanced'])
        # Net on 6100 should be zero
        from desktop.utils.accounting_engine import account_activity
        act = account_activity(self.conn, '6100')
        self.assertEqual(act['balance'], 0.0)

    def test_pnl_reflects_sale(self):
        post_journal(
            self.conn,
            [
                {'account_code': '1000', 'debit': 1000},
                {'account_code': '4000', 'credit': 1000},
                {'account_code': '5000', 'debit': 400},
                {'account_code': '1200', 'credit': 400},
            ],
            description='Sale+COGS',
            source_module='sales',
            source_id='1',
            entry_type='sale',
        )
        self.conn.commit()
        pl = profit_and_loss(self.conn)
        self.assertEqual(pl['total_income'], 1000.0)
        self.assertEqual(pl['total_cogs'], 400.0)
        self.assertEqual(pl['gross_profit'], 600.0)
        self.assertEqual(pl['net_profit'], 600.0)


if __name__ == '__main__':
    unittest.main()
