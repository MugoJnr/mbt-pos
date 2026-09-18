"""Focused v3.0.92 checks: Expense keys + Pro foot hide list + Inbox open."""
from __future__ import annotations

import inspect
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class ExpenseWireDialogKeysArgs(unittest.TestCase):
    """RecordExpenseDialog must call wire_dialog_keys(primary=, cancel=)."""

    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_source_uses_primary_cancel_not_accept_reject(self):
        path = os.path.join(ROOT, 'desktop', 'dialogs', 'record_expense_dialog.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('wire_dialog_keys(self, primary=self._submit, cancel=self._cancel)', src)
        self.assertNotIn('accept_btn', src)
        self.assertNotIn('reject_btn', src)

    def test_construct_calls_real_wire_dialog_keys(self):
        from desktop.dialogs.record_expense_dialog import RecordExpenseDialog
        from desktop.utils.dialog_keys import wire_dialog_keys

        api = MagicMock()
        api.accounting_expense_categories.return_value = [
            {'label': 'Transport', 'account_code': '6400'},
        ]
        # Call the real wire_dialog_keys — previously TypeError on accept_btn=
        with patch('desktop.dialogs.record_expense_dialog.apply_themed_dialog'), \
             patch(
                 'desktop.dialogs.record_expense_dialog.wire_dialog_keys',
                 wraps=wire_dialog_keys,
             ) as wired:
            dlg = RecordExpenseDialog(None, api, currency='KES', user={'role': 'cashier'})
            wired.assert_called_once()
            kwargs = wired.call_args.kwargs
            self.assertIn('primary', kwargs)
            self.assertIn('cancel', kwargs)
            self.assertNotIn('accept_btn', kwargs)
            self.assertNotIn('reject_btn', kwargs)
            dlg.close()


class CheckoutProFootHideList(unittest.TestCase):
    def test_hide_list_includes_expense_and_mpesa_inbox(self):
        path = os.path.join(ROOT, 'desktop', 'pos', 'checkout_pro_chrome.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        # Sticky foot must never show these next to Grand Total / Complete Sale.
        self.assertIn("'_mpesa_inbox_btn'", src)
        self.assertIn("'_expense_btn'", src)
        # Sale Actions must keep Expense and must not crowbar M-Pesa Inbox.
        self.assertIn("('_record_expense'", src) or "'_record_expense'" in src
        self.assertIn("('Expense', warn, '_record_expense')", src)
        self.assertNotIn("('M-Pesa Inbox', info, '_open_payment_inbox')", src)
        self.assertIn('_remove_mpesa_inbox_sale_action_tile', src)

    def test_panel_factory_hides_both_from_footer_row(self):
        path = os.path.join(ROOT, 'desktop', 'pos', 'panel_factory.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('tab._expense_btn.hide()', src)
        self.assertIn('tab._mpesa_inbox_btn.hide()', src)
        # Must not add either to the visible secondary row.
        self.assertNotIn('br.addWidget(tab._mpesa_inbox_btn)', src)
        self.assertNotIn('br.addWidget(tab._expense_btn)', src)


class PaymentInboxOpen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_inbox_dialog_opens_on_temp_db(self):
        from desktop.payments.schema import ensure_payment_schema
        from desktop.payments.service import build_payment_service
        from desktop.dialogs.payment_inbox_dialog import PaymentInboxDialog

        db_path = tempfile.mktemp(suffix='.db')
        conn = sqlite3.connect(db_path)
        conn.executescript(
            'CREATE TABLE sales (id INTEGER PRIMARY KEY);'
            'CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT);'
        )
        conn.commit()
        ensure_payment_schema(conn)
        conn.close()

        def factory():
            c = sqlite3.connect(db_path)
            c.row_factory = sqlite3.Row
            return c

        svc = build_payment_service(db_conn_factory=factory, offline=True)
        dlg = PaymentInboxDialog(None, payment_service=svc, currency='KES')
        self.assertEqual(dlg.windowTitle(), 'M-Pesa Payment Inbox')
        self.assertEqual(dlg.table.rowCount(), 0)
        dlg.close()

    def test_schema_tolerates_missing_sales_and_settings(self):
        from desktop.payments.schema import ensure_payment_schema
        db_path = tempfile.mktemp(suffix='.db')
        conn = sqlite3.connect(db_path)
        # Empty DB — previously crashed on ALTER sales / system_settings.
        ensure_payment_schema(conn)
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertIn('mpesa_payments', tables)
        self.assertIn('mpesa_incoming', tables)
        conn.close()


if __name__ == '__main__':
    unittest.main()
