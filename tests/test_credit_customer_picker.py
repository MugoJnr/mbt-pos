"""Credit customer picker auto-selects a lone match."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class CreditCustomerPickerTests(unittest.TestCase):
    def setUp(self):
        from PyQt5.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication([])

    def test_single_customer_auto_selected_in_picker(self):
        from desktop.dialogs.credit_customer_dialogs import CustomerPickerDialog

        class FakeApi:
            def get_customers(self):
                return [{
                    'id': 42,
                    'name': 'Lone Credit Cust',
                    'phone': '0700123456',
                    'wallet_balance': 0,
                    'total_outstanding': 0,
                }]

        dlg = CustomerPickerDialog(None, FakeApi())
        if dlg._use_select and dlg.picker is not None:
            self.assertEqual(dlg.picker.current_value(), 42)
        elif dlg._list is not None:
            from PyQt5.QtCore import Qt
            it = dlg._list.currentItem()
            self.assertIsNotNone(it)
            self.assertEqual(it.data(Qt.UserRole), 42)


if __name__ == '__main__':
    unittest.main()
