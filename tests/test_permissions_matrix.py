"""Permission matrix + role tab defaults — production gate."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from roles import (
    ROLE_CASHIER, ROLE_VIEWER, ROLE_MANAGER, ROLE_ADMIN, ROLE_SUPERADMIN,
    default_tab_permissions, sanitize_tab_permissions, can_assign_role,
)
from desktop.utils.security import (
    has_permission, can_void_sales, can_edit_sales, can_delete_debt,
    can_set_business_day,
)


def _user(role: str) -> dict:
    return {'user': {'role': role, 'username': role}}


class PermissionMatrixTests(unittest.TestCase):
    def test_cashier_cannot_void_edit_or_delete_debt(self):
        u = _user(ROLE_CASHIER)
        self.assertFalse(can_void_sales(u))
        self.assertFalse(can_edit_sales(u))
        self.assertFalse(can_delete_debt(u))
        self.assertFalse(can_set_business_day(u))
        self.assertTrue(has_permission(u, 'sales.create'))

    def test_manager_can_void_not_edit(self):
        u = _user(ROLE_MANAGER)
        self.assertTrue(can_void_sales(u))
        self.assertFalse(can_edit_sales(u))
        self.assertFalse(can_delete_debt(u))
        self.assertTrue(can_set_business_day(u))

    def test_admin_can_void_not_edit_stock(self):
        u = _user(ROLE_ADMIN)
        self.assertTrue(can_void_sales(u))
        self.assertFalse(can_edit_sales(u))
        self.assertFalse(has_permission(u, 'inventory.adjust_stock'))
        self.assertFalse(can_delete_debt(u))

    def test_superadmin_full_sales_and_debt(self):
        u = _user(ROLE_SUPERADMIN)
        self.assertTrue(can_void_sales(u))
        self.assertTrue(can_edit_sales(u))
        self.assertTrue(can_delete_debt(u))
        self.assertTrue(has_permission(u, 'inventory.adjust_stock'))
        self.assertTrue(has_permission(u, 'license.manage'))

    def test_viewer_is_read_only_sales(self):
        u = _user(ROLE_VIEWER)
        self.assertFalse(has_permission(u, 'sales.create'))
        self.assertTrue(has_permission(u, 'sales.view_all'))
        self.assertTrue(has_permission(u, 'reports.view_all'))

    def test_tab_defaults(self):
        self.assertEqual(default_tab_permissions(ROLE_CASHIER), ['dashboard', 'sales'])
        self.assertIn('security', default_tab_permissions(ROLE_SUPERADMIN))
        self.assertNotIn('security', default_tab_permissions(ROLE_ADMIN))
        self.assertNotIn('license', default_tab_permissions(ROLE_ADMIN))

    def test_sanitize_strips_owner_tabs(self):
        dirty = ['dashboard', 'sales', 'security', 'license', 'ai_ops']
        cleaned = sanitize_tab_permissions(ROLE_CASHIER, dirty)
        self.assertEqual(cleaned, ['dashboard', 'sales'])
        admin = sanitize_tab_permissions(ROLE_ADMIN, dirty)
        self.assertNotIn('security', admin)
        self.assertNotIn('license', admin)
        self.assertIn('ai_ops', admin)

    def test_role_assignment_rules(self):
        self.assertTrue(can_assign_role(ROLE_SUPERADMIN, ROLE_ADMIN))
        self.assertTrue(can_assign_role(ROLE_ADMIN, ROLE_CASHIER))
        self.assertFalse(can_assign_role(ROLE_ADMIN, ROLE_SUPERADMIN))
        self.assertFalse(can_assign_role(ROLE_MANAGER, ROLE_ADMIN))

    def test_web_manager_respects_real_tab_permissions(self):
        from web.web_routes import _user_can
        manager = {
            'role': ROLE_MANAGER,
            'tab_permissions': [
                'dashboard', 'sales', 'inventory', 'consumption', 'debt',
            ],
        }
        self.assertTrue(_user_can('inventory', manager))
        self.assertTrue(_user_can('debt', manager))
        self.assertFalse(_user_can('reports', manager))
        self.assertFalse(_user_can('users', manager))
        self.assertFalse(_user_can('backup', manager))

    def test_web_admin_tabs_cannot_be_unchecked(self):
        from web.web_routes import _user_can
        admin = {'role': ROLE_ADMIN, 'tab_permissions': []}
        self.assertTrue(_user_can('sales', admin))
        self.assertTrue(_user_can('reports', admin))
        self.assertTrue(_user_can('users', admin))


if __name__ == '__main__':
    unittest.main()
