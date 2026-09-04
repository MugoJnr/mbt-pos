"""Regression: report bundle gating + permission-denial log redaction.

`/api/reports/data` accepted `reports` OR `sales`, so a cashier holding only POS
access could pull the whole report bundle. Separately, denial logging wrote the
entire login response, which carries the session token.
"""
import io
import logging
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

CASHIER = {'role': 'cashier', 'tab_permissions': ['dashboard', 'sales']}
VIEWER = {'role': 'viewer', 'tab_permissions': ['dashboard', 'reports', 'accounting']}
MANAGER = {'role': 'manager', 'tab_permissions': ['dashboard', 'sales', 'reports']}


class ReportsDataGateTests(unittest.TestCase):
    def setUp(self):
        from web import web_routes
        self.wr = web_routes

    def test_cashier_has_sales_but_not_reports(self):
        """The old gate passed on this alias — it must not grant reports."""
        self.assertTrue(self.wr._user_can('sales', CASHIER))
        self.assertFalse(self.wr._user_can('reports', CASHIER))

    def test_reports_roles_still_allowed(self):
        self.assertTrue(self.wr._user_can('reports', VIEWER))
        self.assertTrue(self.wr._user_can('reports', MANAGER))
        self.assertTrue(self.wr._user_can('reports', {'role': 'admin'}))
        self.assertTrue(self.wr._user_can('reports', {'role': 'superadmin'}))

    def test_reports_data_route_does_not_fall_back_to_sales(self):
        import ast
        import inspect
        src = inspect.getsource(self.wr.reports_data)
        tree = ast.parse(src.lstrip())
        calls = [
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == '_user_can'
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ]
        self.assertEqual(calls, ['reports'])


class PermissionDenialLoggingTests(unittest.TestCase):
    FAKE_TOKEN = 'eyJhbGciOiJIUzI1NiJ9.SESSIONTOKENVALUE.signature'

    def setUp(self):
        from PyQt5.QtWidgets import QApplication, QMessageBox
        self.app = QApplication.instance() or QApplication([])
        self._real_warning = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *a, **k: None)
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger = logging.getLogger('security')
        self.logger.setLevel(logging.WARNING)
        self.logger.addHandler(self.handler)

    def tearDown(self):
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning = self._real_warning
        self.logger.removeHandler(self.handler)

    def _deny(self):
        from desktop.utils.security import require_permission
        login_response = {
            'token': self.FAKE_TOKEN,
            'user': {
                'id': 7,
                'username': 'till_two',
                'full_name': 'Till Two',
                'role': 'cashier',
                'tab_permissions': ['dashboard', 'sales'],
            },
        }
        allowed = require_permission(login_response, 'inventory.adjust_stock')
        return allowed, self.stream.getvalue()

    def test_denial_is_refused(self):
        allowed, _ = self._deny()
        self.assertFalse(allowed)

    def test_token_is_not_logged(self):
        _, out = self._deny()
        self.assertNotIn(self.FAKE_TOKEN, out)
        self.assertNotIn('SESSIONTOKENVALUE', out)
        self.assertNotIn('token', out)

    def test_raw_user_dict_is_not_logged(self):
        _, out = self._deny()
        self.assertNotIn('tab_permissions', out)
        self.assertNotIn('full_name', out)

    def test_identity_and_action_are_logged(self):
        _, out = self._deny()
        self.assertIn('till_two', out)
        self.assertIn('cashier', out)
        self.assertIn('inventory.adjust_stock', out)
        self.assertIn('user_id=7', out)


if __name__ == '__main__':
    unittest.main()
