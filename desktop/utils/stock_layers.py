"""FIFO buying-cost layers.

A later delivery at a different buying price must not rewrite the cost of
stock already on the shelf, and profit on a sale uses the cost of the units
actually sold. The product's cost_price stays the weighted average of what
is still in stock, so inventory value and the catalogue stay in step.
"""
from __future__ import annotations


def ensure_stock_layers(db) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS stock_cost_layers ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "product_id INTEGER NOT NULL,"
        "supplier_id INTEGER,"
        "purchase_id INTEGER,"
        "qty_received REAL NOT NULL,"
        "qty_remaining REAL NOT NULL,"
        "unit_cost REAL NOT NULL,"
        "received_at TEXT,"
        "source TEXT DEFAULT 'purchase'"
        ")"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_stock_layers_product "
        "ON stock_cost_layers(product_id, qty_remaining)"
    )


def _weighted(db, product_id: int) -> float:
    row = db.execute(
        "SELECT COALESCE(SUM(qty_remaining * unit_cost), 0) AS value, "
        "COALESCE(SUM(qty_remaining), 0) AS qty "
        "FROM stock_cost_layers WHERE product_id=? AND qty_remaining > 0.0001",
        (int(product_id),),
    ).fetchone()
    qty = float(row['qty'] if hasattr(row, 'keys') else row[1] or 0)
    value = float(row['value'] if hasattr(row, 'keys') else row[0] or 0)
    if qty <= 0.0001:
        return 0.0
    return round(value / qty, 4)


def _write_average(db, product_id: int) -> float:
    avg = _weighted(db, product_id)
    db.execute(
        "UPDATE products SET cost_price=? WHERE id=?",
        (avg, int(product_id)),
    )
    return avg


def record_receipt(
    db,
    product_id: int,
    *,
    quantity: float,
    unit_cost: float,
    qty_before: float = 0.0,
    previous_cost: float = 0.0,
    supplier_id: int = None,
    purchase_id: int = None,
    received_at: str = '',
    source: str = 'purchase',
) -> float:
    """Add a cost layer. Opening stock with no layers keeps its old cost."""
    ensure_stock_layers(db)
    product_id = int(product_id)
    quantity = round(float(quantity or 0), 4)
    unit_cost = round(float(unit_cost or 0), 4)
    existing = db.execute(
        "SELECT COUNT(*) FROM stock_cost_layers "
        "WHERE product_id=? AND qty_remaining > 0.0001",
        (product_id,),
    ).fetchone()[0]
    before = round(float(qty_before or 0), 4)
    prev = round(float(previous_cost or 0), 4)
    if not existing and before > 0.0001 and prev > 0:
        db.execute(
            "INSERT INTO stock_cost_layers "
            "(product_id, supplier_id, purchase_id, qty_received, qty_remaining, "
            "unit_cost, received_at, source) VALUES (?,?,?,?,?,?,?,?)",
            (product_id, None, None, before, before, prev, received_at, 'opening'),
        )
    if quantity > 0.0001 and unit_cost > 0:
        db.execute(
            "INSERT INTO stock_cost_layers "
            "(product_id, supplier_id, purchase_id, qty_received, qty_remaining, "
            "unit_cost, received_at, source) VALUES (?,?,?,?,?,?,?,?)",
            (
                product_id, supplier_id, purchase_id, quantity, quantity,
                unit_cost, received_at, source,
            ),
        )
    return _write_average(db, product_id)


def consume_fifo(db, product_id: int, quantity: float) -> float:
    """Take oldest layers first. Returns the blended unit cost of qty sold."""
    ensure_stock_layers(db)
    product_id = int(product_id)
    need = round(float(quantity or 0), 4)
    if need <= 0:
        return 0.0
    prod = db.execute(
        "SELECT cost_price FROM products WHERE id=?", (product_id,),
    ).fetchone()
    fallback = float((prod['cost_price'] if prod is not None else 0) or 0)
    layers = db.execute(
        "SELECT id, qty_remaining, unit_cost FROM stock_cost_layers "
        "WHERE product_id=? AND qty_remaining > 0.0001 ORDER BY id",
        (product_id,),
    ).fetchall()
    if not layers:
        return round(fallback, 4)
    cost_sum = 0.0
    taken = 0.0
    for layer in layers:
        if need <= 0.0001:
            break
        left = float(layer['qty_remaining'] or 0)
        unit = float(layer['unit_cost'] or 0)
        take = min(left, need)
        db.execute(
            "UPDATE stock_cost_layers SET qty_remaining=? WHERE id=?",
            (round(left - take, 4), layer['id']),
        )
        cost_sum += take * unit
        taken += take
        need = round(need - take, 4)
    if need > 0.0001:
        cost_sum += need * fallback
        taken += need
    _write_average(db, product_id)
    if taken <= 0:
        return round(fallback, 4)
    return round(cost_sum / taken, 4)


def restore_layer(
    db,
    product_id: int,
    quantity: float,
    unit_cost: float,
    *,
    received_at: str = '',
    source: str = 'void',
) -> float:
    """Put sold units back at the cost that was on the receipt."""
    return record_receipt(
        db,
        int(product_id),
        quantity=float(quantity or 0),
        unit_cost=float(unit_cost or 0),
        qty_before=0,
        previous_cost=0,
        received_at=received_at,
        source=source,
    )


def list_layers(db, product_id: int) -> list:
    ensure_stock_layers(db)
    rows = db.execute(
        "SELECT id, supplier_id, purchase_id, qty_received, qty_remaining, "
        "unit_cost, received_at, source FROM stock_cost_layers "
        "WHERE product_id=? ORDER BY id",
        (int(product_id),),
    ).fetchall()
    out = []
    for row in rows:
        out.append({k: row[k] for k in row.keys()} if hasattr(row, 'keys') else {})
    return out
