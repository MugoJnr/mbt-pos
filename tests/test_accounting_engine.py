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
        for required in ('1000', '1100', '1200', '4000', '5000', '6100', '3300'):
            self.assertIn(required, codes)
        from desktop.utils.accounting_engine import seed_chart_of_accounts
        again = seed_chart_of_accounts(self.conn)
        self.assertEqual(again, 0)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM chart_of_accounts WHERE code='3300'"
        ).fetchone()[0]
        self.assertEqual(count, 1)

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

    def test_consumption_reason_does_not_all_hit_operating_expense(self):
        from desktop.utils.accounting_hooks import post_consumption_journal
        self.conn.execute(
            """CREATE TABLE stock_consumptions (
                id INTEGER PRIMARY KEY,
                reference_no TEXT,
                date TEXT,
                reason TEXT,
                total_cost REAL
            )"""
        )
        rows = [
            (1, 'USE-1', 'Staff tea'),
            (2, 'USE-2', 'Damaged bags'),
            (3, 'USE-3', 'Expired milk'),
            (4, 'USE-4', 'Owner personal use'),
        ]
        for row_id, ref, reason in rows:
            self.conn.execute(
                "INSERT INTO stock_consumptions (id, reference_no, date, reason, total_cost) "
                "VALUES (?,?,?,?,?)",
                (row_id, ref, '2026-11-13', reason, 25),
            )
        self.conn.commit()
        for row_id in (1, 2, 3, 4):
            posted = post_consumption_journal(self.conn, row_id, safe=False)
            self.assertTrue(posted.get('success'), posted)
        codes = {}
        for row_id, _ref, _reason in rows:
            line = self.conn.execute(
                """SELECT jl.account_code FROM journal_lines jl
                   JOIN journal_entries je ON je.id = jl.journal_id
                   WHERE je.source_module='consumption' AND je.source_id=?
                     AND jl.debit > 0""",
                (str(row_id),),
            ).fetchone()
            codes[row_id] = line['account_code']
        self.assertEqual(codes[1], '6100')
        self.assertEqual(codes[2], '6200')
        self.assertEqual(codes[3], '6300')
        self.assertEqual(codes[4], '3300')
        from desktop.utils.accounting_hooks import reverse_consumption_journal
        from desktop.utils.accounting_engine import account_activity
        first = reverse_consumption_journal(self.conn, 4, reason='void owner', safe=False)
        second = reverse_consumption_journal(self.conn, 4, reason='void owner', safe=False)
        self.assertTrue(first.get('success'), first)
        self.assertTrue(second.get('success') or second.get('error'), second)
        self.conn.commit()
        self.assertEqual(account_activity(self.conn, '3300')['balance'], 0.0)
        voids = self.conn.execute(
            "SELECT COUNT(*) FROM journal_entries WHERE source_module='consumption' "
            "AND source_id='4' AND entry_type='consumption_void' AND deleted_at IS NULL"
        ).fetchone()[0]
        self.assertEqual(voids, 1)

    def test_transfer_cannot_be_booked_as_sales(self):
        from desktop.utils.accounting_engine import create_expense, create_transfer, profit_and_loss
        refused = create_transfer(self.conn, {
            'from_code': '4000', 'to_code': '1000', 'amount': 500,
            'description': 'Not a sale',
        })
        self.assertIn('not income', refused.get('error', '').lower())
        sales_expense = create_expense(self.conn, {
            'account_code': '4000', 'pay_from_code': '1000', 'amount': 15000,
            'description': 'Rent booked to sales',
        })
        self.assertIn('expense account', sales_expense.get('error', '').lower())
        moved = create_transfer(self.conn, {
            'from_code': '1000', 'to_code': '1020', 'amount': 2000,
            'description': 'Cash to bank',
        })
        self.assertTrue(moved.get('success'), moved)
        rent = create_expense(self.conn, {
            'account_code': '6000', 'pay_from_code': '1000', 'amount': 15000,
            'description': 'Rent',
        })
        self.assertTrue(rent.get('success'), rent)
        self.conn.commit()
        pl = profit_and_loss(self.conn)
        self.assertEqual(pl['total_income'], 0.0)
        self.assertEqual(pl['total_expenses'], 15000.0)

    def test_split_tenders_post_to_their_own_accounts(self):
        from desktop.utils.accounting_engine import payment_method_account
        from desktop.utils.accounting_hooks import post_sale_journal
        self.assertEqual(payment_method_account('Airtel Money'), '1010')
        self.assertEqual(payment_method_account('Card'), '1030')
        self.assertEqual(payment_method_account('Cash'), '1000')
        self.conn.execute(
            """CREATE TABLE sales (
                id INTEGER PRIMARY KEY,
                receipt_number TEXT, status TEXT, sale_date TEXT, created_at TEXT,
                payment_method TEXT, original_total REAL, total REAL,
                amount_paid REAL, change_amount REAL, credit_applied REAL,
                electronic_paid REAL, cash_rounding_adj REAL, notes TEXT,
                payment_tenders TEXT
            )"""
        )
        self.conn.execute(
            """CREATE TABLE payment_variances (
                id INTEGER PRIMARY KEY, sale_id INTEGER, tip_amount REAL,
                transport_amount REAL, deposit_amount REAL, advance_amount REAL,
                misc_amount REAL, excess_amount REAL, handling TEXT
            )"""
        )
        import json
        tenders = [
            {'method': 'Cash', 'amount': 150, 'status': 'confirmed'},
            {'method': 'M-Pesa', 'amount': 200, 'status': 'confirmed', 'reference': 'QAOPS1'},
            {'method': 'Card', 'amount': 120, 'status': 'confirmed'},
        ]
        self.conn.execute(
            """INSERT INTO sales (id, receipt_number, status, sale_date, payment_method,
               original_total, total, amount_paid, change_amount, credit_applied,
               electronic_paid, cash_rounding_adj, notes, payment_tenders)
               VALUES (1, 'RCP-SPLIT', 'completed', '2026-11-14', 'mixed',
               470, 470, 470, 0, 0, 320, 0, 'Paid: M-Pesa 200.00 + Cash 150.00 + Card 120.00', ?)""",
            (json.dumps(tenders),),
        )
        result = post_sale_journal(self.conn, 1, username='tester', safe=False)
        self.assertTrue(result.get('success'), result)
        lines = {
            row['account_code']: row['debit']
            for row in self.conn.execute(
                "SELECT account_code, debit FROM journal_lines WHERE journal_id=?",
                (result['journal_id'],),
            )
        }
        self.assertEqual(lines.get('1000'), 150.0)
        self.assertEqual(lines.get('1010'), 200.0)
        self.assertEqual(lines.get('1030'), 120.0)

    def test_manual_mpesa_code_on_a_split_line_is_recorded(self):
        from backend.mpesa_service import MpesaSaleError, prepare_sale_mpesa
        self.conn.execute(
            "CREATE TABLE sales (id INTEGER PRIMARY KEY, mpesa_ref TEXT)"
        )
        data = {
            'payment_method': 'mixed',
            'electronic_method': 'M-Pesa',
            'electronic_paid': 200,
            'payment_tenders': [
                {'method': 'M-Pesa', 'amount': 200, 'status': 'confirmed', 'reference': 'QAOPS1'},
                {'method': 'Cash', 'amount': 150, 'status': 'confirmed'},
            ],
        }
        prepared = prepare_sale_mpesa(self.conn, data, 'mixed', 200)
        self.assertEqual(prepared.get('mpesa_ref'), 'QAOPS1')
        self.assertNotIn('No transaction code', prepared.get('note') or '')
        self.assertIn('Not verified', prepared.get('note') or '')
        with self.assertRaises(MpesaSaleError):
            prepare_sale_mpesa(self.conn, data, 'mixed', 200)
        with self.assertRaises(MpesaSaleError):
            prepare_sale_mpesa(self.conn, {
                **data,
                'payment_tenders': [
                    {'method': 'M-Pesa', 'amount': 200, 'status': 'confirmed', 'reference': 'QA'},
                ],
            }, 'mixed', 200)


if __name__ == '__main__':
    unittest.main()
