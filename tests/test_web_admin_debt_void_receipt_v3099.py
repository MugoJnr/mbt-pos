"""v3.0.99 — Web Admin debt write-off / void / receipt permission matrix."""
from __future__ import annotations

from desktop.utils.security import has_permission


def _u(role: str) -> dict:
    return {'role': role}


def test_cashier_collect_yes_write_off_void_edit_no():
    assert has_permission(_u('cashier'), 'debt.collect') is True
    assert has_permission(_u('cashier'), 'debt.delete') is False
    assert has_permission(_u('cashier'), 'sales.void') is False
    assert has_permission(_u('cashier'), 'sales.edit') is False


def test_admin_write_off_void_view_yes_edit_no():
    assert has_permission(_u('admin'), 'debt.delete') is True
    assert has_permission(_u('admin'), 'debt.collect') is True
    assert has_permission(_u('admin'), 'sales.void') is True
    assert has_permission(_u('admin'), 'sales.view_all') is True
    assert has_permission(_u('admin'), 'sales.edit') is False


def test_superadmin_edit_yes():
    assert has_permission(_u('superadmin'), 'sales.edit') is True
    assert has_permission(_u('superadmin'), 'debt.delete') is True
    assert has_permission(_u('superadmin'), 'sales.void') is True


def test_web_has_perm_mirrors_security(monkeypatch):
    from flask import Flask, g
    from web import web_routes

    app = Flask(__name__)
    with app.app_context():
        g.current_user = {'role': 'cashier', 'id': 1}
        assert web_routes._has_perm('debt.delete') is False
        assert web_routes._has_perm('debt.collect') is True
        g.current_user = {'role': 'admin', 'id': 2}
        assert web_routes._has_perm('debt.delete') is True
        assert web_routes._has_perm('sales.void') is True
        assert web_routes._has_perm('sales.edit') is False


def test_write_off_route_message_allows_admin():
    import inspect
    from web.web_routes import write_off_debt_invoice
    src = inspect.getsource(write_off_debt_invoice)
    assert 'Super Admin only' not in src
    assert 'debt.delete' in src


def test_void_route_preserves_credit_payment_confirmation():
    import inspect
    from web.web_routes import void_sale_web
    src = inspect.getsource(void_sale_web)
    assert "sales.void" in src
    assert "force_with_payments" in src
    assert "pin" in src


def test_return_route_uses_atomic_domain_operation():
    import inspect
    from web.web_routes import return_sale_web
    src = inspect.getsource(return_sale_web)
    assert "sales.void" in src
    assert "api.return_sale" in src
    assert "refund_method" in src
    assert "pin" in src


def test_dashboard_exposes_admin_receipt_and_debt_actions():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    reports = (root / 'web' / 'dashboard-ui' / 'src' / 'routes' / 'reports.tsx').read_text(
        encoding='utf-8',
    )
    receipt = (
        root / 'web' / 'dashboard-ui' / 'src' / 'components'
        / 'receipt-admin-modal.tsx'
    ).read_text(encoding='utf-8')
    debt = (root / 'web' / 'dashboard-ui' / 'src' / 'routes' / 'debt.tsx').read_text(
        encoding='utf-8',
    )
    assert 'ReceiptAdminModal' in reports
    assert 'Void receipt' in receipt
    assert 'Return items' in receipt
    assert 'Reprint' in receipt
    assert 'force_with_payments' in receipt
    assert 'View linked receipt' in debt
    assert 'Payment history' in debt
    assert 'Add customer' in debt
    assert 'role === "admin" || role === "superadmin"' in debt
    audit = (root / 'web' / 'dashboard-ui' / 'src' / 'routes' / 'audit.tsx').read_text(
        encoding='utf-8',
    )
    assert 'GET<any[]>("/audit")' in audit
    assert 'Immutable activity history' in audit


def test_dashboard_exposes_admin_product_metadata_editor_without_stock_write():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    inventory = (
        root / 'web' / 'dashboard-ui' / 'src' / 'routes' / 'inventory.tsx'
    ).read_text(encoding='utf-8')
    assert 'Add product' in inventory
    assert 'Edit ${form.name}' in inventory
    assert 'Buying cost' in inventory
    assert 'Stock is not changed here' in inventory
    assert 'payload.stock' not in inventory
    assert 'canDelete' in inventory
    assert 'DEL<any>(`/products/${product.id}`)' in inventory
    assert 'from the catalogue' in inventory
    assert 'const canDelete = ["admin", "superadmin"].includes(role)' in inventory
