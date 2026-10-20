"""Cashiers can record an expense and cannot change or remove one."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class CashierExpenseRecordTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'expenses.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = 'cashier'
        self.api._user_id = 4
        self.api._username = 'mercy'

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_cashier_records_once_and_cannot_edit_or_delete(self):
        created = self.api.accounting_create_expense({
            'amount': 150,
            'description': 'Transport',
            'account_code': '6000',
            'pay_from_code': '1000',
        })
        self.assertTrue(created.get('success'), created)
        expense_id = int(created['id'])
        db = self.ac._db()
        try:
            row = db.execute(
                "SELECT created_by_name, amount, status FROM expense_entries WHERE id=?",
                (expense_id,),
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(row['created_by_name'], 'mercy')
        self.assertAlmostEqual(float(row['amount']), 150.0)

        edited = self.api.accounting_update_expense(expense_id, {'description': 'Changed'})
        self.assertIn('Insufficient', edited.get('error', ''))
        deleted = self.api.accounting_delete_expense(expense_id, 'mistake')
        self.assertIn('Insufficient', deleted.get('error', ''))

        self.api._role = 'viewer'
        denied = self.api.accounting_create_expense({'amount': 10, 'description': 'No'})
        self.assertIn('Insufficient', denied.get('error', ''))

        db = self.ac._db()
        try:
            count = db.execute("SELECT COUNT(*) FROM expense_entries").fetchone()[0]
            still = db.execute(
                "SELECT description FROM expense_entries WHERE id=?",
                (expense_id,),
            ).fetchone()['description']
        finally:
            db.close()
        self.assertEqual(count, 1)
        self.assertEqual(still, 'Transport')


if __name__ == '__main__':
    unittest.main()
