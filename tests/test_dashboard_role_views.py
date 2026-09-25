"""Cashier and owner dashboards do not show the same shop figures."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication, QLabel

from desktop.tabs.dashboard_tab import DashboardTab


APP = QApplication.instance() or QApplication([])


class _Login:
    def __init__(self, role, user_id, tabs):
        self.user = {'role': role, 'id': user_id, 'tab_permissions': tabs}
        self.hidden = []

    def _tab_allowed(self, tab_id):
        role = self.user['role']
        if role in ('admin', 'superadmin'):
            return True
        return tab_id in self.user['tab_permissions']


class DashboardRoleTests(unittest.TestCase):
    def test_cashier_sees_shop_receipts_including_admin_sales(self):
        login = _Login('cashier', 7, ['dashboard', 'sales', 'inventory'])
        sales = [
            {'id': 1, 'cashier_id': 7, 'receipt_number': 'A', 'total': 50, 'status': 'completed'},
            {'id': 2, 'cashier_id': 3, 'receipt_number': 'B', 'total': 900, 'status': 'completed'},
        ]
        login._owner_dashboard = lambda: DashboardTab._owner_dashboard(login)
        kept = DashboardTab._sales_for_this_login(login, sales)
        self.assertEqual([s['receipt_number'] for s in kept], ['A', 'B'])
        self.assertFalse(DashboardTab._owner_dashboard(login))

    def test_admin_manager_and_reports_viewer_see_the_shop(self):
        shop = [
            {'cashier_id': 7, 'receipt_number': 'A'},
            {'cashier_id': 3, 'receipt_number': 'B'},
        ]
        admin = _Login('admin', 1, [])
        manager = _Login('manager', 2, ['dashboard', 'reports', 'sales'])
        viewer = _Login('viewer', 4, ['dashboard', 'reports', 'accounting'])
        for login in (admin, manager, viewer):
            self.assertTrue(DashboardTab._owner_dashboard(login), login.user['role'])
            login._owner_dashboard = lambda login=login: DashboardTab._owner_dashboard(login)
            kept = DashboardTab._sales_for_this_login(login, shop)
            self.assertEqual(len(kept), 2)

    def test_cashier_dashboard_hides_shop_finance_and_offers_void_request(self):
        class Api:
            def get_setting(self, key):
                return 'KES' if key == 'currency_symbol' else ''

            def get_products(self):
                return []

            def get_sales(self, *a, **k):
                return []

            def get_report_summary(self, *a, **k):
                return {'summary': {}}

            def get_debt_summary(self):
                return {}

        user = {
            'user': {
                'role': 'cashier', 'id': 7, 'username': 'till',
                'tab_permissions': ['dashboard', 'sales', 'inventory'],
            }
        }
        tab = DashboardTab(Api(), user, ':memory:', lambda: {'currency_symbol': 'KES'})
        self.assertTrue(tab._k_low.isHidden())
        self.assertTrue(tab._trend_card.isHidden())
        self.assertTrue(tab._debt_chip_host.isHidden())
        self.assertFalse(tab._copy_btn.isHidden())
        self.assertIsNone(tab._void_btn)
        self.assertFalse(tab._ask_void_btn.isHidden())
        self.assertEqual(DashboardTab._receipt_status_label('voided', False), 'Voided')
        self.assertEqual(DashboardTab._receipt_status_label('completed', True), 'Pending void')
        self.assertEqual(DashboardTab._receipt_status_label('completed', False), 'Done')
        tab._apply_void_banner([{
            'receipt_number': 'RCP-1', 'requested_by': 'till', 'reason': 'wrong item',
        }])
        self.assertFalse(tab._void_banner.isHidden())
        self.assertIn('RCP-1', tab._void_banner.text())
        self.assertIn('Pending void', tab._void_banner.text())
        tab._apply_void_banner([])
        self.assertTrue(tab._void_banner.isHidden())
        self.assertIn('What was sold', [
            tab._tbl.horizontalHeaderItem(i).text()
            for i in range(tab._tbl.columnCount())
        ])
        tab.deleteLater()

    def test_admin_dashboard_keeps_void_and_shop_charts(self):
        class Api:
            def get_setting(self, key):
                return 'KES'

            def get_products(self):
                return []

            def get_sales(self, *a, **k):
                return []

            def get_report_summary(self, *a, **k):
                return {'summary': {}}

            def get_debt_summary(self):
                return {}

        user = {'user': {'role': 'admin', 'id': 1, 'username': 'owner'}}
        tab = DashboardTab(Api(), user, ':memory:', lambda: {'currency_symbol': 'KES'})
        self.assertTrue(tab._owner_dashboard())
        self.assertFalse(tab._void_btn.isHidden())
        self.assertFalse(hasattr(tab, '_ask_void_btn'))
        self.assertFalse(tab._trend_card.isHidden())
        tab.deleteLater()
        _ = QLabel
