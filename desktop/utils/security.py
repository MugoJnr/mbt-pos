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
        'sales.create', 'sales.view_own',
        'inventory.view',
        'reports.view_basic',
        'notes.own',
        'debt.create', 'debt.collect', 'debt.view_own',
    },
    ROLE_VIEWER: {
        'sales.view_all',
        'inventory.view',
        'reports.view_all',
        'notes.view_all',
        'debt.view',
    },
    ROLE_MANAGER: {
        'sales.create', 'sales.view_all',
        'inventory.view', 'inventory.create', 'inventory.edit_info',
        'reports.view_all', 'reports.export',
        'notes.own', 'notes.view_all',
        'users.view',
        'settings.view',
        'debt.view', 'debt.create', 'debt.collect', 'debt.customer_manage',
    },
    ROLE_ADMIN: {
        'sales.create', 'sales.view_all', 'sales.void',
        'inventory.view', 'inventory.create', 'inventory.edit_info',
        'reports.view_all', 'reports.export',
        'notes.own', 'notes.view_all',
        'users.view', 'users.create', 'users.edit',
        'settings.view', 'settings.edit',
        'audit.view',
        'debt.view', 'debt.create', 'debt.collect',
        'debt.customer_manage', 'debt.cancel',
    },
    ROLE_SUPERADMIN: {
        'sales.create', 'sales.view_all', 'sales.void', 'sales.edit',
        'inventory.view', 'inventory.create', 'inventory.edit_info',
        'inventory.adjust_stock',          # ONLY superadmin can change stock
        'reports.view_all', 'reports.export',
        'notes.own', 'notes.view_all',
        'users.view', 'users.create', 'users.edit', 'users.delete',
        'settings.view', 'settings.edit',
        'audit.view', 'audit.clear',
        'license.manage',
        'security.override',
        'debt.view', 'debt.create', 'debt.collect',
        'debt.customer_manage', 'debt.cancel',
    },
}


def has_permission(user: dict, action: str) -> bool:
    """Check if a user dict (from login response) has a given permission."""
    role = (user.get('user') or user).get('role', ROLE_CASHIER)
    allowed = _PERMISSIONS.get(role, _PERMISSIONS[ROLE_CASHIER])
    return action in allowed


def require_permission(user: dict, action: str, parent_widget=None) -> bool:
    """
    Check permission and show an error dialog if denied.
    Returns True if allowed, False if denied.
    """
    if has_permission(user, action):
        return True
    from PyQt5.QtWidgets import QMessageBox
    role = (user.get('user') or user).get('role', 'cashier')
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


def ask_superadmin_pin(api, parent_widget=None, reason='') -> bool:
    """
    Show PIN entry dialog and verify.
    Returns True if correct PIN entered.
    """
    from PyQt5.QtWidgets import QInputDialog, QLineEdit
    prompt = 'Enter Super-Admin PIN'
    if reason:
        prompt += f'\n({reason})'
    pin, ok = QInputDialog.getText(
        parent_widget, 'Super-Admin Authorization', prompt,
        QLineEdit.Password)
    if not ok or not pin:
        return False
    return verify_superadmin_pin(pin, api, parent_widget, log_attempt=True)


def can_void_sales(user: dict) -> bool:
    """True if user may void completed sales (admin / superadmin)."""
    role = (user.get('user') or user).get('role', ROLE_CASHIER)
    return role in (ROLE_ADMIN, ROLE_SUPERADMIN)


def prompt_void_sale(api, parent_widget=None, receipt_prefill: str = '') -> bool:
    """
    Prompt for receipt, reason, and super-admin PIN; void the sale if confirmed.
    Returns True when a sale was voided successfully.
    """
    from PyQt5.QtWidgets import QInputDialog, QMessageBox
    from desktop.utils.api_client import _db

    receipt = (receipt_prefill or '').strip()
    if not receipt:
        receipt, ok = QInputDialog.getText(
            parent_widget, 'Void Sale',
            'Receipt number to void:\n(e.g. RCP-20260605-0089)')
        if not ok or not receipt.strip():
            return False
        receipt = receipt.strip()

    reason, ok = QInputDialog.getText(
        parent_widget, 'Void Reason', f'Reason for voiding {receipt}:')
    if not ok or not reason.strip():
        QMessageBox.warning(parent_widget, 'Required', 'A reason is required.')
        return False

    if not ask_superadmin_pin(api, parent_widget, reason=f'Void {receipt}'):
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

    res = api.void_sale(row['id'], reason.strip())
    if res and res.get('success'):
        QMessageBox.information(
            parent_widget, 'Voided',
            f'Sale {receipt} has been voided.\nStock has been restored.')
        return True

    QMessageBox.critical(parent_widget, 'Error',
                         res.get('error', 'Failed to void sale.'))
    return False
