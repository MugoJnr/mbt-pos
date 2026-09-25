"""Generic stocktake and reconciliation.

Expected quantity is the snapshot taken when the count starts, plus every
stock movement recorded after that moment. Physical counts never change
on-hand stock until an authorized user applies an adjustment.
"""
from __future__ import annotations

import json
from datetime import datetime


REASONS = (
    'Routine stocktake',
    'Month-end',
    'Week-end',
    'Shift handover',
    'Suspected discrepancy',
    'Audit',
    'Management request',
    'Other',
)

SCOPES = ('all', 'categories', 'products', 'cycle')
MODES = ('normal', 'blind')


def ensure_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS stocktakes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_json TEXT DEFAULT '{}',
            counting_mode TEXT NOT NULL DEFAULT 'normal',
            reason TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
            allow_sales INTEGER NOT NULL DEFAULT 1,
            location_name TEXT DEFAULT '',
            created_by_id INTEGER,
            created_by_name TEXT DEFAULT '',
            started_at TEXT NOT NULL,
            submitted_at TEXT,
            completed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS stocktake_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stocktake_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            sku TEXT DEFAULT '',
            barcode TEXT DEFAULT '',
            category TEXT DEFAULT '',
            unit TEXT DEFAULT '',
            cost_price REAL DEFAULT 0,
            sell_price REAL DEFAULT 0,
            baseline_qty REAL NOT NULL,
            counted_qty REAL,
            counted_by_id INTEGER,
            counted_by_name TEXT DEFAULT '',
            counted_at TEXT,
            line_status TEXT DEFAULT 'open',
            variance_reason TEXT DEFAULT '',
            adjusted INTEGER DEFAULT 0,
            UNIQUE(stocktake_id, product_id)
        );
        CREATE TABLE IF NOT EXISTS stocktake_counts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            line_id INTEGER NOT NULL,
            stocktake_id INTEGER NOT NULL,
            quantity REAL NOT NULL,
            kind TEXT NOT NULL DEFAULT 'count',
            user_id INTEGER,
            username TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )


def _now() -> str:
    # Match SQLite CURRENT_TIMESTAMP so movement comparisons stay ordered.
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _reference(conn) -> str:
    day = datetime.now().strftime('%Y%m%d')
    row = conn.execute(
        "SELECT COUNT(*) FROM stocktakes WHERE reference LIKE ?",
        (f'ST-{day}-%',),
    ).fetchone()
    n = int(row[0] or 0) + 1
    return f'ST-{day}-{n:04d}'


def start_stocktake(conn, *, name, scope_type, scope_ids, counting_mode,
                    reason, allow_sales, user_id, username, location_name='') -> dict:
    ensure_schema(conn)
    scope_type = (scope_type or 'all').strip().lower()
    if scope_type not in SCOPES:
        return {'error': 'Choose all products, categories, selected products, or a cycle count.'}
    mode = (counting_mode or 'normal').strip().lower()
    if mode not in MODES:
        mode = 'normal'
    name = (name or '').strip() or 'Stocktake'
    reason = (reason or '').strip()
    if len(reason) < 3:
        return {'error': 'Choose a reason for this stocktake.'}
    products = _products_for_scope(conn, scope_type, scope_ids or [])
    if not products:
        return {'error': 'No active products match this stocktake.'}
    started = _now()
    ref = _reference(conn)
    cur = conn.execute(
        "INSERT INTO stocktakes (reference, name, scope_type, scope_json, counting_mode, "
        "reason, status, allow_sales, location_name, created_by_id, created_by_name, started_at) "
        "VALUES (?,?,?,?,?,?, 'IN_PROGRESS', ?,?,?,?,?)",
        (
            ref, name, scope_type, json.dumps({'ids': list(scope_ids or [])}),
            mode, reason, 1 if allow_sales else 0, location_name or '',
            user_id, username or '', started,
        ),
    )
    sid = int(cur.lastrowid)
    for product in products:
        conn.execute(
            "INSERT INTO stocktake_lines (stocktake_id, product_id, product_name, sku, "
            "barcode, category, unit, cost_price, sell_price, baseline_qty) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                sid, int(product['id']), product['name'] or '',
                product['sku'] or '', product['barcode'] or '',
                product['category'] or '', product['unit'] or '',
                float(product['cost_price'] or 0), float(product['price'] or 0),
                float(product['stock'] or 0),
            ),
        )
    conn.commit()
    return {'success': True, 'id': sid, 'reference': ref, 'products': len(products)}


