"""
MBT POS — Security & Permission Layer
MugoByte Technologies | mugobyte.com

Central authority for:
  • Role-based permission checks
  • Super-admin PIN verification
  • Action enforcement (cashier cannot touch stock, etc.)
"""
import hashlib, os, json, logging
logger = logging.getLogger('security')

# ── Roles ──────────────────────────────────────────────────────────────────────
from roles import (
    ROLE_CASHIER, ROLE_VIEWER, ROLE_MANAGER, ROLE_ADMIN, ROLE_SUPERADMIN,
    ALL_DESKTOP_TABS, TAB_PERMISSIONS_BY_ROLE,
    default_tab_permissions, is_superadmin_role, is_shop_admin_role,
    can_assign_role, sanitize_tab_permissions, role_display_name,
)

# What each role can do — granular action flags
_PERMISSIONS = {
    ROLE_CASHIER: {
        'sales.create', 'sales.view_own', 'sales.request_void', 'sales.request_backdate',
        'inventory.view', 'inventory.create', 'inventory.edit_info', 'inventory.receive',
        'reports.view_basic',
        'notes.own',
        'debt.create', 'debt.collect', 'debt.view_own',
        'consumption.create', 'consumption.request_void',
        'sales.variance_handle',
        'accounting.create_expenses',
        'supplier.pay', 'supplier.request',
    },
    ROLE_VIEWER: {
        'sales.view_all',
        'inventory.view', 'inventory.create', 'inventory.edit_info',
        'reports.view_all',
        'notes.view_all',
        'debt.view',
        'consumption.view_report',
        'reports.view_variance',
        'accounting.view', 'accounting.view_reports',
        'supplier.view',
    },
    ROLE_MANAGER: {
        'sales.create', 'sales.view_all', 'sales.void', 'sales.request_void', 'sales.request_backdate', 'sales.business_day',
        'inventory.view', 'inventory.create', 'inventory.edit_info', 'inventory.receive',
        'reports.view_all', 'reports.export',
        'notes.own', 'notes.view_all',
        'users.view',
        'settings.view',
        'debt.view', 'debt.create', 'debt.collect', 'debt.customer_manage',
        'consumption.create', 'consumption.request_void',
        'consumption.view_report', 'consumption.export',
        'sales.variance_handle', 'reports.view_variance',
        'accounting.view', 'accounting.view_reports', 'accounting.create_journal',
        'accounting.reverse_journal', 'accounting.create_expenses',
        'accounting.approve_expenses',
        'accounting.export',
        'ai_ops.view', 'ai_ops.heal_safe', 'ai_ops.support',
        'inventory.view_cost',
        'supplier.view', 'supplier.pay', 'supplier.request',
    },
    ROLE_ADMIN: {
        'sales.create', 'sales.view_all', 'sales.void', 'sales.request_void', 'sales.request_backdate', 'sales.business_day',
        'inventory.view', 'inventory.create', 'inventory.edit_info', 'inventory.receive',
        'inventory.delete',
        'reports.view_all', 'reports.export',
        'notes.own', 'notes.view_all',
        'users.view', 'users.create', 'users.edit', 'users.delete',
        'settings.view', 'settings.edit',
        'audit.view',
        'debt.view', 'debt.create', 'debt.collect',
        'debt.customer_manage', 'debt.cancel',
        'consumption.create', 'consumption.void', 'consumption.edit',
        'consumption.view_report', 'consumption.export',
        'sales.variance_handle', 'sales.variance_approve', 'reports.view_variance',
        'accounting.view', 'accounting.view_reports', 'accounting.create_journal',
        'accounting.reverse_journal', 'accounting.create_expenses',
        'accounting.approve_expenses',
        'accounting.close_period', 'accounting.edit_accounts', 'accounting.export',
        'ai_ops.view', 'ai_ops.heal_safe', 'ai_ops.support', 'ai_ops.analyze',
        'inventory.view_cost',
        'supplier.view', 'supplier.pay', 'supplier.request', 'supplier.manage',
    },
    ROLE_SUPERADMIN: {
        'sales.create', 'sales.view_all', 'sales.void', 'sales.request_void', 'sales.request_backdate', 'sales.edit',
        'sales.business_day',
        'inventory.view', 'inventory.create', 'inventory.edit_info', 'inventory.receive',
        'inventory.delete',
        'inventory.adjust_stock',          # ONLY superadmin can change stock directly
        'reports.view_all', 'reports.export',
        'notes.own', 'notes.view_all',
        'users.view', 'users.create', 'users.edit', 'users.delete',
        'settings.view', 'settings.edit',
        'audit.view', 'audit.clear',
        'license.manage',
        'security.override',
        'debt.view', 'debt.create', 'debt.collect',
        'debt.customer_manage', 'debt.cancel', 'debt.delete',
        'consumption.create', 'consumption.void', 'consumption.edit',
        'consumption.view_report', 'consumption.export',
        'sales.variance_handle', 'sales.variance_approve', 'reports.view_variance',
        'accounting.view', 'accounting.view_reports', 'accounting.create_journal',
        'accounting.reverse_journal', 'accounting.create_expenses',
        'accounting.approve_expenses',
        'accounting.close_period', 'accounting.edit_accounts', 'accounting.export',
        'ai_ops.view', 'ai_ops.heal_safe', 'ai_ops.support', 'ai_ops.analyze',
        'ai_ops.developer',
        'inventory.view_cost',
        'supplier.view', 'supplier.pay', 'supplier.request', 'supplier.manage',
    },
}

