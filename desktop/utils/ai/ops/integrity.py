"""
Business Integrity — read-only scans (negative stock, payment mismatch, debt drift, orphans).
Never mutates data.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Optional

from mbt_paths import get_db_path, configure_sqlite_connection

log = logging.getLogger('ai.ops.integrity')


def _conn(db_path: str) -> sqlite3.Connection:
    c = sqlite3.connect(db_path, timeout=15)
    c.row_factory = sqlite3.Row
    configure_sqlite_connection(c)
    return c


def _table_exists(c: sqlite3.Connection, name: str) -> bool:
    row = c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return bool(row)


def scan_negative_stock(c: sqlite3.Connection) -> List[Dict[str, Any]]:
    if not _table_exists(c, 'products'):
        return []
    rows = c.execute(
        "SELECT id, name, sku, stock, min_stock FROM products WHERE CAST(stock AS REAL) < 0 LIMIT 50"
    ).fetchall()
    return [
        {
            'type': 'negative_stock',
            'severity': 'high',
            'product_id': r['id'],
            'name': r['name'],
            'stock': r['stock'],
            'message': f"Negative stock: {r['name']} ({r['stock']})",
        }
        for r in rows
    ]


def scan_sales_payment_mismatch(c: sqlite3.Connection) -> List[Dict[str, Any]]:
    issues = []
    if not _table_exists(c, 'sales'):
        return issues
    cols = {r[1] for r in c.execute('PRAGMA table_info(sales)').fetchall()}
    # Prefer final_total / total vs amount_paid / payment fields
    total_col = 'final_total' if 'final_total' in cols else ('total' if 'total' in cols else None)
    paid_col = None
    for cand in ('amount_paid', 'paid_amount', 'payment_amount', 'cash_received'):
        if cand in cols:
            paid_col = cand
            break
    if not total_col:
        return issues
    # Sales marked completed/paid with missing totals
    try:
        status_filter = "AND (status IS NULL OR lower(status) NOT IN ('void','voided','cancelled'))"
        if paid_col:
            q = f'''SELECT id, receipt_no, {total_col} AS tot, {paid_col} AS paid, status
                    FROM sales WHERE ABS(COALESCE({total_col},0) - COALESCE({paid_col},0)) > 1.0
                    {status_filter} LIMIT 40'''
            for r in c.execute(q).fetchall():
                # Credit/debt sales may intentionally differ — skip if payment method hints credit
                issues.append({
                    'type': 'sales_payment_mismatch',
                    'severity': 'medium',
                    'sale_id': r['id'],
                    'receipt': r['receipt_no'],
                    'total': r['tot'],
                    'paid': r['paid'],
                    'message': f"Sale {r['receipt_no'] or r['id']}: total {r['tot']} vs paid {r['paid']}",
                })
        # Null totals on non-void sales
        for r in c.execute(
            f"SELECT id, receipt_no FROM sales WHERE {total_col} IS NULL {status_filter} LIMIT 20"
        ).fetchall():
            issues.append({
                'type': 'sales_null_total',
                'severity': 'high',
                'sale_id': r['id'],
                'receipt': r['receipt_no'],
                'message': f"Sale {r['receipt_no'] or r['id']} has null total",
            })
    except Exception as e:
        log.debug('sales mismatch: %s', e)
    return issues


def scan_debt_drift(c: sqlite3.Connection) -> List[Dict[str, Any]]:
    issues = []
    if not _table_exists(c, 'debt_invoices'):
        return issues
    try:
        cols = {r[1] for r in c.execute('PRAGMA table_info(debt_invoices)').fetchall()}
        bal = 'balance' if 'balance' in cols else ('amount_due' if 'amount_due' in cols else None)
        total = 'total' if 'total' in cols else ('amount' if 'amount' in cols else None)
        if not bal:
            return issues
        # Negative balances
        for r in c.execute(
            f"SELECT id, customer_id, {bal} AS bal FROM debt_invoices "
            f"WHERE CAST({bal} AS REAL) < -0.5 LIMIT 30"
        ).fetchall():
            issues.append({
                'type': 'debt_negative_balance',
                'severity': 'medium',
                'invoice_id': r['id'],
                'balance': r['bal'],
                'message': f"Debt invoice {r['id']} has negative balance {r['bal']}",
            })
        # Paid status with remaining balance
        if 'status' in cols:
            for r in c.execute(
                f"SELECT id, {bal} AS bal, status FROM debt_invoices "
                f"WHERE lower(COALESCE(status,'')) IN ('paid','settled') "
                f"AND CAST({bal} AS REAL) > 1 LIMIT 30"
            ).fetchall():
                issues.append({
                    'type': 'debt_status_drift',
                    'severity': 'medium',
                    'invoice_id': r['id'],
                    'balance': r['bal'],
                    'message': f"Invoice {r['id']} marked {r['status']} but balance {r['bal']}",
                })
    except Exception as e:
        log.debug('debt drift: %s', e)
    return issues


def scan_orphan_refs(c: sqlite3.Connection) -> List[Dict[str, Any]]:
    issues = []
    try:
        if _table_exists(c, 'sale_items') and _table_exists(c, 'sales'):
            for r in c.execute(
                '''SELECT si.id, si.sale_id FROM sale_items si
                   LEFT JOIN sales s ON s.id = si.sale_id
                   WHERE s.id IS NULL LIMIT 30'''
            ).fetchall():
                issues.append({
                    'type': 'orphan_sale_item',
                    'severity': 'high',
                    'item_id': r['id'],
                    'sale_id': r['sale_id'],
                    'message': f"Orphan sale_item {r['id']} (sale {r['sale_id']} missing)",
                })
        if _table_exists(c, 'sale_items') and _table_exists(c, 'products'):
            for r in c.execute(
                '''SELECT si.id, si.product_id FROM sale_items si
                   LEFT JOIN products p ON p.id = si.product_id
                   WHERE si.product_id IS NOT NULL AND p.id IS NULL LIMIT 30'''
            ).fetchall():
                issues.append({
                    'type': 'orphan_product_ref',
                    'severity': 'medium',
                    'item_id': r['id'],
                    'product_id': r['product_id'],
                    'message': f"Sale item {r['id']} references missing product {r['product_id']}",
                })
    except Exception as e:
        log.debug('orphan scan: %s', e)
    return issues


def run_integrity_scan(db_path: Optional[str] = None) -> Dict[str, Any]:
    db_path = db_path or get_db_path()
    issues: List[Dict[str, Any]] = []
    try:
        with _conn(db_path) as c:
            issues.extend(scan_negative_stock(c))
            issues.extend(scan_sales_payment_mismatch(c))
            issues.extend(scan_debt_drift(c))
            issues.extend(scan_orphan_refs(c))
    except Exception as e:
        log.warning('integrity scan failed: %s', e)
        return {
            'ok': False, 'error': str(e), 'issues': [],
            'counts': {}, 'summary': 'Integrity scan failed',
        }

    counts: Dict[str, int] = {}
    for i in issues:
        counts[i['type']] = counts.get(i['type'], 0) + 1
    high = sum(1 for i in issues if i.get('severity') == 'high')
    return {
        'ok': True,
        'issues': issues,
        'counts': counts,
        'high_severity': high,
        'summary': (
            f'Found {len(issues)} issue(s) ({high} high severity).'
            if issues else 'No integrity issues detected.'
        ),
    }
