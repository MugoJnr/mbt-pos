"""Regressions for the v3.0.75 shell, dialog and lifecycle defects.

Covers:
  * deferred dashboard work must not touch a destroyed widget
  * Enter in a dialog runs the validated primary action, never Cancel
  * the login dialog focuses username instead of its scroll area
  * AI workspace quick actions keep their full label width at 1024
  * the inventory Current Stock hint wraps instead of overflowing
  * unreadable payment amounts refuse instead of raising
  * the shell minimum size fits a 1024x768 screen
  * logout stops timers and services before the window is retired
  * global search only queries modules the role can open
"""
from __future__ import annotations

import ast
import os
import sys
import traceback
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QEventLoop, QSize, Qt, QTimer  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QApplication, QDialog, QLabel, QLineEdit, QPushButton, QWidget,
)

APP = QApplication.instance() or QApplication([])


def pump(msec: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(msec, loop.quit)
    loop.exec_()


class DeferredLifecycleTests(unittest.TestCase):
    def test_defer_runs_while_owner_alive(self):
        from desktop.utils.lifecycle import defer
        owner = QWidget()
        fired = []
        defer(owner, 10, lambda: fired.append(True))
        pump(200)
        self.assertEqual(fired, [True])
        owner.deleteLater()

    def test_defer_is_cancelled_with_its_owner(self):
        from desktop.utils.lifecycle import defer
        errors = []

        def hook(exc_type, exc, tb):
            errors.append(''.join(traceback.format_exception(exc_type, exc, tb)))

        owner = QWidget()
        child = QLabel('x', owner)
        fired = []

        def touch_deleted():
            fired.append(True)
            child.setText('boom')

        defer(owner, 120, touch_deleted)
        owner.deleteLater()
        owner.setParent(None)
        del owner

        previous = sys.excepthook
        sys.excepthook = hook
        try:
            pump(500)
        finally:
            sys.excepthook = previous

        self.assertEqual(fired, [])
        self.assertEqual(errors, [])

    def test_stop_timers_halts_child_timers(self):
        from desktop.utils.lifecycle import stop_timers
        owner = QWidget()
        ticks = []
        timer = QTimer(owner)
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(10)
        self.assertEqual(stop_timers(owner), 1)
        pump(120)
        self.assertEqual(ticks, [])
        owner.deleteLater()

    def test_dashboard_has_no_bare_single_shot(self):
        path = os.path.join(ROOT, 'desktop', 'tabs', 'dashboard_tab.py')
        with open(path, 'r', encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'singleShot'
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == 'QTimer'
        ]
        self.assertEqual(
            offenders, [],
            f'bare QTimer.singleShot at lines {offenders}; use defer(owner, ms, fn)')


class DialogKeyboardTests(unittest.TestCase):
    """Enter must reach the validated primary action, never Cancel."""

    def _dialog(self):
        from desktop.utils.dialog_keys import wire_dialog_keys
        dlg = QDialog()
        field = QLineEdit(dlg)
        cancel = QPushButton('Cancel', dlg)
        primary = QPushButton('Save', dlg)
        calls = {'cancel': 0, 'save': 0}
        cancel.clicked.connect(lambda: calls.__setitem__('cancel', calls['cancel'] + 1))
        primary.clicked.connect(lambda: calls.__setitem__('save', calls['save'] + 1))
        wire_dialog_keys(dlg, primary=primary, cancel=cancel)
        return dlg, field, primary, cancel, calls

    def test_enter_triggers_primary_not_cancel(self):
        from PyQt5.QtTest import QTest
        dlg, field, primary, cancel, calls = self._dialog()
        dlg.show()
        field.setFocus()
        QTest.keyClick(dlg, Qt.Key_Return)
        self.assertEqual(calls['save'], 1)
        self.assertEqual(calls['cancel'], 0)
        dlg.close()

    def test_cancel_is_never_auto_default(self):
        dlg, _field, primary, cancel, _calls = self._dialog()
        self.assertFalse(cancel.autoDefault())
        self.assertFalse(cancel.isDefault())
        self.assertTrue(primary.isDefault())
        dlg.close()

    def test_disabled_primary_swallows_enter(self):
        from PyQt5.QtTest import QTest
        dlg, field, primary, cancel, calls = self._dialog()
        primary.setEnabled(False)
        dlg.show()
        field.setFocus()
        QTest.keyClick(dlg, Qt.Key_Return)
        self.assertEqual(calls, {'cancel': 0, 'save': 0})
        dlg.close()

    def test_exempt_field_does_not_submit(self):
        from PyQt5.QtTest import QTest
        from desktop.utils.dialog_keys import wire_dialog_keys
        dlg = QDialog()
        search = QLineEdit(dlg)
        primary = QPushButton('Go', dlg)
        calls = []
        primary.clicked.connect(lambda: calls.append(True))
        wire_dialog_keys(dlg, primary=primary, submit_exempt=(search,))
        dlg.show()
        search.setFocus()
        QTest.keyClick(dlg, Qt.Key_Return)
        self.assertEqual(calls, [])
        dlg.close()

    def test_wired_dialogs_import_the_helper(self):
        """Every dialog named in the defect list must route Enter."""
        targets = (
            ('desktop', 'dialogs', 'return_sale_dialog.py'),
            ('desktop', 'dialogs', 'receive_stock_dialog.py'),
            ('desktop', 'dialogs', 'edit_sale_dialog.py'),
            ('desktop', 'dialogs', 'category_editor.py'),
            ('desktop', 'dialogs', 'credit_customer_dialogs.py'),
            ('desktop', 'tabs', 'inventory_tab.py'),
        )
        for parts in targets:
            path = os.path.join(ROOT, *parts)
            with open(path, 'r', encoding='utf-8') as fh:
                source = fh.read()
            self.assertIn('wire_dialog_keys', source, parts[-1])


class PaymentVarianceCoercionTests(unittest.TestCase):
    def test_parse_money_handles_formatted_and_broken_input(self):
        from desktop.dialogs.payment_variance_dialog import parse_money
        self.assertEqual(parse_money(250), (250.0, True))
        self.assertEqual(parse_money('1,250.50'), (1250.5, True))
        self.assertEqual(parse_money('KES 300'), (300.0, True))
        self.assertEqual(parse_money('abc'), (0.0, False))
        self.assertEqual(parse_money(None), (0.0, False))
        self.assertEqual(parse_money(''), (0.0, False))

    def test_non_numeric_amount_opens_a_refusing_dialog(self):
        from desktop.dialogs.payment_variance_dialog import PaymentVarianceDialog
        dlg = PaymentVarianceDialog(None, 'KES', 'not-a-number', 'nope', 'nope')
        self.assertTrue(dlg.invalid_amounts)
        self.assertFalse(dlg._confirm_btn.isEnabled())
        self.assertIsNone(dlg.result_data)
        dlg.close()

    def test_string_amounts_are_accepted(self):
        from desktop.dialogs.payment_variance_dialog import PaymentVarianceDialog
        dlg = PaymentVarianceDialog(None, 'KES', '1,000.00', '1,250.00', '250.00')
        self.assertFalse(dlg.invalid_amounts)
        self.assertEqual(dlg._excess, 250.0)
        self.assertTrue(dlg._confirm_btn.isEnabled())
        dlg.close()

    def test_missing_excess_is_derived_from_the_other_amounts(self):
        from desktop.dialogs.payment_variance_dialog import PaymentVarianceDialog
        dlg = PaymentVarianceDialog(None, 'KES', 1000, 1250, None)
        self.assertFalse(dlg.invalid_amounts)
        self.assertEqual(dlg._excess, 250.0)
        dlg.close()


class InventoryLabelWrapTests(unittest.TestCase):
    def test_current_stock_hint_wraps(self):
        source_path = os.path.join(ROOT, 'desktop', 'tabs', 'inventory_tab.py')
        with open(source_path, 'r', encoding='utf-8') as fh:
            source = fh.read()
        marker = "lay.addRow(lbl('Current Stock'), stk_info)"
        self.assertIn(marker, source)
        block = source[source.index('Use the Adjust Stock button'):source.index(marker)]
        self.assertIn('setWordWrap(True)', block)


class AiWorkspaceQuickActionTests(unittest.TestCase):
    def test_quick_action_labels_are_not_squeezed(self):
        from desktop.widgets.ai_assistant import _QUICK_ACTIONS
        from PyQt5.QtGui import QFontMetrics
        holder = QWidget()
        holder.resize(1024, 60)
        too_narrow = []
        for label, _kind, icon in _QUICK_ACTIONS[:8]:
            button = QPushButton(f'{icon} {label}', holder)
            button.setMinimumWidth(button.sizeHint().width())
            needed = QFontMetrics(button.font()).horizontalAdvance(button.text())
            if button.minimumWidth() < needed:
                too_narrow.append(label)
        self.assertEqual(too_narrow, [])
        holder.deleteLater()

    def test_workspace_uses_a_scrollable_quick_action_strip(self):
        path = os.path.join(ROOT, 'desktop', 'widgets', 'ai_workspace.py')
        with open(path, 'r', encoding='utf-8') as fh:
            source = fh.read()
        self.assertIn('wsQuickStrip', source)
        self.assertIn('setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)', source)


class ShellGeometryTests(unittest.TestCase):
    def test_minimum_width_fits_a_1024_screen(self):
        import desktop.main as main
        source_path = os.path.join(ROOT, 'desktop', 'main.py')
        with open(source_path, 'r', encoding='utf-8') as fh:
            source = fh.read()
        self.assertNotIn('setMinimumSize(1200, 720)', source)

        class _Probe(QWidget):
            _responsive_minimum = main.MainWindow._responsive_minimum

        probe = _Probe()
        size = probe._responsive_minimum()
        self.assertIsInstance(size, QSize)
        self.assertLessEqual(size.width(), 1024)
        self.assertLessEqual(size.height(), 768)
        self.assertGreaterEqual(size.width(), 640)
        probe.deleteLater()


class LogoutLifecycleTests(unittest.TestCase):
    """Logout must not leave a hidden window polling under the old session."""

    def test_stop_services_stops_pollers_and_timers(self):
        import desktop.main as main

        class _Svc:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

        window = QWidget()
        window._closing = False
        window._services_started = True
        services = {name: _Svc() for name in
                    ('_svc_net', '_svc_lic', '_svc_diag', '_svc_sched')}
        for name, svc in services.items():
            setattr(window, name, svc)
        window._updater = _Svc()
        updater = window._updater

        ticks = []
        timer = QTimer(window)
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(10)

        called = []
        stubs = {
            'backend.cloud_backup': 'stop_cloud_backup_service',
            'backend.local_db_backup': 'stop_local_backup_scheduler',
            'backend.cloud.report_engine': 'stop_report_scheduler',
            'backend.cloudflare_setup': 'stop_auto_cloudflare',
        }
        patches = [
            patch(f'{module}.{func}', lambda _m=module: called.append(_m))
            for module, func in stubs.items()
        ]
        for item in patches:
            item.start()
        try:
            main.MainWindow._stop_services(window)
        finally:
            for item in patches:
                item.stop()

        self.assertTrue(updater.stopped)
        for name, svc in services.items():
            self.assertTrue(svc.stopped, name)
            self.assertIsNone(getattr(window, name))
        self.assertEqual(sorted(called), sorted(stubs))
        self.assertFalse(window._services_started)
        pump(80)
        self.assertEqual(ticks, [])
        window.deleteLater()

    def test_start_services_is_not_run_twice(self):
        import desktop.main as main
        window = QWidget()
        window._closing = False
        window._services_started = True
        # A replayed boot timer must return before touching any service.
        main.MainWindow._start_services(window)
        self.assertFalse(hasattr(window, '_svc_net'))
        window.deleteLater()

    def test_retired_window_never_restarts_services(self):
        import desktop.main as main
        window = QWidget()
        window._closing = True
        window._services_started = False
        main.MainWindow._start_services(window)
        self.assertFalse(window._services_started)
        window.deleteLater()

    def test_logout_closes_window_before_showing_login(self):
        source_path = os.path.join(ROOT, 'desktop', 'main.py')
        with open(source_path, 'r', encoding='utf-8') as fh:
            source = fh.read()
        start = source.index('def _perform_logout')
        block = source[start:source.index('def _logout', start)]
        for expected in ('self._stop_services()', 'self.close()',
                         'self.deleteLater()', 'setQuitOnLastWindowClosed(False)'):
            self.assertIn(expected, block)
        # Login is scheduled after the teardown, not called inline.
        self.assertIn('QTimer.singleShot(0, lambda: _show_login(api))', block)


class LoginFocusTests(unittest.TestCase):
    def test_username_holds_focus_and_sign_in_is_default(self):
        from desktop.main import LoginDialog
        from PyQt5.QtGui import QIcon
        dlg = LoginDialog(object(), QIcon())
        dlg.show()
        APP.processEvents()
        self.assertTrue(dlg._u.hasFocus())
        self.assertTrue(dlg._btn.isDefault())
        dlg.close()
        dlg.deleteLater()


class GlobalSearchScopeTests(unittest.TestCase):
    class _Api:
        def __init__(self):
            self.calls = []

        def get_products(self):
            self.calls.append('products')
            return [{'id': 1, 'name': 'Sugar', 'sku': 'SG1', 'stock': 3,
                     'is_active': 1}]

        def get_customers(self):
            self.calls.append('customers')
            return [{'id': 2, 'name': 'Sugar Buyer', 'phone': '0700'}]

        def get_sales(self, start, end):
            self.calls.append('sales')
            return [{'id': 3, 'receipt_number': 'SUGAR-1', 'payment_method': 'Cash',
                     'total': 10, 'status': 'completed'}]

        def get_debt_invoices(self):
            self.calls.append('debts')
            return [{'id': 4, 'invoice_number': 'SUGARINV', 'customer_name': 'X',
                     'balance': 5, 'status': 'open'}]

    def test_cashier_only_queries_allowed_modules(self):
        from desktop.dialogs.global_search_dialog import GlobalSearchDialog
        api = self._Api()
        dlg = GlobalSearchDialog(api, allowed_modules=('sales',))
        dlg._q.setText('sugar')
        APP.processEvents()
        self.assertEqual(api.calls, ['sales'])
        self.assertNotIn('products', api.calls)
        self.assertNotIn('debts', api.calls)
        self.assertIn('receipts', dlg._hint.text())
        self.assertNotIn('products', dlg._hint.text())
        dlg.close()

    def test_manager_queries_every_allowed_module(self):
        from desktop.dialogs.global_search_dialog import GlobalSearchDialog
        api = self._Api()
        dlg = GlobalSearchDialog(
            api, allowed_modules=('sales', 'inventory', 'debt'))
        dlg._q.setText('sugar')
        APP.processEvents()
        self.assertEqual(sorted(set(api.calls)),
                         ['customers', 'debts', 'products', 'sales'])
        dlg.close()


if __name__ == '__main__':
    unittest.main()