# These stay with the role. A checkbox cannot add them to a lower role.
NOT_GRANTABLE = {
    'inventory.adjust_stock', 'audit.clear', 'license.manage', 'security.override',
    'debt.delete', 'ai_ops.developer', 'sales.edit',
    'users.view', 'users.create', 'users.edit', 'users.delete',
    'settings.edit', 'accounting.edit_accounts', 'accounting.close_period',
}

_ACTION_LABELS = {
    'sales.create': 'Make a sale',
    'sales.view_own': 'View own sales',
    'sales.view_all': 'View every sale',
    'sales.void': 'Void a sale',
    'sales.request_void': 'Request a sale void',
    'sales.request_backdate': 'Request a backdated sale',
    'sales.business_day': 'Choose a business day',
    'sales.edit': 'Edit a posted sale',
    'inventory.view': 'View inventory',
    'inventory.view_cost': 'View product costs and valuation',
    'inventory.create': 'Create products',
    'inventory.edit_info': 'Edit product details',
    'inventory.receive': 'Receive supplier stock',
    'inventory.delete': 'Remove products',
    'inventory.adjust_stock': 'Adjust stock directly',
    'reports.view_basic': 'View the basic report',
    'reports.view_all': 'View management reports and profit',
    'reports.export': 'Export reports',
    'debt.view': 'View customer debt',
    'debt.view_own': 'View own customer debt',
    'debt.collect': 'Collect customer payments',
    'debt.create': 'Create customer debt',
    'debt.customer_manage': 'Manage customers',
    'debt.cancel': 'Resolve customer debt',
    'supplier.view': 'View supplier balances',
    'supplier.pay': 'Record supplier payments',
    'supplier.request': 'Request a delivery void or backdate',
    'supplier.manage': 'Edit, void, backdate, or return a delivery',
    'consumption.create': 'Record internal consumption',
    'consumption.edit': 'Correct internal consumption',
    'consumption.void': 'Void internal consumption',
    'consumption.request_void': 'Request a consumption void',
    'consumption.view_report': 'View consumption reports',
    'consumption.export': 'Export consumption',
    'accounting.view': 'View finance',
    'accounting.view_reports': 'View finance reports',
    'accounting.create_expenses': 'Record expenses',
    'accounting.approve_expenses': 'Approve expenses',
    'accounting.export': 'Export finance',
    'accounting.create_journal': 'Create a journal entry',
    'accounting.reverse_journal': 'Reverse a journal entry',
    'accounting.close_period': 'Close an accounting period',
    'accounting.edit_accounts': 'Edit the chart of accounts',
    'audit.view': 'View the audit log',
    'audit.clear': 'Clear the audit log',
    'settings.view': 'View settings',
    'settings.edit': 'Change system settings',
    'notes.own': 'Keep own notes',
    'notes.view_all': 'View every note',
    'reports.view_variance': 'View cash variance',
    'sales.variance_handle': 'Handle a cash variance',
    'sales.variance_approve': 'Approve a cash variance',
    'debt.delete': 'Delete customer debt',
    'license.manage': 'Manage the licence',
    'security.override': 'Override security controls',
    'users.view': 'View staff accounts',
    'users.create': 'Create staff accounts',
    'users.edit': 'Edit staff accounts',
    'users.delete': 'Deactivate staff accounts',
    'ai_ops.view': 'View shop assistant tools',
    'ai_ops.heal_safe': 'Run safe shop repairs',
    'ai_ops.support': 'Use shop assistant support',
    'ai_ops.analyze': 'Analyse shop activity',
    'ai_ops.developer': 'Use developer shop tools',
}


