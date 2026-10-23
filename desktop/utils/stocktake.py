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
    before = db.execute("SELECT stock FROM products WHERE id=?", (int(product_id),)).fetchone()
    if not before:
        return {'error': 'Product was not found'}
    db.execute(
        "INSERT INTO stocktake_lines (stocktake_id, product_id, counted_qty) "
        "VALUES (?,?,?) "
        "ON CONFLICT(stocktake_id, product_id) DO UPDATE SET counted_qty=excluded.counted_qty",
        (int(stocktake_id), int(product_id), counted),
    )
    after = db.execute("SELECT stock FROM products WHERE id=?", (int(product_id),)).fetchone()
    return {
        'success': True,
        'stock_unchanged': float(before[0] or 0) == float(after[0] or 0),
        'stock': float(after[0] or 0),
    }


def apply_stocktake(db, stocktake_id: int) -> dict:
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
        "SELECT product_id, counted_qty FROM stocktake_lines WHERE stocktake_id=?",
        (int(stocktake_id),),
    ).fetchall()
    if not lines:
        db.rollback()
        return {'error': 'Enter at least one count'}
    changed = []
    for product_id, counted in lines:
        row = db.execute(
            "SELECT id, name, stock FROM products WHERE id=?", (product_id,)
        ).fetchone()
        if not row:
            db.rollback()
            return {'error': 'Product was not found'}
        old = round(float(row[2] or 0), 4)
        new = round(float(counted), 4)
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
             ref, f'Stocktake {stocktake_id}', None, 'stocktake'),
        )
        changed.append(product_id)
    db.execute(
        "UPDATE stocktakes SET status='applied' WHERE id=? AND status='open'",
        (int(stocktake_id),),
    )
    db.commit()
    return {'success': True, 'changed': changed}
