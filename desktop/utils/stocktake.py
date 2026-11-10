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
    counted = round(float(counted_qty), 4)
    if counted < 0:
        return {'error': 'Count cannot be negative'}
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


def apply_stocktake(db, stocktake_id: int, username: str = '', user_id=None) -> dict:
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
            "SELECT id, name, stock FROM products WHERE id=?", (product_id,)
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
             ref, f'Stocktake {stocktake_id}', None, (username or 'stocktake')[:40]),
        )
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