def dashboard_locked_to_today(user: dict) -> bool:
    """Cashiers work the current shop day. They do not browse other dashboard periods."""
    source = (user or {}).get('user') or user or {}
    role = str(source.get('role') or '').strip().lower()
    if source.get('id') and 'permission_grants' not in source and 'permission_denials' not in source:
        loaded = load_user_auth(source.get('id'))
        if loaded:
            role = loaded['role']
    if role != 'cashier':
        return False
    return 'sales.business_day' not in effective_actions(source)


def _known_actions() -> set:
    found = set()
    for actions in _PERMISSIONS.values():
        found |= set(actions)
    return found


def _parse_actions(value) -> set:
    if isinstance(value, str):
        try:
            value = json.loads(value or '[]')
        except (TypeError, ValueError):
            return set()
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def role_actions(role: str) -> set:
    return set(_PERMISSIONS.get((role or '').strip().lower()) or ())


def load_user_auth(user_id):
    """Fresh role and individual permissions. Inactive accounts are refused."""
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    try:
        from desktop.utils.api_client import _db
        db = _db()
        try:
            row = db.execute(
                "SELECT role, is_active, permission_grants, permission_denials FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
        finally:
            db.close()
    except Exception:
        logger.warning('permission load failed for user %s', user_id, exc_info=True)
        return None
    if not row or int(row['is_active'] or 0) != 1:
        return None
    return {
        'role': (row['role'] or '').strip().lower(),
        'permission_grants': _parse_actions(row['permission_grants']),
        'permission_denials': _parse_actions(row['permission_denials']),
    }


def permission_overrides(user_id):
    """Grants and denials for an active user. False when the account cannot sign in."""
    if not user_id:
        return None
    loaded = load_user_auth(user_id)
    if not loaded:
        return False
    return loaded['permission_grants'], loaded['permission_denials']


def client_actor(api) -> dict:
    """Role from the call, plus that account's grants and denials.

    The role is not replaced from the database. Tests set a role that can
    differ from the stored user, and a grant must not turn that role into
    another one.
    """
    role = (getattr(api, '_role', '') or '').lower()
    loaded = permission_overrides(getattr(api, '_user_id', None))
    if loaded is False:
        return {'role': ''}
    user = {'role': role}
    if isinstance(loaded, tuple):
        user['permission_grants'] = sorted(loaded[0])
        user['permission_denials'] = sorted(loaded[1])
    return user


_COST_FIELDS = (
    'unit_cost', 'line_total', 'cost_price', 'cost', 'average_cost',
    'gross_profit', 'profit', 'valuation', 'inventory_value',
)


def redact_cost_fields(payload):
    """Remove stored cost and profit figures. Invoice totals stay."""
    if isinstance(payload, list):
        for item in payload:
            redact_cost_fields(item)
        return payload
    if not isinstance(payload, dict):
        return payload
    for key in _COST_FIELDS:
        payload.pop(key, None)
    for key in ('lines', 'items', 'products', 'receipts'):
        rows = payload.get(key)
        if isinstance(rows, list):
            for row in rows:
                redact_cost_fields(row)
    return payload


def _resolved(user: dict):
    source = (user or {}).get('user') or user or {}
    role = str(source.get('role') or '').strip().lower()
    if source.get('id') and 'permission_grants' not in source and 'permission_denials' not in source:
        loaded = load_user_auth(source.get('id'))
        if not loaded:
            return '', set(), set()
        return loaded['role'], loaded['permission_grants'], loaded['permission_denials']
    return role, _parse_actions(source.get('permission_grants')), _parse_actions(source.get('permission_denials'))


def effective_actions(user: dict) -> set:
    """Role defaults, plus explicit grants, minus explicit denials.

    A Super Admin keeps the full Super Admin set. A denial beats a grant.
    An unknown action is never included.
    """
    role, grants, denials = _resolved(user)
    known = _known_actions()
    if role == ROLE_SUPERADMIN:
        return set(_PERMISSIONS[ROLE_SUPERADMIN])
    base = role_actions(role)
    if not base and role not in _PERMISSIONS:
        return set()
    extra = {item for item in grants if item in known and item not in NOT_GRANTABLE}
    removed = {item for item in denials if item in known}
    return (base - removed) | (extra - removed)


def has_permission(user: dict, action: str) -> bool:
    """An unknown role, an unknown action, or a missing account is denied."""
    action = str(action or '').strip()
    if action not in _known_actions():
        return False
    return action in effective_actions(user)


def sees_management_figures(user: dict) -> bool:
    return has_permission(user, 'reports.view_all') or has_permission(user, 'accounting.view')


def sees_product_cost(user: dict) -> bool:
    return has_permission(user, 'inventory.view_cost')


def permission_catalogue(role: str = '') -> list:
    """Every real action, grouped for User Control."""
    defaults = role_actions(role)
    groups = {}
    for action in sorted(_known_actions()):
        group = action.split('.', 1)[0].replace('_', ' ').title()
        groups.setdefault(group, []).append({
            'key': action,
            'label': _ACTION_LABELS.get(action, action.replace('.', ' · ').replace('_', ' ')),
            'grantable': action not in NOT_GRANTABLE,
            'inherited': action in defaults,
        })
    return [{'group': name, 'items': items} for name, items in groups.items()]


def clean_permission_change(actor: dict, target_role: str, grants, denials) -> dict:
    """Drop unknown, locked, and permissions the actor is not allowed to give."""
    target_role = (target_role or '').strip().lower()
    if target_role == ROLE_SUPERADMIN:
        return {'error': 'Super Admin access follows that role. It is not a set of checkboxes.', 'status': 400}
    if target_role not in _PERMISSIONS:
        return {'error': 'That role is not recognised.', 'status': 400}
    actor_set = effective_actions(actor)
    actor_role = _resolved(actor)[0]
    if actor_role not in (ROLE_ADMIN, ROLE_SUPERADMIN):
        return {'error': 'Only an administrator can change individual permissions.', 'status': 403}
    known = _known_actions()
    role_set = role_actions(target_role)
    clean_grants = []
    for item in sorted(_parse_actions(grants)):
        if item not in known or item in NOT_GRANTABLE or item in role_set:
            continue
        if actor_role != ROLE_SUPERADMIN and item not in actor_set:
            continue
        clean_grants.append(item)
    clean_denials = []
    for item in sorted(_parse_actions(denials)):
        if item in role_set and item in known:
            clean_denials.append(item)
    return {'permission_grants': clean_grants, 'permission_denials': clean_denials}


def require_permission(user: dict, action: str, parent_widget=None) -> bool:
    """
    Check permission and show an error dialog if denied.
    Returns True if allowed, False if denied.
    """
    if has_permission(user, action):
        return True
    from PyQt5.QtWidgets import QMessageBox
    role = (user.get('user') or user).get('role', 'cashier')
    try:
        from desktop.utils.audio_manager import play as _audio_play
        _audio_play('permission_denied')
    except Exception:
        pass
    QMessageBox.warning(
        parent_widget, 'Access Denied',
        f'Your role ({role}) does not have permission for this action.\n'
        f'Contact your system administrator.')
    logger.warning(f"Permission denied: user={user} action={action}")
    return False


# ── Super-admin PIN ────────────────────────────────────────────────────────────
# The PIN is hashed with PBKDF2 and stored in system_settings.
# Default PIN is set during setup wizard. Never stored in plain text.

def _pin_hash(pin: str) -> str:
    return hashlib.pbkdf2_hmac(
        'sha256', pin.encode(),
        b'MBT_POS_SUPERADMIN_SALT_2024', 200_000
    ).hex()


def set_superadmin_pin(pin: str, api) -> bool:
    """Hash and store the super-admin PIN."""
    try:
        h = _pin_hash(pin)
        api.update_settings({'superadmin_pin_hash': h})
        return True
    except Exception as e:
        logger.error(f"set_superadmin_pin: {e}")
        return False


def verify_superadmin_pin(pin: str, api, parent_widget=None,
                          log_attempt=True) -> bool:
    """
    Verify the PIN. Returns True on success.
    Logs every attempt (success or fail) for audit trail.
    """
    from PyQt5.QtWidgets import QMessageBox, QInputDialog, QLineEdit
    try:
        cfg = api.get_settings() or {}
        stored_hash = cfg.get('superadmin_pin_hash', '')
        if not stored_hash:
            QMessageBox.warning(parent_widget, 'Not Set',
                'Super-admin PIN has not been configured.\n'
                'Go to Settings → Security to set it.')
            return False
        ok = (_pin_hash(pin) == stored_hash)
        if log_attempt:
            from desktop.utils.api_client import _audit
            result_str = 'ok' if ok else 'fail'
            _audit(None, 'SYSTEM',
                   'SUPERADMIN_PIN_SUCCESS' if ok else 'SUPERADMIN_PIN_FAIL',
                   'security',
                   f'pin_attempt result={result_str}')
        if not ok:
            QMessageBox.critical(parent_widget, 'Wrong PIN',
                'Incorrect Super-Admin PIN.')
        return ok
    except Exception as e:
        logger.error(f"verify_superadmin_pin: {e}")
        return False


def collect_superadmin_pin(api, parent_widget=None, reason='') -> str:
    """Return a verified Super-Admin PIN, or an empty string if it was not accepted.

    A signed-in Super Admin returns a session marker. The server still checks
    the authenticated role and does not accept that marker from anyone else.
    """
    from PyQt5.QtWidgets import QInputDialog, QLineEdit
    if (getattr(api, '_role', None) or '').lower() == 'superadmin':
        from desktop.utils.api_client import _audit
        _audit(getattr(api, '_user_id', None), getattr(api, '_username', None) or 'superadmin',
               'SUPERADMIN_SESSION_AUTH', 'security', f'pin_skipped reason={reason or "action"}')
        return 'session-authorized'
    auto = (os.environ.get('MBT_AUTO_SUPERADMIN_PIN') or '').strip()
    if auto:
        return auto if verify_superadmin_pin(auto, api, parent_widget, log_attempt=True) else ''
    prompt = 'Enter Super-Admin PIN'
    if reason:
        prompt += f'\n({reason})'
    pin, ok = QInputDialog.getText(
        parent_widget, 'Super-Admin Authorization', prompt,
        QLineEdit.Password)
    if not ok or not pin:
        return ''
    if not verify_superadmin_pin(pin, api, parent_widget, log_attempt=True):
        return ''
    return pin


def ask_superadmin_pin(api, parent_widget=None, reason='') -> bool:
    """
    Show PIN entry dialog and verify.
    A signed-in Super Admin is already authorized and is not asked again.
    """
    from PyQt5.QtWidgets import QInputDialog, QLineEdit
    if (getattr(api, '_role', None) or '').lower() == 'superadmin':
        from desktop.utils.api_client import _audit
        _audit(getattr(api, '_user_id', None), getattr(api, '_username', None) or 'superadmin',
               'SUPERADMIN_SESSION_AUTH', 'security', f'pin_skipped reason={reason or "action"}')
        return True
    auto = (os.environ.get('MBT_AUTO_SUPERADMIN_PIN') or '').strip()
    if auto:
        return verify_superadmin_pin(auto, api, parent_widget, log_attempt=True)
    prompt = 'Enter Super-Admin PIN'
    if reason:
        prompt += f'\n({reason})'
    pin, ok = QInputDialog.getText(
        parent_widget, 'Super-Admin Authorization', prompt,
        QLineEdit.Password)
    if not ok or not pin:
        return False
    return verify_superadmin_pin(pin, api, parent_widget, log_attempt=True)


def can_edit_sales(user: dict) -> bool:
    """True if user may edit completed sale receipts (superadmin / sales.edit)."""
    return has_permission(user, 'sales.edit')


def can_void_sales(user: dict) -> bool:
    """True if user may approve a void (manager / admin / superadmin)."""
    return has_permission(user, 'sales.void')


def can_request_void(user: dict) -> bool:
    """True if user may ask for a void. The sale stays completed until approval."""
    return has_permission(user, 'sales.request_void')


def can_set_business_day(user: dict) -> bool:
    """True if user may select/backdate the POS business day (manager+)."""
    return has_permission(user, 'sales.business_day')


def can_delete_debt(user: dict) -> bool:
    """True if user may delete/write-off open debts (superadmin only)."""
    return has_permission(user, 'debt.delete')


class DeleteDebtDialog:
    """Simple confirm dialog: required reason for clearing an open debt."""

    @staticmethod
    def ask(parent_widget=None, *, invoice_number: str = '',
            customer_name: str = '', balance: float = 0.0,
            amount_paid: float = 0.0, currency: str = 'KES') -> str:
        """
        Returns reason string, or None if cancelled.
        """
        from PyQt5.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
            QDialogButtonBox, QMessageBox,
        )
        from PyQt5.QtCore import Qt
        from desktop.utils.theme import C, apply_themed_dialog
        from desktop.utils.select_controls import CONTROL_HEIGHT

        paid = float(amount_paid or 0)
        bal = float(balance or 0)
        is_partial = paid > 0.009

        dlg = QDialog(parent_widget)
        dlg.setWindowTitle('Write Off Debt' if is_partial else 'Delete Debt')
        dlg.setMinimumWidth(440)
        apply_themed_dialog(dlg)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        title = QLabel('Write Off Debt' if is_partial else 'Delete Debt')
        title.setStyleSheet(
            f"color:{C['text']};font-size:18px;font-weight:700;background:transparent;")
        lay.addWidget(title)

        bal_txt = f"{currency} {bal:,.2f}"
        paid_txt = f"{currency} {paid:,.2f}"
        if is_partial:
            hint = QLabel(
                f'Clear remaining balance on invoice <b>{invoice_number or "?"}</b>'
                f' ({customer_name or "customer"}).<br><br>'
                f'Paid kept: <b>{paid_txt}</b> &nbsp;|&nbsp; '
                f'Write off: <b>{bal_txt}</b><br><br>'
                f'Payments kept. Remaining balance cleared. '
                f'Stock not restocked for partial debts.<br>'
                f'Requires Super-Admin PIN.'
            )
        else:
            hint = QLabel(
                f'This will cancel unpaid invoice <b>{invoice_number or "?"}</b>'
                f' ({customer_name or "customer"}) — balance {bal_txt}.<br><br>'
                f'If the debt is linked to a POS credit sale, that sale is voided '
                f'and stock is restored. Requires Super-Admin PIN.'
            )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.RichText)
        hint.setStyleSheet(
            f"color:{C['text2']};font-size:13px;background:transparent;")
        lay.addWidget(hint)

        reason_lbl = QLabel('Reason (required)')
        reason_lbl.setStyleSheet(
            f"color:{C['muted']};font-size:12px;font-weight:600;background:transparent;")
        lay.addWidget(reason_lbl)
        reason_edit = QLineEdit()
        reason_edit.setPlaceholderText(
            'Why is this remaining balance being written off?'
            if is_partial else
            'Why is this debt being deleted?'
        )
        reason_edit.setMinimumHeight(CONTROL_HEIGHT)
        lay.addWidget(reason_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setText('Continue')
        buttons.rejected.connect(dlg.reject)

        def _accept():
            if not reason_edit.text().strip():
                QMessageBox.warning(
                    dlg, 'Required',
                    'Enter a reason to clear this debt.')
                reason_edit.setFocus()
                return
            dlg.accept()

        buttons.accepted.connect(_accept)
        lay.addWidget(buttons)

        if dlg.exec_() != QDialog.Accepted:
            return None
        return reason_edit.text().strip() or None


def prompt_delete_debt(api, parent_widget, invoice_id: int, *,
                       invoice_number: str = '', customer_name: str = '',
                       balance: float = 0.0, amount_paid: float = 0.0,
                       currency: str = 'KES',
                       user: dict = None) -> bool:
    """
    Reason → super-admin PIN → delete_debt_invoice (void unpaid / write-off partial).
    Returns True when the debt was cleared successfully.
    """
    from PyQt5.QtWidgets import QMessageBox

    if user is not None and not require_permission(user, 'debt.delete', parent_widget):
        return False

    reason = DeleteDebtDialog.ask(
        parent_widget,
        invoice_number=invoice_number,
        customer_name=customer_name,
        balance=balance,
        amount_paid=amount_paid,
        currency=currency,
    )
    if not reason:
        return False

    label = invoice_number or f'#{invoice_id}'
    pin_reason = (
        f'Write off debt {label}' if float(amount_paid or 0) > 0.009
        else f'Delete debt {label}'
    )
    if not ask_superadmin_pin(api, parent_widget, reason=pin_reason):
        return False

    res = api.delete_debt_invoice(int(invoice_id), reason)
    if res and res.get('success'):
        msg = res.get('message') or 'Debt cleared.'
        if res.get('restocked') and res.get('restock'):
            lines = [
                f"  • {r.get('product_name') or ('#' + str(r.get('product_id')))}: "
                f"+{float(r.get('quantity') or 0):g}"
                for r in res['restock']
            ]
            msg += '\n\nStock restored:\n' + '\n'.join(lines)
        title = (
            'Debt Written Off' if res.get('mode') == 'write_off'
            else 'Debt Deleted'
        )
        try:
            from desktop.utils.quiet_ui import info_toast
            info_toast(parent_widget, f"{title}: {msg.splitlines()[0]}")
        except Exception:
            QMessageBox.information(parent_widget, title, msg)
        return True

    QMessageBox.critical(
        parent_widget, 'Error',
        (res or {}).get('error', 'Failed to clear debt.'))
    return False


class VoidSaleDialog:
    """Themed void dialog: receipt + ReasonSelect (Other → Please specify)."""

    @staticmethod
    def ask(parent_widget=None, receipt_prefill: str = '', *, direct: bool = False) -> tuple:
        """
        Returns (receipt, reason) or (None, None) if cancelled.
        Reason is the catalog label, or 'Other: <detail>' (+ optional notes).
        """
        from PyQt5.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
            QDialogButtonBox, QMessageBox,
        )
        from desktop.utils.theme import C, apply_themed_dialog
        from desktop.utils.option_lists import VOID_REASONS
        from desktop.utils.select_controls import ReasonSelect, CONTROL_HEIGHT

        dlg = QDialog(parent_widget)
        dlg.setWindowTitle('Void receipt' if direct else 'Request a void')
        dlg.setMinimumWidth(460)
        apply_themed_dialog(dlg)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        title = QLabel('Void this receipt' if direct else 'Request a void')
        title.setStyleSheet(
            f"color:{C['text']};font-size:18px;font-weight:700;background:transparent;")
        lay.addWidget(title)

        hint = QLabel(
            'This voids the receipt now. No approval request is created.'
            if direct else
            'This sends the sale to Approvals. The sale stays completed, '
            'and stock stays as it is, until a manager approves it with the Super-Admin PIN.')
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color:{C['text2']};font-size:13px;background:transparent;")
        lay.addWidget(hint)

        rcpt_lbl = QLabel('Receipt number')
        rcpt_lbl.setStyleSheet(
            f"color:{C['muted']};font-size:12px;font-weight:600;background:transparent;")
        lay.addWidget(rcpt_lbl)
        receipt_edit = QLineEdit()
        receipt_edit.setPlaceholderText('e.g. RCP-20260605-0089')
        receipt_edit.setMinimumHeight(CONTROL_HEIGHT)
        if receipt_prefill:
            receipt_edit.setText(receipt_prefill.strip())
        lay.addWidget(receipt_edit)

        reason_lbl = QLabel('Void reason')
        reason_lbl.setStyleSheet(
            f"color:{C['muted']};font-size:12px;font-weight:600;background:transparent;")
        lay.addWidget(reason_lbl)
        reason_sel = ReasonSelect(dlg, reasons=VOID_REASONS, height=CONTROL_HEIGHT)
        lay.addWidget(reason_sel)

        notes_lbl = QLabel('Notes (optional)')
        notes_lbl.setStyleSheet(
            f"color:{C['muted']};font-size:12px;background:transparent;")
        lay.addWidget(notes_lbl)
        notes = QLineEdit()
        notes.setPlaceholderText('Optional notes…')
        notes.setMinimumHeight(CONTROL_HEIGHT)
        lay.addWidget(notes)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setText('Void receipt' if direct else 'Send request')
        buttons.rejected.connect(dlg.reject)

        def _accept():
            rcpt = receipt_edit.text().strip()
            if not rcpt:
                QMessageBox.warning(dlg, 'Required', 'Enter a receipt number.')
                receipt_edit.setFocus()
                return
            if not reason_sel.is_valid():
                QMessageBox.warning(dlg, 'Required', reason_sel.validation_error())
                return
            dlg.accept()

        buttons.accepted.connect(_accept)
        lay.addWidget(buttons)
        reason_sel.refresh_theme()

        if dlg.exec_() != QDialog.Accepted:
            return None, None
        reason = reason_sel.value().strip()
        extra = notes.text().strip()
        if extra:
            reason = f'{reason} — {extra}' if reason else extra
        return receipt_edit.text().strip(), reason or None


