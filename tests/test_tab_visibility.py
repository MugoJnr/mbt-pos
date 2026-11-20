"""Saved tab access controls the menu. A role name does not add a revoked tab."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from roles import visible_tabs


def test_cashier_without_inventory_does_not_see_it():
    tabs = visible_tabs('cashier', ['dashboard', 'sales', 'receipts'])
    assert 'inventory' not in tabs
    assert 'sales' in tabs


def test_cashier_with_inventory_sees_it():
    tabs = visible_tabs('cashier', ['dashboard', 'sales', 'inventory'])
    assert 'inventory' in tabs


def test_admin_revoked_tab_stays_hidden():
    tabs = visible_tabs('admin', ['dashboard', 'sales', 'receipts'])
    assert 'inventory' not in tabs
    assert 'license' not in tabs
    assert 'security' not in tabs


def test_superadmin_keeps_the_shop_menu():
    tabs = visible_tabs('superadmin', [])
    assert 'inventory' in tabs
    assert 'license' in tabs
    assert 'security' in tabs


def test_unknown_role_sees_nothing():
    assert visible_tabs('platform_admin', ['inventory', 'sales']) == []


def test_cashier_cannot_keep_owner_tabs():
    tabs = visible_tabs('cashier', ['sales', 'license', 'security', 'ai_ops'])
    assert tabs == ['sales']
