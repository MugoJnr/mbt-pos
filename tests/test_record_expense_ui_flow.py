"""Automated UI path: open dialog, fill fields, confirm, assert API called once."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class RecordExpenseUiFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_submit_calls_api_once(self):
        from PyQt5.QtWidgets import QMessageBox
        from desktop.dialogs.record_expense_dialog import RecordExpenseDialog

        api = MagicMock()
        api.accounting_expense_categories.return_value = [
            {'label': 'Transport', 'account_code': '6400'},
        ]
        api.accounting_cash_balance.return_value = 50000.0
        api.accounting_create_expense.return_value = {
            'success': True, 'id': 9, 'expense_number': 'EXP-9', 'amount': 500.0,
        }
        with patch('desktop.dialogs.record_expense_dialog.apply_themed_dialog'), \
             patch('desktop.dialogs.record_expense_dialog.wire_dialog_keys'), \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), \
             patch.object(QMessageBox, 'information', return_value=QMessageBox.Ok):
            dlg = RecordExpenseDialog(None, api, currency='KES', user={'role': 'cashier'})
            dlg._amount.setText('500')
            dlg._category.setCurrentText('Transport')
            dlg._description.setText('Delivery boda')
            dlg._pay_method.setCurrentIndex(0)
            dlg._on_submit()
            self.assertEqual(api.accounting_create_expense.call_count, 1)
            payload = api.accounting_create_expense.call_args[0][0]
            self.assertEqual(payload['amount'], 500.0)
            self.assertEqual(payload['category_label'], 'Transport')
            self.assertEqual(payload['payment_method'], 'cash')
            self.assertTrue(payload['client_txn_id'])
            # Double submit blocked
            dlg._on_submit()
            self.assertEqual(api.accounting_create_expense.call_count, 1)


if __name__ == '__main__':
    unittest.main()
