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
        'sales.variance_handle',
    },
    ROLE_VIEWER: {
        'sales.view_all',
        'inventory.view',
        'reports.view_all',
        'notes.view_all',
        'debt.view',
        'consumption.view_report',
        'reports.view_variance',
        'accounting.view', 'accounting.view_reports',
    },
    ROLE_MANAGER: {
        'sales.create', 'sales.view_all', 'sales.void',
        'inventory.view', 'inventory.create', 'inventory.edit_info',
        'reports.view_all', 'reports.export',
        'notes.own', 'notes.view_all',
        'users.view',
        'settings.view',
        'debt.view', 'debt.create', 'debt.collect', 'debt.customer_manage',
        'consumption.create', 'consumption.view_report', 'consumption.export',
        'sales.variance_handle', 'reports.view_variance',
        'accounting.view', 'accounting.view_reports', 'accounting.create_journal',
        'accounting.reverse_journal', 'accounting.approve_expenses',
        'accounting.export',
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
        'consumption.create', 'consumption.void',
        'consumption.view_report', 'consumption.export',
        'sales.variance_handle', 'sales.variance_approve', 'reports.view_variance',
        'accounting.view', 'accounting.view_reports', 'accounting.create_journal',
        'accounting.reverse_journal', 'accounting.approve_expenses',
        'accounting.close_period', 'accounting.edit_accounts', 'accounting.export',
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
        'consumption.create', 'consumption.void',
        'consumption.view_report', 'consumption.export',
        'sales.variance_handle', 'sales.variance_approve', 'reports.view_variance',
        'accounting.view', 'accounting.view_reports', 'accounting.create_journal',
        'accounting.reverse_journal', 'accounting.approve_expenses',
        'accounting.close_period', 'accounting.edit_accounts', 'accounting.export',
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

    Automation: set env MBT_AUTO_SUPERADMIN_PIN (e.g. 1110) to skip the dialog.
    """
    from PyQt5.QtWidgets import QInputDialog, QLineEdit
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


def can_void_sales(user: dict) -> bool:
    """True if user may void completed sales (manager / admin / superadmin)."""
    return has_permission(user, 'sales.void')


class VoidSaleDialog:
    """Themed void dialog: receipt + ReasonSelect (Other → Please specify)."""

    @staticmethod
    def ask(parent_widget=None, receipt_prefill: str = '') -> tuple:
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
        dlg.setWindowTitle('Void Sale')
        dlg.setMinimumWidth(460)
        apply_themed_dialog(dlg)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        title = QLabel('Void Sale')
        title.setStyleSheet(
            f"color:{C['text']};font-size:18px;font-weight:700;background:transparent;")
        lay.addWidget(title)

        hint = QLabel(
            'Cancel a completed sale and restore stock. '
            'Requires Super-Admin PIN after you confirm the reason.')
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
            ok_btn.setText('Continue')
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
    """
    Prompt for receipt, standardized void reason, and super-admin PIN;
    void the sale if confirmed. Returns True when a sale was voided successfully.
    """
    from PyQt5.QtWidgets import QMessageBox
    from desktop.utils.api_client import _db

    receipt, reason = VoidSaleDialog.ask(parent_widget, receipt_prefill=receipt_prefill)
    if not receipt or not reason:
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
    if res and res.get('error') == 'credit_payments_exist':
        paid = float(res.get('debt_paid_total') or 0)
        msg = res.get('message') or (
            f'This credit sale has debt payments totaling {paid:,.2f} already collected.\n\n'
            f'Voiding will cancel the remaining balance. Collected amounts must be '
            f'refunded manually if applicable.\n\nProceed with void?')
        confirm = QMessageBox.warning(
            parent_widget, 'Credit Sale Has Payments',
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return False
        res = api.void_sale(row['id'], reason.strip(), force_with_payments=True)

    if res and res.get('success'):
        extra = res.get('warning') or ''
        QMessageBox.information(
            parent_widget, 'Voided',
            f'Sale {receipt} has been voided.\nStock has been restored.'
            + (f'\n\n{extra}' if extra else ''))
        return True

    QMessageBox.critical(parent_widget, 'Error',
                         (res or {}).get('error', 'Failed to void sale.'))
    return False