def _products_for_scope(conn, scope_type, scope_ids):
    base = (
        "SELECT id, name, sku, barcode, category, unit, cost_price, price, stock "
        "FROM products WHERE COALESCE(is_active,1)=1"
    )
    if scope_type == 'all':
        return conn.execute(base + " ORDER BY name").fetchall()
    ids = [str(x).strip() for x in scope_ids if str(x).strip()]
    if not ids:
        return []
    if scope_type == 'categories':
        marks = ','.join('?' for _ in ids)
        return conn.execute(
            base + f" AND category IN ({marks}) ORDER BY name", ids,
        ).fetchall()
    marks = ','.join('?' for _ in ids)
    limit = ''
    params = ids
    if scope_type == 'cycle':
        limit = ' LIMIT ?'
        params = ids + [max(1, min(len(ids), 500))]
    return conn.execute(
        base + f" AND id IN ({marks}) ORDER BY name{limit}", params,
    ).fetchall()


def record_count(conn, line_id, quantity, *, user_id, username, recount=False) -> dict:
    ensure_schema(conn)
    line = conn.execute(
        "SELECT l.*, s.status AS session_status FROM stocktake_lines l "
        "JOIN stocktakes s ON s.id=l.stocktake_id WHERE l.id=?",
        (int(line_id),),
    ).fetchone()
    if not line:
        return {'error': 'That count line was not found.'}
    status = (line['session_status'] or '')
    open_states = (
        ('IN_PROGRESS', 'RECOUNT_REQUIRED', 'SUBMITTED', 'UNDER_REVIEW')
        if recount else ('IN_PROGRESS', 'RECOUNT_REQUIRED')
    )
    if status not in open_states:
        return {'error': 'This stocktake is not open for counting.'}
    if not recount and line['counted_qty'] is not None:
        owner = line['counted_by_id']
        if owner and user_id and int(owner) != int(user_id):
            return {
                'error': (
                    f"{line['counted_by_name'] or 'Another counter'} already counted "
                    f"{line['product_name']}. Ask a reviewer for a recount."
                ),
            }
    try:
        qty = round(float(quantity), 4)
    except (TypeError, ValueError):
        return {'error': 'Enter the quantity you counted.'}
    if qty < 0:
        return {'error': 'A physical count cannot be negative.'}
    kind = 'recount' if recount else 'count'
    stamp = _now()
    conn.execute(
        "INSERT INTO stocktake_counts (line_id, stocktake_id, quantity, kind, user_id, username, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (int(line_id), int(line['stocktake_id']), qty, kind, user_id, username or '', stamp),
    )
    conn.execute(
        "UPDATE stocktake_lines SET counted_qty=?, counted_by_id=?, counted_by_name=?, "
        "counted_at=?, line_status=? WHERE id=?",
        (qty, user_id, username or '', stamp, 'recounted' if recount else 'counted', int(line_id)),
    )
    conn.commit()
    return {'success': True, 'line_id': int(line_id), 'quantity': qty}


def movements_since(conn, product_id, started_at) -> list:
    rows = conn.execute(
        "SELECT movement_type, qty_change, reference, reason, username, created_at "
        "FROM stock_movements WHERE product_id=? AND created_at>=? ORDER BY id",
        (int(product_id), started_at),
    ).fetchall()
    return [dict(row) for row in rows]


