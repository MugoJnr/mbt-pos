"""FIFO cost layers. Opening stock is backfilled only when a cost is already stored."""
from __future__ import annotations


def ensure_cost_layers(db) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS cost_layers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            original_qty REAL NOT NULL,
            remaining_qty REAL NOT NULL,
            unit_cost REAL NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    db.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_cost_layer_source
           ON cost_layers(product_id, source_type, source_id)"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS cost_layer_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            layer_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            sale_id INTEGER,
            quantity REAL NOT NULL,
            unit_cost REAL NOT NULL,
            reference TEXT,
            reversed INTEGER DEFAULT 0
        )"""
    )


def add_layer(db, product_id: int, qty: float, unit_cost: float,
              source_type: str, source_id: str) -> dict:
    ensure_cost_layers(db)
    qty = round(float(qty), 4)
    unit_cost = round(float(unit_cost), 4)
    if qty <= 0:
        return {'error': 'Quantity must be greater than zero'}
    if unit_cost < 0:
        return {'error': 'Cost cannot be negative'}
    existing = db.execute(
        "SELECT id, remaining_qty FROM cost_layers "
        "WHERE product_id=? AND source_type=? AND source_id=?",
        (int(product_id), source_type, str(source_id)),
    ).fetchone()
    if existing:
        return {'success': True, 'id': existing[0], 'duplicate': True,
                'remaining_qty': existing[1]}
    db.execute(
        "INSERT INTO cost_layers "
        "(product_id, source_type, source_id, original_qty, remaining_qty, unit_cost) "
        "VALUES (?,?,?,?,?,?)",
        (int(product_id), source_type, str(source_id), qty, qty, unit_cost),
    )
    return {'success': True, 'id': db.execute('SELECT last_insert_rowid()').fetchone()[0],
            'duplicate': False}


def consume_fifo(db, product_id: int, qty: float, sale_id=None, reference: str = '') -> dict:
    ensure_cost_layers(db)
    need = round(float(qty), 4)
    if need <= 0:
        return {'error': 'Quantity must be greater than zero'}
    rows = db.execute(
        "SELECT id, remaining_qty, original_qty, unit_cost FROM cost_layers "
        "WHERE product_id=? AND remaining_qty>0 ORDER BY created_at, id",
        (int(product_id),),
    ).fetchall()
    if not rows:
        return {'skipped': True}
    left = need
    uses = []
    cogs = 0.0
    for row in rows:
        if left <= 0.0001:
            break
        take = min(left, float(row[1]))
        take = round(take, 4)
        if take <= 0:
            continue
        db.execute(
            "UPDATE cost_layers SET remaining_qty=remaining_qty-? WHERE id=? AND remaining_qty>=?",
            (take, row[0], take),
        )
        db.execute(
            "INSERT INTO cost_layer_uses "
            "(layer_id, product_id, sale_id, quantity, unit_cost, reference) "
            "VALUES (?,?,?,?,?,?)",
            (row[0], int(product_id), sale_id, take, float(row[3]), reference or None),
        )
        uses.append({'layer_id': row[0], 'quantity': take, 'unit_cost': float(row[3])})
        cogs = round(cogs + take * float(row[3]), 4)
        left = round(left - take, 4)
    if left > 0.0001:
        return {'error': 'Insufficient cost layers'}
    return {'success': True, 'cogs': cogs, 'uses': uses}


def restore_reference_layers(db, reference: str) -> dict:
    """Put back cost-layer uses recorded against one consumption reference prefix."""
    ensure_cost_layers(db)
    prefix = (reference or '').strip()
    if not prefix:
        return {'success': True, 'restored': 0}
    uses = db.execute(
        "SELECT id, layer_id, quantity FROM cost_layer_uses "
        "WHERE reference LIKE ? AND reversed=0",
        (prefix + '%',),
    ).fetchall()
    restored = 0.0
    for use in uses:
        layer = db.execute(
            "SELECT remaining_qty, original_qty FROM cost_layers WHERE id=?",
            (use[1],),
        ).fetchone()
        if not layer:
            continue
        room = round(float(layer[1]) - float(layer[0]), 4)
        put = min(float(use[2]), max(room, 0))
        if put > 0:
            db.execute(
                "UPDATE cost_layers SET remaining_qty=remaining_qty+? WHERE id=?",
                (put, use[1]),
            )
            restored = round(restored + put, 4)
        db.execute("UPDATE cost_layer_uses SET reversed=1 WHERE id=?", (use[0],))
    return {'success': True, 'restored': restored}


def restore_sale_layers(db, sale_id: int) -> dict:
    ensure_cost_layers(db)
    uses = db.execute(
        "SELECT id, layer_id, quantity FROM cost_layer_uses "
        "WHERE sale_id=? AND reversed=0",
        (int(sale_id),),
    ).fetchall()
    restored = 0.0
    for use in uses:
        layer = db.execute(
            "SELECT remaining_qty, original_qty FROM cost_layers WHERE id=?",
            (use[1],),
        ).fetchone()
        if not layer:
            continue
        room = round(float(layer[1]) - float(layer[0]), 4)
        put = min(float(use[2]), max(room, 0))
        if put > 0:
            db.execute(
                "UPDATE cost_layers SET remaining_qty=remaining_qty+? WHERE id=?",
                (put, use[1]),
            )
            restored = round(restored + put, 4)
        db.execute("UPDATE cost_layer_uses SET reversed=1 WHERE id=?", (use[0],))
    return {'success': True, 'restored': restored}


def opening_backfill(db) -> list:
    """Create one opening layer per product that already has stock and a cost."""
    ensure_cost_layers(db)
    rows = db.execute(
        "SELECT id, name, stock, cost_price FROM products"
    ).fetchall()
    report = []
    for row in rows:
        pid, name, stock, cost = row[0], row[1], row[2], row[3]
        qty = float(stock or 0)
        if qty <= 0:
            report.append({'product_id': pid, 'name': name, 'status': 'skipped_zero'})
            continue
        if cost is None or float(cost) < 0:
            report.append({'product_id': pid, 'name': name, 'status': 'missing_cost'})
            continue
        result = add_layer(db, pid, qty, float(cost), 'opening', str(pid))
        report.append({
            'product_id': pid,
            'name': name,
            'status': 'duplicate' if result.get('duplicate') else 'created',
            'quantity': qty,
            'unit_cost': float(cost),
        })
    return report
