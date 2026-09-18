"""Cashier POS expense: create allowed, edit/delete denied, idempotent, math."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import date
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class CashierExpenseSuite(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'test.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self._db_path),
        ]
        for p in self._patches:
            p.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            ('cashier1', 'x:y', 'cashier'),
        )
        self.cashier_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            ('admin1', 'x:y', 'admin'),
        )
        self.admin_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.commit()
        db.close()
        self.api._role = 'cashier'
        self.api._user_id = self.cashier_id
        self.api._username = 'cashier1'

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _as_cashier(self):
        self.api._role = 'cashier'
        self.api._user_id = self.cashier_id
        self.api._username = 'cashier1'

    def _as_admin(self):
        self.api._role = 'admin'
        self.api._user_id = self.admin_id
        self.api._username = 'admin1'

    def test_e1_cashier_creates_expense(self):
        today = str(date.today())
        txn = str(uuid.uuid4())
        created = self.api.accounting_create_expense({
            'amount': 500.0,
            'category_label': 'Transport',
            'description': 'Delivery boda',
            'payment_method': 'cash',
            'vendor_name': 'Boda rider',
            'client_txn_id': txn,
            'expense_date': today,
        })
        self.assertTrue(created.get('success'), created)
        self.assertEqual(created.get('payment_method'), 'cash')
        self.assertEqual(created.get('pay_from_code'), '1000')
        self.assertEqual(created.get('category_label'), 'Transport')
        rows = self.api.accounting_expenses(today, today) or []
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]['amount']), 500.0, places=2)
        self.assertEqual(int(rows[0]['created_by']), self.cashier_id)

    def test_e2_e3_e4_cashier_cannot_edit_delete(self):
        created = self.api.accounting_create_expense({
            'amount': 100.0,
            'description': 'Snack',
            'category_label': 'Staff Meals',
            'payment_method': 'cash',
            'client_txn_id': str(uuid.uuid4()),
        })
        self.assertTrue(created.get('success'), created)
        eid = int(created['id'])
        denied_u = self.api.accounting_update_expense(eid, {'amount': 1.0})
        self.assertIn('error', denied_u)
        denied_d = self.api.accounting_delete_expense(eid, 'nope')
        self.assertIn('error', denied_d)
        denied_r = self.api.accounting_reverse_expense(eid, 'nope')
        self.assertIn('error', denied_r)
        rows = self.api.accounting_expenses() or []
        match = next(r for r in rows if int(r['id']) == eid)
        self.assertAlmostEqual(float(match['amount']), 100.0, places=2)

    def test_e5_admin_reversal(self):
        created = self.api.accounting_create_expense({
            'amount': 200.0,
            'description': 'Fuel',
            'category_label': 'Fuel',
            'payment_method': 'cash',
            'client_txn_id': str(uuid.uuid4()),
        })
        eid = int(created['id'])
        cash_before = self.api.accounting_cash_balance('1000')
        self._as_admin()
        rev = self.api.accounting_reverse_expense(eid, 'Wrong amount')
        self.assertTrue(rev.get('success'), rev)
        rows = self.api.accounting_expenses() or []
        self.assertFalse(any(int(r.get('id') or 0) == eid for r in rows))
        cash_after = self.api.accounting_cash_balance('1000')
        self.assertAlmostEqual(cash_after - cash_before, 200.0, places=2)

    def test_e6_e7_payment_method_accounts(self):
        cash0 = self.api.accounting_cash_balance('1000')
        mpesa0 = self.api.accounting_cash_balance('1010')
        self.api.accounting_create_expense({
            'amount': 1000.0,
            'description': 'Cash fuel',
            'category_label': 'Fuel',
            'payment_method': 'cash',
            'client_txn_id': str(uuid.uuid4()),
        })
        self.assertAlmostEqual(
            cash0 - self.api.accounting_cash_balance('1000'), 1000.0, places=2)
        self.assertAlmostEqual(
            mpesa0 - self.api.accounting_cash_balance('1010'), 0.0, places=2)
        mpesa1 = self.api.accounting_cash_balance('1010')
        self.api.accounting_create_expense({
            'amount': 750.0,
            'description': 'Data',
            'category_label': 'Internet / Data',
            'payment_method': 'mpesa',
            'client_txn_id': str(uuid.uuid4()),
        })
        self.assertAlmostEqual(
            mpesa1 - self.api.accounting_cash_balance('1010'), 750.0, places=2)
        # Physical cash unchanged by M-Pesa expense
        self.assertAlmostEqual(
            self.api.accounting_cash_balance('1000'), cash0 - 1000.0, places=2)

    def test_e8_profit_math(self):
        self._as_admin()
        db = self.ac._db()
        from desktop.utils.accounting_engine import post_journal, profit_and_loss, create_expense
        # Controlled income 20000, COGS 12000, expense 2000 → gross 8000, net 6000
        post_journal(
            db,
            [
                {'account_code': '1000', 'debit': 20000, 'memo': 'sale'},
                {'account_code': '4000', 'credit': 20000, 'memo': 'sale'},
            ],
            description='test sale',
            entry_date=str(date.today()),
            source_module='test',
            source_id='sale1',
            entry_type='sale',
            user_id=self.admin_id,
            username='admin1',
        )
        post_journal(
            db,
            [
                {'account_code': '5000', 'debit': 12000, 'memo': 'cogs'},
                {'account_code': '1200', 'credit': 12000, 'memo': 'cogs'},
            ],
            description='test cogs',
            entry_date=str(date.today()),
            source_module='test',
            source_id='cogs1',
            entry_type='cogs',
            user_id=self.admin_id,
            username='admin1',
        )
        create_expense(db, {
            'amount': 2000,
            'category_label': 'Rent',
            'description': 'Shop rent',
            'payment_method': 'cash',
            'client_txn_id': str(uuid.uuid4()),
        }, user_id=self.admin_id, username='admin1')
        db.commit()
        pl = profit_and_loss(db, str(date.today()), str(date.today()))
        db.close()
        self.assertAlmostEqual(pl['total_income'], 20000.0, places=2)
        self.assertAlmostEqual(pl['total_cogs'], 12000.0, places=2)
        self.assertAlmostEqual(pl['gross_profit'], 8000.0, places=2)
        self.assertAlmostEqual(pl['total_expenses'], 2000.0, places=2)
        self.assertAlmostEqual(pl['net_profit'], 6000.0, places=2)

    def test_e9_duplicate_client_txn(self):
        txn = str(uuid.uuid4())
        a = self.api.accounting_create_expense({
            'amount': 333.0,
            'description': 'dup',
            'category_label': 'Other',
            'payment_method': 'cash',
            'client_txn_id': txn,
        })
        b = self.api.accounting_create_expense({
            'amount': 333.0,
            'description': 'dup',
            'category_label': 'Other',
            'payment_method': 'cash',
            'client_txn_id': txn,
        })
        self.assertTrue(a.get('success'), a)
        self.assertTrue(b.get('success'), b)
        self.assertTrue(b.get('idempotent'))
        self.assertEqual(int(a['id']), int(b['id']))
        today = str(date.today())
        rows = [r for r in (self.api.accounting_expenses(today, today) or [])
                if float(r.get('amount') or 0) == 333.0]
        self.assertEqual(len(rows), 1)

    def test_e18_multi_cashier_ownership(self):
        self.api.accounting_create_expense({
            'amount': 50.0,
            'description': 'c1',
            'category_label': 'Other',
            'payment_method': 'cash',
            'client_txn_id': str(uuid.uuid4()),
        })
        db = self.ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            ('cashier2', 'x:y', 'cashier'),
        )
        c2 = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.commit()
        db.close()
        self.api._user_id = c2
        self.api._username = 'cashier2'
        self.api.accounting_create_expense({
            'amount': 75.0,
            'description': 'c2',
            'category_label': 'Other',
            'payment_method': 'cash',
            'client_txn_id': str(uuid.uuid4()),
        })
        own = self.api.accounting_expenses() or []
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0]['description'], 'c2')


if __name__ == '__main__':
    unittest.main()