def expected_qty(baseline, movements) -> float:
    total = float(baseline or 0)
    for row in movements:
        total += float(row.get('qty_change') or 0)
    return round(total, 4)


def reconcile(conn, stocktake_id, *, reveal=True) -> dict:
    ensure_schema(conn)
    session = conn.execute(
        "SELECT * FROM stocktakes WHERE id=?", (int(stocktake_id),)
    ).fetchone()
    if not session:
        return {'error': 'Stocktake not found.'}
    session = dict(session)
    blind = (session.get('counting_mode') or '') == 'blind' and not reveal
    lines = conn.execute(
        "SELECT * FROM stocktake_lines WHERE stocktake_id=? ORDER BY product_name",
        (int(stocktake_id),),
    ).fetchall()
    out = []
    matched = short_n = excess_n = open_n = 0
    short_cost = excess_cost = 0.0
    for line in lines:
        line = dict(line)
        moves = movements_since(conn, line['product_id'], session['started_at'])
        expected = expected_qty(line['baseline_qty'], moves)
        counted = line['counted_qty']
        if counted is None:
            open_n += 1
            variance = None
            state = 'Not counted'
        else:
            variance = round(float(counted) - expected, 4)
            if abs(variance) < 0.0001:
                state = 'Matched'
                matched += 1
            elif variance < 0:
                state = 'Shortage'
                short_n += 1
                short_cost += abs(variance) * float(line['cost_price'] or 0)
            else:
                state = 'Excess'
                excess_n += 1
                excess_cost += variance * float(line['cost_price'] or 0)
        cost_impact = None if variance is None else round(variance * float(line['cost_price'] or 0), 2)
        retail_impact = None if variance is None else round(variance * float(line['sell_price'] or 0), 2)
        item = {
            'line_id': line['id'],
            'product_id': line['product_id'],
            'product_name': line['product_name'],
            'sku': line['sku'],
            'unit': line['unit'],
            'category': line['category'],
            'baseline_qty': line['baseline_qty'],
            'physical_qty': counted,
            'variance_reason': line['variance_reason'] or '',
            'counted_by_name': line['counted_by_name'] or '',
            'counted_at': line['counted_at'] or '',
            'adjusted': int(line['adjusted'] or 0),
            'status': state,
            'cost_price': line['cost_price'],
            'sell_price': line['sell_price'],
            'barcode': line.get('barcode') or '',
            'variance_pct': (
                None if variance is None or abs(expected) < 0.0001
                else round((variance / expected) * 100, 2)
            ) if reveal else None,
        }
        if reveal:
            item.update({
                'expected_qty': expected,
                'variance_qty': variance,
                'cost_impact': cost_impact,
                'retail_impact': retail_impact,
                'movements': moves,
            })
        out.append(item)
    return {
        'success': True,
        'stocktake': {
            'id': session['id'],
            'reference': session['reference'],
            'name': session['name'],
            'status': session['status'],
            'counting_mode': session['counting_mode'],
            'reason': session['reason'],
            'started_at': session['started_at'],
            'created_by_name': session['created_by_name'],
            'blind': (session.get('counting_mode') or '') == 'blind',
        },
        'summary': {
            'products': len(out),
            'counted': len(out) - open_n,
            'matched': matched if reveal else None,
            'shortages': short_n if reveal else None,
            'excess': excess_n if reveal else None,
            'shortage_cost': round(short_cost, 2) if reveal else None,
            'excess_cost': round(excess_cost, 2) if reveal else None,
            'net_cost': round(excess_cost - short_cost, 2) if reveal else None,
        },
        'lines': out,
    }


