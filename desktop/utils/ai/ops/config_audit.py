"""Config Auditor — printer/tax/payment/M-Pesa/backup/permissions warnings."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

log = logging.getLogger('ai.ops.config_audit')


def audit_config(api, user: dict = None) -> Dict[str, Any]:
    warnings: List[Dict[str, Any]] = []
    try:
        cfg = api.get_settings() if hasattr(api, 'get_settings') else {}
    except Exception as e:
        return {
            'ok': False, 'warnings': [{
                'area': 'settings', 'severity': 'high',
                'message': f'Cannot read settings: {e}',
            }],
            'summary': 'Config audit failed',
        }
    cfg = cfg or {}

    def warn(area, severity, message):
        warnings.append({'area': area, 'severity': severity, 'message': message})

    # Shop identity
    if not (cfg.get('shop_name') or cfg.get('business_name')):
        warn('shop', 'medium', 'Shop name is not set.')

    # Tax
    tax = cfg.get('tax_rate', cfg.get('vat_rate', None))
    if tax is None:
        warn('tax', 'low', 'Tax/VAT rate not configured — confirm if tax-exempt.')
    else:
        try:
            t = float(tax)
            if t < 0 or t > 40:
                warn('tax', 'medium', f'Tax rate looks unusual: {t}%')
        except Exception:
            warn('tax', 'medium', f'Tax rate is not numeric: {tax}')

    # Printer
    printer = cfg.get('printer_name') or cfg.get('receipt_printer') or ''
    if not printer:
        warn('printer', 'medium', 'Receipt printer not configured.')

    # Payment methods
    pm = cfg.get('payment_methods') or cfg.get('enabled_payments')
    if pm is not None and (isinstance(pm, list) and len(pm) == 0):
        warn('payment', 'high', 'No payment methods enabled.')

    # M-Pesa
    mpesa_keys = [k for k in cfg.keys() if 'mpesa' in str(k).lower() or 'daraja' in str(k).lower()]
    if mpesa_keys:
        # Check presence without revealing secrets
        has_consumer = any(
            cfg.get(k) for k in cfg
            if 'consumer' in str(k).lower() and 'mpesa' in str(k).lower()
        )
        # Soft: if any mpesa key exists but looks empty
        empty_mpesa = [
            k for k in mpesa_keys
            if not str(cfg.get(k) or '').strip()
            and 'token' not in str(k).lower()
        ]
        if empty_mpesa:
            warn('mpesa', 'medium', f'M-Pesa settings incomplete ({len(empty_mpesa)} empty fields).')
    else:
        warn('mpesa', 'low', 'M-Pesa not configured (OK if unused).')

    # Backup
    if not cfg.get('backup_enabled') and not cfg.get('auto_backup'):
        warn('backup', 'medium', 'Automatic backup does not appear enabled.')

    # Currency
    if not cfg.get('currency_symbol'):
        warn('currency', 'low', 'Currency symbol missing (default KES assumed).')

    # Permissions / users — light check
    try:
        if hasattr(api, 'get_users'):
            users = api.get_users() or []
            if not users:
                warn('permissions', 'high', 'No users found in system.')
            else:
                roles = [(u.get('role') or '').lower() for u in users]
                if 'superadmin' not in roles and 'admin' not in roles:
                    warn('permissions', 'high', 'No admin/superadmin user found.')
                cashiers = sum(1 for r in roles if r == 'cashier')
                if cashiers == 0:
                    warn('permissions', 'low', 'No cashier accounts — OK for owner-only shops.')
    except Exception as e:
        warn('permissions', 'low', f'Could not audit users: {e}')

    # Theme / AI — informational
    if not cfg.get('theme') and not cfg.get('ui_theme'):
        warn('ui', 'low', 'Theme preference not saved yet.')

    high = sum(1 for w in warnings if w['severity'] == 'high')
    return {
        'ok': True,
        'warnings': warnings,
        'high_severity': high,
        'summary': (
            f'{len(warnings)} config warning(s) ({high} high).'
            if warnings else 'Configuration looks healthy.'
        ),
    }
