"""
Sensitive spreadsheet / finance PIN policy for MBT POS.

Design decision — one Super-Admin PIN (not a separate export password):
We reuse the existing Super-Admin PIN set/changed in Security (and Settings →
Security) via ``set_superadmin_pin`` / ``superadmin_pin_hash``. A second
“export password” would be forgotten, rarely rotated, and diverge from the PIN
already required for voids, stock adjust, and overrides. If the PIN is not
configured, sensitive export and finance views refuse with a clear “set
Super-Admin PIN in Security first” message — never export unlocked as a
fallback.

Workbook protection honesty (openpyxl):
MS Excel “password to open” (file encryption) is not what openpyxl provides.
We apply workbook structure lock + per-sheet protect with the same PIN so casual
editing / sheet add-remove is blocked; LibreOffice/Excel may still open the
file without a gate. UI tooltips must say this clearly.

Session cache: after a successful verify, cache authorization and the verified
PIN for workbook protection for 20 minutes in this process only (no disk).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger('export_security')

# Process-local session after successful Super-Admin PIN (exports + sensitive views).
EXPORT_PIN_SESSION_SECONDS = 20 * 60

WORKBOOK_PROTECTION_TOOLTIP = (
    'Protected with your Super-Admin PIN (workbook/sheet lock via openpyxl). '
    'This is not Microsoft Excel “password to open” file encryption — '
    'Excel/LibreOffice can still open the file; structure and cells are locked.'
)

PIN_NOT_CONFIGURED_MSG = (
    'Super-Admin PIN is not configured.\n\n'
    'Set it in Security → Super-Admin PIN (or Settings → Security) before '
    'exporting sensitive spreadsheets or opening protected finance views.\n\n'
    'Exports are never written unlocked as a fallback.'
)

_session_until: float = 0.0
_session_pin: str = ''


def clear_export_pin_session() -> None:
    """Clear the in-process export/view PIN session (tests / logout)."""
    global _session_until, _session_pin
    _session_until = 0.0
    _session_pin = ''


def export_pin_session_active() -> bool:
    return bool(_session_pin) and time.monotonic() < _session_until


def _remember_session(pin: str) -> None:
    global _session_until, _session_pin
    _session_pin = str(pin or '')
    _session_until = time.monotonic() + EXPORT_PIN_SESSION_SECONDS


def is_superadmin_pin_configured(api) -> bool:
    """True when ``superadmin_pin_hash`` is stored in system settings."""
    try:
        cfg = api.get_settings() or {}
        return bool(cfg.get('superadmin_pin_hash'))
    except Exception as e:
        logger.error('is_superadmin_pin_configured: %s', e)
        return False


def _warn_not_configured(parent_widget=None) -> None:
    from PyQt5.QtWidgets import QMessageBox
    QMessageBox.warning(parent_widget, 'PIN Required', PIN_NOT_CONFIGURED_MSG)


def require_superadmin_pin_for_export(
    api,
    parent_widget=None,
    reason: str = 'Sensitive spreadsheet export',
) -> Optional[str]:
    """
    Prompt + verify Super-Admin PIN for a sensitive export.

    Returns the verified PIN (for workbook protection) on success, or None if
    cancelled / not configured / wrong PIN. Uses the 20-minute session cache
    when still valid so repeated exports in the same process skip re-prompt.
    """
    if export_pin_session_active():
        return _session_pin

    if not is_superadmin_pin_configured(api):
        _warn_not_configured(parent_widget)
        return None

    from desktop.utils.security import prompt_superadmin_pin, verify_superadmin_pin

    pin = prompt_superadmin_pin(parent_widget, reason=reason)
    if not pin:
        return None
    if not verify_superadmin_pin(pin, api, parent_widget, log_attempt=True):
        return None
    _remember_session(pin)
    return pin


def require_superadmin_pin_session(
    api,
    parent_widget=None,
    reason: str = 'Sensitive finance view',
) -> bool:
    """
    Same gate as export, but callers only need authorization (not the PIN).
    Used for backdate, period close, net-worth / P&L views, etc.
    """
    return require_superadmin_pin_for_export(api, parent_widget, reason=reason) is not None