def mark_status(conn, stocktake_id, status) -> dict:
    ensure_schema(conn)
    if status not in {
        'IN_PROGRESS', 'SUBMITTED', 'UNDER_REVIEW', 'RECOUNT_REQUIRED',
        'APPROVED', 'ADJUSTED', 'CANCELLED',
    }:
        return {'error': 'Unknown stocktake status.'}
    stamp = _now()
    fields = ['status=?']
    params = [status]
    if status == 'SUBMITTED':
        fields.append('submitted_at=?')
        params.append(stamp)
    if status in ('ADJUSTED', 'CANCELLED', 'APPROVED'):
        fields.append('completed_at=?')
        params.append(stamp)
    params.append(int(stocktake_id))
    cur = conn.execute(
        f"UPDATE stocktakes SET {', '.join(fields)} WHERE id=?",
        params,
    )
    if cur.rowcount != 1:
        return {'error': 'Stocktake not found.'}
    conn.commit()
    return {'success': True, 'status': status}


def list_stocktakes(conn, status: str = '') -> list:
    ensure_schema(conn)
    sql = (
        "SELECT s.*, "
        "(SELECT COUNT(*) FROM stocktake_lines l WHERE l.stocktake_id=s.id) AS products, "
        "(SELECT COUNT(*) FROM stocktake_lines l WHERE l.stocktake_id=s.id "
        " AND l.counted_qty IS NOT NULL) AS counted "
        "FROM stocktakes s"
    )
    params = []
    if status:
        sql += " WHERE s.status=?"
        params.append(status)
    sql += " ORDER BY s.id DESC LIMIT 200"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def set_variance_reason(conn, line_id, reason: str) -> dict:
    ensure_schema(conn)
    reason = (reason or '').strip()
    if len(reason) < 2:
        return {'error': 'Enter a reason for this difference.'}
    cur = conn.execute(
        "UPDATE stocktake_lines SET variance_reason=? WHERE id=?",
        (reason[:240], int(line_id)),
    )
    if cur.rowcount != 1:
        return {'error': 'Count line not found.'}
    conn.commit()
    return {'success': True}


def request_recount(conn, stocktake_id, line_id=None) -> dict:
    ensure_schema(conn)
    marked = mark_status(conn, int(stocktake_id), 'RECOUNT_REQUIRED')
    if marked.get('error'):
        return marked
    if line_id:
        conn.execute(
            "UPDATE stocktake_lines SET line_status='recount_required' WHERE id=? AND stocktake_id=?",
            (int(line_id), int(stocktake_id)),
        )
        conn.commit()
    return {'success': True, 'status': 'RECOUNT_REQUIRED'}


def mark_line_adjusted(conn, line_id) -> bool:
    cur = conn.execute(
        "UPDATE stocktake_lines SET adjusted=1, line_status='adjusted' "
        "WHERE id=? AND COALESCE(adjusted,0)=0",
        (int(line_id),),
    )
    conn.commit()
    return cur.rowcount == 1


def compare_stocktakes(conn, left_id, right_id) -> dict:
    left = reconcile(conn, left_id, reveal=True)
    right = reconcile(conn, right_id, reveal=True)
    if left.get('error') or right.get('error'):
        return {'error': left.get('error') or right.get('error')}
    right_by_product = {row['product_id']: row for row in right['lines']}
    rows = []
    repeated_short = repeated_excess = 0
    for row in left['lines']:
        other = right_by_product.get(row['product_id'])
        if not other:
            continue
        lv = row.get('variance_qty')
        rv = other.get('variance_qty')
        if lv is not None and rv is not None and lv < 0 and rv < 0:
            repeated_short += 1
        if lv is not None and rv is not None and lv > 0 and rv > 0:
            repeated_excess += 1
        rows.append({
            'product_name': row['product_name'],
            'unit': row['unit'],
            'left_expected': row.get('expected_qty'),
            'right_expected': other.get('expected_qty'),
            'left_physical': row.get('physical_qty'),
            'right_physical': other.get('physical_qty'),
            'left_variance': lv,
            'right_variance': rv,
        })
    return {
        'success': True,
        'left': left['stocktake'],
        'right': right['stocktake'],
        'repeated_shortages': repeated_short,
        'repeated_excess': repeated_excess,
        'lines': rows,
    }


