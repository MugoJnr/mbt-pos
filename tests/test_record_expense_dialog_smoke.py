"""Headless smoke: RecordExpenseDialog constructs and validates amounts."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class RecordExpenseDialogSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_parse_and_dialog_construct(self):
        from desktop.dialogs.record_expense_dialog import (
            RecordExpenseDialog, _parse_amount,
        )
        self.assertEqual(_parse_amount('1,250.50')[0], 1250.50)
        self.assertIsNone(_parse_amount('0')[0])
        self.assertIsNone(_parse_amount('-5')[0])
        self.assertIsNone(_parse_amount('abc')[0])

        api = MagicMock()
        api.accounting_expense_categories.return_value = [
            {'label': 'Transport', 'account_code': '6400'},
            {'label': 'Other', 'account_code': '6900'},
        ]
        api.accounting_cash_balance.return_value = 10000.0
        api.accounting_create_expense.return_value = {
            'success': True, 'id': 1, 'expense_number': 'EXP-000001',
            'amount': 500.0,
        }
        with patch('desktop.dialogs.record_expense_dialog.apply_themed_dialog'), \
             patch('desktop.dialogs.record_expense_dialog.wire_dialog_keys'):
            dlg = RecordExpenseDialog(None, api, currency='KES', user={'role': 'cashier'})
            self.assertEqual(dlg._client_txn_id.count('-'), 4)
            dlg.close()


if __name__ == '__main__':
    unittest.main()
