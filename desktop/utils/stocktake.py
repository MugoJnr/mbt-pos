"""A stocktake stores counts first. Applying it changes stock once."""
from __future__ import annotations


def ensure_stocktake(db) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS stocktakes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS stocktake_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stocktake_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            counted_qty REAL NOT NULL,
            UNIQUE(stocktake_id, product_id)
        )"""
    )
    line_cols = {row[1] for row in db.execute("PRAGMA table_info(stocktake_lines)")}
    if 'snapshot_qty' not in line_cols:
        db.execute("ALTER TABLE stocktake_lines ADD COLUMN snapshot_qty REAL")


def start_stocktake(db, name: str) -> dict:
    name = (name or '').strip()
    if not name:
        return {'error': 'Enter a stocktake name'}
    ensure_stocktake(db)
    db.execute("INSERT INTO stocktakes (name) VALUES (?)", (name,))
    return {'success': True, 'id': db.execute('SELECT last_insert_rowid()').fetchone()[0]}


def record_count(db, stocktake_id: int, product_id: int, counted_qty: float) -> dict:
    ensure_stocktake(db)
    from desktop.utils.quantities import QuantityError, parse_quantity
    product = db.execute(
        "SELECT name, unit FROM products WHERE id=?", (int(product_id),)
    ).fetchone()
    if not product:
        return {'error': 'Product was not found'}
    unit = product['unit'] if hasattr(product, 'keys') else product[1]
    name = product['name'] if hasattr(product, 'keys') else product[0]
    try:
        counted = parse_quantity(counted_qty, unit, allow_zero=True)
    except QuantityError as exc:
        message = str(exc)
        if 'whole units' in message:
            return {'error': f"'{name}' is sold in whole units.", 'status': 400}
        if 'negative' in message:
            return {'error': 'Count cannot be negative'}
        return {'error': message, 'status': 400}
    header = db.execute(
        "SELECT status FROM stocktakes WHERE id=?", (int(stocktake_id),)
    ).fetchone()
    if not header:
        return {'error': 'Stocktake was not found'}
    if header[0] != 'open':
        return {'error': 'This stocktake is already closed'}
    before = db.execute("SELECT stock FROM products WHERE id=?", (int(product_id),)).fetchone()
    if not before:
        return {'error': 'Product was not found'}
    snapshot = round(float(before[0] or 0), 4)
    db.execute(
        "INSERT INTO stocktake_lines (stocktake_id, product_id, counted_qty, snapshot_qty) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT(stocktake_id, product_id) DO UPDATE SET "
        "counted_qty=excluded.counted_qty, "
        "snapshot_qty=COALESCE(stocktake_lines.snapshot_qty, excluded.snapshot_qty)",
        (int(stocktake_id), int(product_id), counted, snapshot),
    )
    after = db.execute("SELECT stock FROM products WHERE id=?", (int(product_id),)).fetchone()
    return {
        'success': True,
        'stock_unchanged': float(before[0] or 0) == float(after[0] or 0),
        'stock': float(after[0] or 0),
    }


def apply_stocktake(db, stocktake_id: int, username: str = '', user_id=None, business_date: str = '', backdate_reason: str = '') -> dict:
    """Set each counted product once. A second apply does nothing."""
    ensure_stocktake(db)
    db.execute('BEGIN IMMEDIATE')
    header = db.execute(
        "SELECT id, status FROM stocktakes WHERE id=?", (int(stocktake_id),)
    ).fetchone()
    if not header:
        db.rollback()
        return {'error': 'Stocktake was not found'}
    if header[1] == 'applied':
        db.commit()
        return {'success': True, 'duplicate': True}
    lines = db.execute(
        "SELECT product_id, counted_qty, snapshot_qty FROM stocktake_lines WHERE stocktake_id=?",
        (int(stocktake_id),),
    ).fetchall()
    if not lines:
        db.rollback()
        return {'error': 'Enter at least one count'}
    changed = []
    described = []
    for product_id, counted, snapshot in lines:
        row = db.execute(
            "SELECT id, name, stock, cost_price FROM products WHERE id=?", (product_id,)
        ).fetchone()
        if not row:
            db.rollback()
            return {'error': 'Product was not found'}
        old = round(float(row[2] or 0), 4)
        # Sales and receipts during the count stay. The variance is applied
        # on top of the stock that exists now, not instead of it.
        if snapshot is None:
            new = round(float(counted), 4)
        else:
            new = round(float(counted) + (old - float(snapshot)), 4)
        if new < -1e-9:
            db.rollback()
            return {'error': f'{row[1]} would go negative after movements during the count'}
        new = max(0.0, new)
        ref = f'STK:{stocktake_id}:{product_id}'
        already = db.execute(
            "SELECT id FROM stock_movements WHERE reference=?", (ref,)
        ).fetchone()
        if already or abs(new - old) < 1e-9:
            continue
        cur = db.execute(
            "UPDATE products SET stock=? WHERE id=? AND stock=?",
            (new, product_id, old),
        )
        if cur.rowcount != 1:
            db.rollback()
            return {'error': 'Stock changed before this count was applied'}
        db.execute(
            "INSERT INTO stock_movements "
            "(product_id,product_name,movement_type,qty_before,qty_change,"
            "qty_after,reference,reason,user_id,username) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (product_id, row[1], 'STOCKTAKE', old, round(new - old, 4), new,
             ref, (f'Stocktake {stocktake_id}. {backdate_reason}'.strip() if backdate_reason else f'Stocktake {stocktake_id}'),
             None, (username or 'stocktake')[:40]),
        )
        if business_date:
            cols = {item[1] for item in db.execute("PRAGMA table_info(stock_movements)")}
            if 'business_date' not in cols:
                db.execute("ALTER TABLE stock_movements ADD COLUMN business_date TEXT")
            db.execute(
                "UPDATE stock_movements SET business_date=? WHERE reference=?",
                (str(business_date)[:10], ref),
            )
        from desktop.utils.stock_layers import add_layer, consume_available_cost
        delta = round(new - old, 4)
        if delta < 0:
            layer = consume_available_cost(db, product_id, abs(delta), reference=ref)
        else:
            known_cost = float(row[3] or 0)
            layer = (
                add_layer(db, product_id, delta, known_cost, 'stocktake', ref)
                if known_cost > 0
                else {'success': True, 'uncosted': delta}
            )
        if layer.get('error'):
            db.rollback()
            return {'error': layer['error'], 'status': 400}
        changed.append(product_id)
        described.append(f"pid={product_id} stock {old}->{new}")
    db.execute(
        "UPDATE stocktakes SET status='applied' WHERE id=? AND status='open'",
        (int(stocktake_id),),
    )
    db.commit()
    try:
        from desktop.utils.api_client import _audit
        _audit(
            user_id, username or 'stocktake', 'APPLY_STOCKTAKE', 'inventory',
            f"stocktake={stocktake_id} " + ("; ".join(described) if described else "no quantity change"),
        )
    except Exception:
        pass
    return {'success': True, 'changed': changed}


def list_stocktakes(db) -> list:
    ensure_stocktake(db)
    rows = db.execute(
        "SELECT id, name, status, created_at FROM stocktakes ORDER BY id DESC LIMIT 30"
    ).fetchall()
    return [
        {'id': row[0], 'name': row[1], 'status': row[2], 'created_at': row[3]}
        for row in rows
    ]


def stocktake_detail(db, stocktake_id: int) -> dict:
    ensure_stocktake(db)
    header = db.execute(
        "SELECT id, name, status, created_at FROM stocktakes WHERE id=?",
        (int(stocktake_id),),
    ).fetchone()
    if not header:
        return {'error': 'Stocktake was not found'}
    lines = db.execute(
        """SELECT l.product_id, p.name, l.counted_qty, l.snapshot_qty, p.stock
           FROM stocktake_lines l
           LEFT JOIN products p ON p.id = l.product_id
           WHERE l.stocktake_id=?
           ORDER BY p.name""",
        (int(stocktake_id),),
    ).fetchall()
    return {
        'id': header[0],
        'name': header[1],
        'status': header[2],
        'created_at': header[3],
        'lines': [
            {
                'product_id': line[0],
                'name': line[1] or '',
                'counted_qty': line[2],
                'snapshot_qty': line[3],
                'stock_now': line[4],
            }
            for line in lines
        ],
    }


_REPAIRED_PATHS = set()


def repair_uncosted_stocktake_shortages(db) -> dict:
    """Consume FIFO for stocktake shortages that were applied before cost batches moved.

    Product quantity and the original stocktake row stay as posted. The missing
    cost use is added once, with the same reference as the stock movement.
    A second call finds the use and does nothing.
    """
    try:
        path = ''
        for row in db.execute('PRAGMA database_list'):
            if row[1] == 'main':
                path = row[2] or ''
        if path and path in _REPAIRED_PATHS:
            return {'success': True, 'skipped': True, 'repaired': []}
    except Exception:
        path = ''
    try:
        movements = db.execute(
            "SELECT product_id, qty_change, reference FROM stock_movements "
            "WHERE movement_type='STOCKTAKE' AND qty_change < -0.0001 "
            "AND reference IS NOT NULL"
        ).fetchall()
    except Exception:
        if path:
            _REPAIRED_PATHS.add(path)
        return {'success': True, 'repaired': []}
    from desktop.utils.stock_layers import consume_available_cost, ensure_cost_layers
    ensure_cost_layers(db)
    repaired = []
    for product_id, qty_change, reference in movements:
        ref = str(reference or '')
        if not ref:
            continue
        used = db.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM cost_layer_uses "
            "WHERE reference=? AND COALESCE(reversed, 0)=0",
            (ref,),
        ).fetchone()
        covered = round(float(used[0] or 0), 4) if used else 0.0
        need = round(abs(float(qty_change)) - covered, 4)
        if need <= 0.0001:
            continue
        layer = consume_available_cost(db, int(product_id), need, reference=ref)
        if layer.get('error'):
            db.rollback()
            return {'error': layer['error'], 'repaired': repaired}
        repaired.append({
            'product_id': int(product_id),
            'reference': ref,
            'quantity': need,
            'cost': layer.get('cogs'),
        })
    if repaired:
        try:
            from desktop.utils.api_client import _audit
            detail = '; '.join(
                f"{row['reference']} qty {row['quantity']}" for row in repaired
            )
            _audit(None, 'system', 'REPAIR_STOCKTAKE_COST', 'inventory', detail, conn=db)
        except Exception:
            pass
        db.commit()
    if path:
        _REPAIRED_PATHS.add(path)
    return {'success': True, 'repaired': repaired}
