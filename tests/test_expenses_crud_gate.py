"""F01: expenses create / list / update / delete API smoke."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ExpensesCrudGate(unittest.TestCase):
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
        self.api._role = 'admin'
        self.api._user_id = 1
        self.api._username = 'admin'
        db = ac._db()
        existing = db.execute(
            "SELECT id FROM users WHERE username=?", ('admin',)
        ).fetchone()
        if existing:
            self.api._user_id = int(existing['id'])
            db.execute(
                "UPDATE users SET role='admin' WHERE id=?", (self.api._user_id,)
            )
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                ('admin', 'x:y', 'admin'),
            )
            self.api._user_id = int(
                db.execute("SELECT last_insert_rowid()").fetchone()[0]
            )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_f01_create_list_update_delete_expense(self):
        today = str(date.today())
        before = self.api.accounting_expenses(today, today) or []
        n0 = len(before)

        created = self.api.accounting_create_expense({
            'amount': 500.0,
            'description': 'Gate rent',
            'account_code': '6000',
            'pay_from_code': '1000',
            'expense_date': today,
            'vendor_name': 'Landlord',
        })
        self.assertTrue(created.get('success'), created)
        self.assertTrue(created.get('expense_number'))
        eid = int(created['id'])

        rows = self.api.accounting_expenses(today, today) or []
        self.assertEqual(len(rows), n0 + 1)
        match = next(
            (r for r in rows if r.get('expense_number') == created['expense_number']),
            None,
        )
        self.assertIsNotNone(match)
        self.assertAlmostEqual(float(match.get('amount') or 0), 500.0, places=2)
        self.assertIn('Gate rent', match.get('description') or '')

        updated = self.api.accounting_update_expense(eid, {
            'amount': 750.0,
            'description': 'Gate rent revised',
            'vendor_name': 'Landlord LLC',
            'account_code': '6000',
            'pay_from_code': '1000',
            'expense_date': today,
        })
        self.assertTrue(updated.get('success'), updated)

        rows2 = self.api.accounting_expenses(today, today) or []
        match2 = next((r for r in rows2 if int(r.get('id') or 0) == eid), None)
        self.assertIsNotNone(match2)
        self.assertAlmostEqual(float(match2.get('amount') or 0), 750.0, places=2)
        self.assertIn('revised', match2.get('description') or '')
        self.assertEqual(match2.get('vendor_name'), 'Landlord LLC')

        deleted = self.api.accounting_delete_expense(eid, 'gate cleanup')
        self.assertTrue(deleted.get('success'), deleted)
        rows3 = self.api.accounting_expenses(today, today) or []
        self.assertFalse(any(int(r.get('id') or 0) == eid for r in rows3))

    def test_cashier_cannot_create_expense(self):
        self.api._role = 'cashier'
        denied = self.api.accounting_create_expense({
            'amount': 10.0,
            'description': 'blocked',
        })
        self.assertIn('error', denied)
        denied_u = self.api.accounting_update_expense(1, {'description': 'x'})
        self.assertIn('error', denied_u)
        denied_d = self.api.accounting_delete_expense(1, 'x')
        self.assertIn('error', denied_d)


if __name__ == '__main__':
    unittest.main()