def export_workbook(conn, stocktake_id) -> bytes:
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    data = reconcile(conn, stocktake_id, reveal=True)
    if data.get('error'):
        raise ValueError(data['error'])
    session = data['stocktake']
    summary = data['summary']
    wb = Workbook()

    def _sheet(title, headers, rows):
        ws = wb.active if wb.active.title == 'Sheet' and wb.active.max_row == 1 and not wb.active['A1'].value else wb.create_sheet()
        ws.title = title[:31]
        header_font = Font(bold=True, color='FFFFFF')
        fill = PatternFill('solid', fgColor='1F4E79')
        for col, header in enumerate(headers, 1):
            cell = ws.cell(1, col, header)
            cell.font = header_font
            cell.fill = fill
        for r, row in enumerate(rows, 2):
            for c, value in enumerate(row, 1):
                ws.cell(r, c, value)
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, len(rows)+1)}"
        ws.freeze_panes = 'A2'
        for col in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(col)].width = 18
        return ws

    _sheet('Summary', ['Field', 'Value'], [
        ['Stocktake', session['name']],
        ['Reference', session['reference']],
        ['Status', session['status']],
        ['Reason', session['reason']],
        ['Started by', session['created_by_name']],
        ['Started at', session['started_at']],
        ['Products', summary['products']],
        ['Counted', summary['counted']],
        ['Matched', summary['matched']],
        ['Shortages', summary['shortages']],
        ['Excess', summary['excess']],
        ['Shortage at cost', summary['shortage_cost']],
        ['Excess at cost', summary['excess_cost']],
        ['Net cost variance', summary['net_cost']],
    ])
    _sheet('Product Counts', [
        'Product', 'SKU', 'Barcode', 'Category', 'Unit', 'Expected', 'Physical',
        'Variance', 'Variance %', 'Cost impact', 'Retail impact', 'Counted by',
        'Counted at', 'Status', 'Reason',
    ], [[
        row['product_name'], row['sku'], row.get('barcode') or '', row['category'],
        row['unit'], row.get('expected_qty'), row.get('physical_qty'),
        row.get('variance_qty'), row.get('variance_pct'), row.get('cost_impact'),
        row.get('retail_impact'), row['counted_by_name'], row['counted_at'],
        row['status'], row['variance_reason'],
    ] for row in data['lines']])
    movements = []
    recounts = []
    for row in data['lines']:
        for move in row.get('movements') or []:
            movements.append([
                row['product_name'], move.get('movement_type'), move.get('qty_change'),
                move.get('reference'), move.get('reason'), move.get('username'),
                move.get('created_at'),
            ])
        history = conn.execute(
            "SELECT quantity, kind, username, created_at FROM stocktake_counts "
            "WHERE line_id=? ORDER BY id",
            (row['line_id'],),
        ).fetchall()
        for entry in history:
            recounts.append([
                row['product_name'], entry['kind'], entry['quantity'],
                entry['username'], entry['created_at'],
            ])
    _sheet('Stock Movements', [
        'Product', 'Type', 'Qty change', 'Reference', 'Reason', 'User', 'When',
    ], movements)
    _sheet('Recounts', ['Product', 'Kind', 'Quantity', 'User', 'When'], recounts)
    _sheet('Adjustments', [
        'Product', 'Physical', 'Expected', 'Variance', 'Adjusted', 'Reason',
    ], [[
        row['product_name'], row.get('physical_qty'), row.get('expected_qty'),
        row.get('variance_qty'), 'Yes' if row['adjusted'] else 'No', row['variance_reason'],
    ] for row in data['lines'] if row['adjusted']])
    audit = conn.execute(
        "SELECT created_at, username, action, details FROM audit_log "
        "WHERE module='stocktake' AND details LIKE ? ORDER BY id",
        (f"%{session['reference']}%",),
    ).fetchall()
    _sheet('Audit Trail', ['When', 'User', 'Action', 'Details'], [
        [row['created_at'], row['username'], row['action'], row['details']] for row in audit
    ])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
