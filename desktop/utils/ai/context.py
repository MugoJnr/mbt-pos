"""
Context engine — minimum DB context filtered by role permissions.

Cashiers never receive payroll/accounting payloads. Honors desktop.utils.security.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from desktop.utils.ai.security import scrub_context
from desktop.utils.security import has_permission
from desktop.utils.ai.prompts import domain_for_module

log = logging.getLogger('ai.context')

# Module → required permission(s) for rich context (any match)
_MODULE_PERMS = {
    'sales': ['sales.create', 'sales.view_own', 'sales.view_all'],
    'inventory': ['inventory.view'],
    'consumption': ['consumption.view_report', 'consumption.create'],
    'debt': ['debt.view', 'debt.view_own', 'debt.create'],
    'accounting': ['accounting.view', 'accounting.view_reports'],
    'reports': ['reports.view_basic', 'reports.view_all'],
    'dashboard': ['sales.view_own', 'sales.view_all', 'reports.view_basic', 'reports.view_all'],
}


def _role(user: dict) -> str:
    return (user.get('user') or user).get('role', 'cashier')


def _uid(user: dict) -> str:
    u = user.get('user') or user
    return str(u.get('id') or u.get('user_id') or u.get('username') or '')


def _allowed_module(user: dict, module: str) -> bool:
    perms = _MODULE_PERMS.get(module)
    if not perms:
        return True
    return any(has_permission(user, p) for p in perms)


def build_context(
    api,
    user: dict,
    module: str,
    *,
    max_chars: int = 10000,
) -> Dict[str, Any]:
    """
    Build a compact, permission-filtered context snapshot for the prompt.
    Never includes passwords/tokens (scrubbed).
    """
    module = (module or 'dashboard').lower()
    role = _role(user)
    ctx: Dict[str, Any] = {
        'module': module,
        'domain': domain_for_module(module),
        'role': role,
        'today': str(date.today()),
        'shop': {},
        'snapshot': {},
        'notes': [],
    }

    try:
        cfg = api.get_settings() if hasattr(api, 'get_settings') else {}
        if isinstance(cfg, dict):
            ctx['shop'] = {
                'name': cfg.get('shop_name') or cfg.get('business_name') or '',
                'currency': cfg.get('currency_symbol') or 'KES',
            }
    except Exception as e:
        log.debug('settings context: %s', e)

    if not _allowed_module(user, module):
        ctx['notes'].append('Limited context: role cannot access this module\'s data.')
        return scrub_context(ctx)

    snap = ctx['snapshot']

    # Always-safe light dashboard bits for permitted users
    try:
        if module in ('dashboard', 'sales', 'reports') and (
            has_permission(user, 'sales.view_all')
            or has_permission(user, 'sales.view_own')
            or has_permission(user, 'reports.view_basic')
            or has_permission(user, 'reports.view_all')
        ):
            today = str(date.today())
            sales = []
            if hasattr(api, 'get_sales'):
                sales = api.get_sales(start=today, end=today) or []
            if has_permission(user, 'sales.view_own') and not has_permission(user, 'sales.view_all'):
                uid = _uid(user)
                uname = (user.get('user') or user).get('username', '')
                sales = [
                    s for s in sales
                    if str(s.get('user_id', '')) == uid
                    or str(s.get('cashier', '')).lower() == str(uname).lower()
                ]
            # Compact
            total = 0.0
            for s in sales[:200]:
                try:
                    total += float(s.get('total') or s.get('final_total') or 0)
                except Exception:
                    pass
            snap['today_sales'] = {
                'count': len(sales),
                'revenue': round(total, 2),
                'sample': [
                    {
                        'receipt': s.get('receipt_no') or s.get('id'),
                        'total': s.get('total') or s.get('final_total'),
                        'status': s.get('status'),
                    }
                    for s in sales[:8]
                ],
            }
    except Exception as e:
        log.debug('sales context: %s', e)

    try:
        if module in ('dashboard', 'inventory', 'purchasing') and has_permission(user, 'inventory.view'):
            products = api.get_products() if hasattr(api, 'get_products') else []
            low = []
            for p in products or []:
                try:
                    qty = float(p.get('quantity') or p.get('stock') or 0)
                    reorder = float(p.get('reorder_level') or p.get('min_stock') or 0)
                except Exception:
                    continue
                if reorder > 0 and qty <= reorder:
                    low.append({
                        'name': p.get('name'),
                        'sku': p.get('sku') or p.get('barcode'),
                        'qty': qty,
                        'reorder_level': reorder,
                    })
                if len(low) >= 15:
                    break
            snap['low_stock'] = low
            snap['product_count'] = len(products or [])
    except Exception as e:
        log.debug('inventory context: %s', e)

    try:
        if module in ('dashboard', 'debt', 'customers') and (
            has_permission(user, 'debt.view') or has_permission(user, 'debt.view_own')
        ):
            if hasattr(api, 'get_debt_summary'):
                ds = api.get_debt_summary() or {}
                # Strip anything odd
                snap['debt_summary'] = {
                    k: ds.get(k)
                    for k in (
                        'total_outstanding', 'outstanding', 'collected_today',
                        'customers_with_debt', 'overdue_count', 'overdue',
                    )
                    if k in ds
                } or {k: v for k, v in list(ds.items())[:8]
                      if k.lower() not in ('password', 'token')}
    except Exception as e:
        log.debug('debt context: %s', e)

    try:
        if module == 'accounting' and has_permission(user, 'accounting.view'):
            # Minimal — avoid dumping full GL
            snap['accounting'] = {
                'available': True,
                'hint': 'User may open Accounting tab for GL/P&L/TB. Figures not auto-loaded.',
            }
        elif module == 'accounting':
            ctx['notes'].append('Accounting context denied for this role.')
    except Exception:
        pass

    # Size guard
    import json
    raw = json.dumps(ctx, default=str)
    if len(raw) > max_chars:
        ctx['snapshot'] = {k: ctx['snapshot'][k] for k in list(ctx['snapshot'])[:3]}
        ctx['notes'].append('Context truncated for size.')

    return scrub_context(ctx)