def prompt_void_sale(api, parent_widget=None, receipt_prefill: str = '') -> bool:
    """Ask for a void. The sale stays completed until Approvals accepts it."""
    from PyQt5.QtWidgets import QMessageBox
    from desktop.utils.api_client import _db

    user = getattr(parent_widget, 'user', None) or {}
    if getattr(api, '_role', None):
        user = {'role': api._role}
    if not can_request_void(user):
        QMessageBox.warning(
            parent_widget, 'Not allowed',
            'You cannot request a void.')
        return False

    direct = (user.get('role') or '').lower() == 'superadmin'
    receipt, reason = VoidSaleDialog.ask(
        parent_widget, receipt_prefill=receipt_prefill, direct=direct)
    if not receipt or not reason:
        return False

    db = _db()
    row = db.execute(
        "SELECT id, status FROM sales WHERE receipt_number=?", (receipt,)
    ).fetchone()
    db.close()
    if not row:
        QMessageBox.warning(parent_widget, 'Not Found',
                            f'No sale found with receipt: {receipt}')
        return False
    if row['status'] == 'voided':
        QMessageBox.warning(parent_widget, 'Already Voided',
                            f'Sale {receipt} is already voided.')
        return False

    if direct:
        res = api.void_sale(row['id'], reason.strip())
    else:
        res = api.request_sale_void(row['id'], reason.strip())
    if res and res.get('success'):
        if direct:
            try:
                from backend.void_requests import close_open_for_sale
                link = _db()
                api._ensure_approval_table(link)
                close_open_for_sale(link, int(row['id']), getattr(api, '_username', '') or 'superadmin')
                link.commit()
                link.close()
            except Exception:
                pass
            QMessageBox.information(
                parent_widget, 'Receipt voided',
                f'Sale {receipt} is voided. Stock was put back once.')
        elif res.get('duplicate'):
            QMessageBox.information(
                parent_widget, 'Already requested',
                f'Sale {receipt} is already waiting for approval. It is still completed.')
        else:
            QMessageBox.information(
                parent_widget, 'Request sent',
                f'Sale {receipt} was sent for approval. It stays completed until a manager approves it.')
        return True

    QMessageBox.critical(parent_widget, 'Error',
                         (res or {}).get('error', 'Could not send the void request.'))
    return False
