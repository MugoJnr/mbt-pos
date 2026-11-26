"""FIFO cost layers.

Each delivery keeps its own buying price. A later delivery does not rewrite an
older batch. A sale is costed only from the batches it actually consumes.
The product-card buying price is a reference. It is not a substitute cost
when a sale has no batch, and it does not fill a shortfall after a real batch.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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
    have = {row[1] for row in db.execute("PRAGMA table_info(cost_layers)").fetchall()}
    for name, decl in (
        ("supplier_id", "INTEGER"),
        ("supplier_name", "TEXT"),
        ("reference_note", "TEXT"),
        ("purchase_unit_cost", "REAL"),
        ("extra_unit_cost", "REAL DEFAULT 0"),
        ("product_name", "TEXT"),
        ("username", "TEXT"),
        ("sell_price", "REAL"),
    ):
        if name not in have:
            db.execute(f"ALTER TABLE cost_layers ADD COLUMN {name} {decl}")
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
              source_type: str, source_id: str, **meta) -> dict:
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
        if source_type == 'opening':
            db.execute(
                "UPDATE cost_layers SET "
                "supplier_name=COALESCE(NULLIF(supplier_name, ''), 'Opening stock'), "
                "reference_note=COALESCE(NULLIF(reference_note, ''), "
                "'Inherited from the product cost. Supplier unknown.') "
                "WHERE id=?",
                (existing[0],),
            )
        return {'success': True, 'id': existing[0], 'duplicate': True,
                'remaining_qty': existing[1]}
    db.execute(
        "INSERT INTO cost_layers "
        "(product_id, source_type, source_id, original_qty, remaining_qty, unit_cost) "
        "VALUES (?,?,?,?,?,?)",
        (int(product_id), source_type, str(source_id), qty, qty, unit_cost),
    )
    layer_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    fields = []
    values = []
    for key in (
        'supplier_id', 'supplier_name', 'reference_note', 'purchase_unit_cost',
        'extra_unit_cost', 'product_name', 'username', 'sell_price',
    ):
        if key in meta and meta[key] is not None:
            fields.append(f"{key}=?")
            values.append(meta[key])
    if fields:
        values.append(layer_id)
        db.execute(
            f"UPDATE cost_layers SET {', '.join(fields)} WHERE id=?",
            values,
        )
    return {'success': True, 'id': layer_id, 'duplicate': False}


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
        changed = db.execute(
            "UPDATE cost_layers SET remaining_qty=remaining_qty-? WHERE id=? AND remaining_qty>=?",
            (take, row[0], take),
        )
        if changed.rowcount != 1:
            return {'error': 'That batch was already used by another sale.'}
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


def consume_available_cost(db, product_id: int, qty: float, sale_id=None, reference: str = '') -> dict:
    """Consume the oldest remaining batches first.

    Quantity with no batch stays uncosted. The product-card buying price is
    not written onto the sale and does not create a batch.
    """
    ensure_cost_layers(db)
    need = round(float(qty), 4)
    if need <= 0:
        return {'error': 'Quantity must be greater than zero'}
    left = need
    covered = 0.0
    cogs = 0.0
    uses = []
    skipped = set()
    while left > 0.0001:
        row = db.execute(
            "SELECT id, remaining_qty, unit_cost FROM cost_layers "
            "WHERE product_id=? AND remaining_qty>0 ORDER BY created_at, id LIMIT 1",
            (int(product_id),),
        ).fetchone()
        if not row:
            break
        if row[0] in skipped:
            row = db.execute(
                "SELECT id, remaining_qty, unit_cost FROM cost_layers "
                "WHERE product_id=? AND remaining_qty>0 AND id NOT IN (%s) "
                "ORDER BY created_at, id LIMIT 1" % ",".join("?" * len(skipped)),
                (int(product_id), *skipped),
            ).fetchone()
            if not row:
                break
        take = round(min(left, float(row[1] or 0)), 4)
        if take <= 0:
            break
        changed = db.execute(
            "UPDATE cost_layers SET remaining_qty=remaining_qty-? "
            "WHERE id=? AND remaining_qty>=?",
            (take, row[0], take),
        )
        if changed.rowcount != 1:
            skipped.add(row[0])
            continue
        db.execute(
            "INSERT INTO cost_layer_uses "
            "(layer_id, product_id, sale_id, quantity, unit_cost, reference) "
            "VALUES (?,?,?,?,?,?)",
            (row[0], int(product_id), sale_id, take, float(row[2]), reference or None),
        )
        uses.append({'layer_id': row[0], 'quantity': take, 'unit_cost': float(row[2])})
        cogs = round(cogs + take * float(row[2]), 4)
        covered = round(covered + take, 4)
        left = round(left - take, 4)
    return {
        'success': True,
        'cogs': cogs,
        'covered': covered,
        'uncosted': round(max(left, 0), 4),
        'uses': uses,
    }


def quote_available_cost(db, product_id: int, qty: float) -> dict:
    """Read the FIFO cost of a quantity. Does not write a layer or a use."""
    ensure_cost_layers(db)
    need = round(float(qty), 4)
    if need <= 0:
        return {'error': 'Quantity must be greater than zero', 'cogs': 0, 'covered': 0, 'uncosted': 0, 'unit_cost': None}
    left = need
    cogs = 0.0
    covered = 0.0
    rows = db.execute(
        "SELECT remaining_qty, unit_cost FROM cost_layers "
        "WHERE product_id=? AND remaining_qty>0 ORDER BY created_at, id",
        (int(product_id),),
    ).fetchall()
    for row in rows:
        if left <= 0.0001:
            break
        take = round(min(left, float(row[0] or 0)), 4)
        if take <= 0:
            continue
        cogs = round(cogs + take * float(row[1] or 0), 4)
        covered = round(covered + take, 4)
        left = round(left - take, 4)
    unit = round(cogs / covered, 4) if covered > 0 else None
    return {
        'cogs': cogs,
        'covered': covered,
        'uncosted': round(max(left, 0), 4),
        'unit_cost': unit,
    }


def record_sale_cost(db, product_id: int, qty: float, sale_id=None, reference: str = '', layer_id=None) -> dict:
    """Record the FIFO cost that exists. A chosen batch is used only when named."""
    if layer_id:
        result = consume_layer(
            db, int(layer_id), qty, sale_id=sale_id, reference=reference,
        )
    else:
        result = consume_available_cost(
            db, product_id, qty, sale_id=sale_id, reference=reference,
        )
    if sale_id and not result.get('error'):
        stamp_sale_costs(db, sale_id)
    return result


def consume_layer(db, layer_id: int, qty: float, sale_id=None, reference: str = '') -> dict:
    """Use one named batch. Other batches for the same product stay untouched."""
    ensure_cost_layers(db)
    need = round(float(qty), 4)
    if need <= 0:
        return {'error': 'Quantity must be greater than zero'}
    layer = db.execute(
        "SELECT id, product_id, remaining_qty, unit_cost FROM cost_layers WHERE id=?",
        (int(layer_id),),
    ).fetchone()
    if not layer:
        return {'error': 'Cost batch was not found.'}
    unit_cost = float(layer[3])
    changed = db.execute(
        "UPDATE cost_layers SET remaining_qty=remaining_qty-? WHERE id=? AND remaining_qty>=?",
        (need, int(layer_id), need),
    )
    if changed.rowcount != 1:
        return {'error': 'That batch was already used by another sale.'}
    db.execute(
        "INSERT INTO cost_layer_uses "
        "(layer_id, product_id, sale_id, quantity, unit_cost, reference) "
        "VALUES (?,?,?,?,?,?)",
        (int(layer_id), int(layer[1]), sale_id, need, unit_cost, reference or None),
    )
    return {'success': True, 'cogs': round(need * unit_cost, 4), 'unit_cost': unit_cost}


def copy_card_costs_onto_uncosted_sales(db, username: str = '') -> dict:
    """Do not invent a buying price. Unknown cost stays visible until an admin records it."""
    return {'copied': 0, 'reason': 'card_price_is_not_a_historical_cost'}


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


def restore_reference_quantity(db, reference: str, qty: float) -> dict:
    """Put back part of one consumption product. Newer uses are reversed first."""
    ensure_cost_layers(db)
    need = round(float(qty), 4)
    prefix = (reference or '').strip()
    if need <= 0 or not prefix:
        return {'error': 'Quantity must be greater than zero'}
    uses = db.execute(
        "SELECT id, layer_id, quantity, unit_cost FROM cost_layer_uses "
        "WHERE reference LIKE ? AND reversed=0 ORDER BY id DESC",
        (prefix + '%',),
    ).fetchall()
    if not uses:
        return {'success': True, 'skipped': True, 'restored': 0, 'cogs': 0}
    left = need
    restored = 0.0
    cogs = 0.0
    for use in uses:
        if left <= 0.0001:
            break
        available = round(float(use[2] or 0), 4)
        take = round(min(left, available), 4)
        if take <= 0:
            continue
        layer = db.execute(
            "SELECT remaining_qty, original_qty FROM cost_layers WHERE id=?",
            (use[1],),
        ).fetchone()
        if not layer:
            continue
        room = round(float(layer[1]) - float(layer[0]), 4)
        put = round(min(take, max(room, 0)), 4)
        if put + 0.0001 < take:
            return {'error': 'The cost layer cannot take the restored quantity.'}
        if put > 0:
            db.execute(
                "UPDATE cost_layers SET remaining_qty=remaining_qty+? WHERE id=?",
                (put, use[1]),
            )
        if take + 0.0001 >= available:
            db.execute("UPDATE cost_layer_uses SET reversed=1 WHERE id=?", (use[0],))
        else:
            db.execute(
                "UPDATE cost_layer_uses SET quantity=quantity-? WHERE id=?",
                (take, use[0]),
            )
        cogs = round(cogs + take * float(use[3] or 0), 4)
        restored = round(restored + take, 4)
        left = round(left - take, 4)
    if left > 0.0001:
        return {'error': 'Not enough recorded cost to restore that quantity.'}
    return {'success': True, 'restored': restored, 'cogs': cogs}


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
    stamp_sale_costs(db, sale_id)
    return {'success': True, 'restored': restored}


def restore_sale_product_qty(db, sale_id: int, product_id: int, qty: float) -> dict:
    """Put back the newest FIFO uses for one product on one sale, up to qty."""
    ensure_cost_layers(db)
    need = round(float(qty), 4)
    if need <= 0:
        return {'error': 'Quantity must be greater than zero'}
    uses = db.execute(
        "SELECT id, layer_id, quantity, unit_cost FROM cost_layer_uses "
        "WHERE sale_id=? AND product_id=? AND COALESCE(reversed,0)=0 "
        "ORDER BY id DESC",
        (int(sale_id), int(product_id)),
    ).fetchall()
    if not uses:
        return {'skipped': True, 'restored': 0, 'cost': 0}
    left = need
    restored = 0.0
    restored_cost = 0.0
    for use in uses:
        if left <= 0.0001:
            break
        available = round(float(use[2]), 4)
        take = round(min(left, available), 4)
        if take <= 0:
            continue
        layer = db.execute(
            "SELECT remaining_qty, original_qty FROM cost_layers WHERE id=?",
            (use[1],),
        ).fetchone()
        if not layer:
            continue
        room = round(float(layer[1]) - float(layer[0]), 4)
        put = min(take, max(room, 0))
        if put > 0:
            db.execute(
                "UPDATE cost_layers SET remaining_qty=remaining_qty+? WHERE id=?",
                (put, use[1]),
            )
            restored = round(restored + put, 4)
            restored_cost = round(restored_cost + put * float(use[3] or 0), 2)
        if take + 0.0001 >= available:
            db.execute("UPDATE cost_layer_uses SET reversed=1 WHERE id=?", (use[0],))
        else:
            db.execute(
                "UPDATE cost_layer_uses SET quantity=quantity-? WHERE id=?",
                (take, use[0]),
            )
        left = round(left - take, 4)
    result = {
        'success': True,
        'restored': restored,
        'cost': restored_cost,
        'uncosted': round(max(left, 0), 4),
    }
    stamp_sale_costs(db, sale_id)
    return result


def ensure_sale_item_cost_columns(db) -> None:
    """Sale lines keep the FIFO snapshot the portal syncs. Older shops gain the columns."""
    cols = {row[1] for row in db.execute("PRAGMA table_info(sale_items)").fetchall()}
    if not cols:
        return
    if 'returned_qty' not in cols:
        db.execute("ALTER TABLE sale_items ADD COLUMN returned_qty REAL DEFAULT 0")
    if 'unit_cost' not in cols:
        db.execute("ALTER TABLE sale_items ADD COLUMN unit_cost REAL")
    if 'costed_qty' not in cols:
        db.execute("ALTER TABLE sale_items ADD COLUMN costed_qty REAL")
    if 'line_cost' not in cols:
        db.execute("ALTER TABLE sale_items ADD COLUMN line_cost REAL")


def _cost_value(row, index: int, name: str):
    if hasattr(row, 'keys') and name in row.keys():
        return row[name]
    return row[index]


def _costs_match(current, unit_cost, costed_qty, line_cost) -> bool:
    pairs = (
        (_cost_value(current, 0, 'unit_cost'), unit_cost),
        (_cost_value(current, 1, 'costed_qty'), costed_qty),
        (_cost_value(current, 2, 'line_cost'), line_cost),
    )
    for old, new in pairs:
        if old in (None, '') and new in (None, ''):
            continue
        if old in (None, '') or new in (None, ''):
            return False
        if abs(float(old) - float(new)) > 0.00005:
            return False
    return True


def _write_sale_item_cost(db, item_id: int, unit_cost, costed_qty, line_cost) -> bool:
    current = db.execute(
        "SELECT unit_cost, costed_qty, line_cost FROM sale_items WHERE id=?",
        (int(item_id),),
    ).fetchone()
    if current and _costs_match(current, unit_cost, costed_qty, line_cost):
        return False
    db.execute(
        "UPDATE sale_items SET unit_cost=?, costed_qty=?, line_cost=? WHERE id=?",
        (unit_cost, costed_qty, line_cost, int(item_id)),
    )
    return True


def stamp_sale_costs(db, sale_id) -> int:
    """Copy the FIFO uses still on this sale onto its lines.

    Uses are stored per product, so they are shared across that product's lines
    in line order after returns. Nothing is invented when no use remains.
    A line that did not change is left untouched, so sync is not queued again.
    """
    ensure_cost_layers(db)
    ensure_sale_item_cost_columns(db)
    items = db.execute(
        "SELECT id, product_id, quantity, COALESCE(returned_qty, 0) "
        "FROM sale_items WHERE sale_id=? ORDER BY id",
        (int(sale_id),),
    ).fetchall()
    if not items:
        return 0
    uses = db.execute(
        "SELECT product_id, COALESCE(SUM(quantity), 0), "
        "COALESCE(SUM(quantity * unit_cost), 0) "
        "FROM cost_layer_uses "
        "WHERE sale_id=? AND COALESCE(reversed, 0)=0 "
        "GROUP BY product_id",
        (int(sale_id),),
    ).fetchall()
    remaining = {
        int(row[0]): [round(float(row[1] or 0), 4), round(float(row[2] or 0), 4)]
        for row in uses
    }
    changed = 0
    for item in items:
        item_id = int(_cost_value(item, 0, 'id'))
        product_id = _cost_value(item, 1, 'product_id')
        quantity = float(_cost_value(item, 2, 'quantity') or 0)
        returned = float(_cost_value(item, 3, 'returned_qty') or 0)
        net = round(quantity - returned, 4) if quantity > 0 else 0.0
        pool = remaining.get(int(product_id)) if product_id not in (None, '') else None
        if net <= 0.0001 or not pool or pool[0] <= 0.0001:
            if _write_sale_item_cost(db, item_id, None, 0.0, None):
                changed += 1
            continue
        take = round(min(net, pool[0]), 4)
        if take + 0.0001 >= pool[0]:
            part_cost = pool[1]
            pool[0] = 0.0
            pool[1] = 0.0
        else:
            part_cost = round(pool[1] * (take / pool[0]), 4)
            pool[0] = round(pool[0] - take, 4)
            pool[1] = round(pool[1] - part_cost, 4)
        unit = round(part_cost / take, 4) if take else None
        if _write_sale_item_cost(db, item_id, unit, take, round(part_cost, 4)):
            changed += 1
    return changed


def backfill_sale_line_costs(db) -> dict:
    """Stamp every existing sale from the FIFO ledger. Safe to run more than once."""
    tables = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if 'sale_items' not in tables or 'cost_layer_uses' not in tables:
        return {'sales': 0, 'updated': 0}
    ensure_sale_item_cost_columns(db)
    sale_ids = [
        row[0] for row in db.execute(
            "SELECT DISTINCT sale_id FROM sale_items WHERE sale_id IS NOT NULL"
        ).fetchall()
    ]
    updated = 0
    for sale_id in sale_ids:
        updated += stamp_sale_costs(db, sale_id)
    return {'sales': len(sale_ids), 'updated': updated}


def period_profit(db, start: str, end: str) -> dict:
    """Profit from the FIFO cost actually consumed. Sales with no layer are uncosted."""
    ensure_cost_layers(db)
    cols = {row[1] for row in db.execute("PRAGMA table_info(sale_items)").fetchall()}
    if "returned_qty" not in cols:
        db.execute("ALTER TABLE sale_items ADD COLUMN returned_qty REAL DEFAULT 0")
    day = "COALESCE(NULLIF(s.sale_date,''), date(s.created_at))"
    rows = db.execute(
        f"""
        SELECT s.id, s.total, si.product_id, COALESCE(si.total,0),
               COALESCE(si.quantity,0),
               COALESCE(si.quantity,0) - COALESCE(si.returned_qty,0),
               (SELECT COALESCE(SUM(u.quantity), 0) FROM cost_layer_uses u
                WHERE u.sale_id=si.sale_id AND u.product_id=si.product_id
                  AND COALESCE(u.reversed,0)=0),
               (SELECT COALESCE(SUM(u.quantity * u.unit_cost), 0) FROM cost_layer_uses u
                WHERE u.sale_id=si.sale_id AND u.product_id=si.product_id
                  AND COALESCE(u.reversed,0)=0)
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        WHERE {day} BETWEEN ? AND ?
          AND COALESCE(s.status,'completed')='completed'
        """,
        (str(start)[:10], str(end)[:10]),
    ).fetchall()
    parsed = []
    line_sums = {}
    for sale_id, sale_total, product_id, line_total, quantity, net_qty, covered_qty, line_cogs in rows:
        item = {
            "sale_id": int(sale_id),
            "sale_total": float(sale_total or 0),
            "product_id": product_id,
            "line_total": float(line_total or 0),
            "quantity": float(quantity or 0),
            "net_qty": float(net_qty or 0),
            "covered_qty": float(covered_qty or 0),
            "cogs": float(line_cogs or 0),
        }
        parsed.append(item)
        line_sums[item["sale_id"]] = line_sums.get(item["sale_id"], 0.0) + item["line_total"]
    revenue = cogs = uncosted = 0.0
    uncosted_units = 0.0
    costed_lines = uncosted_lines = 0
    products = set()
    seen_cost = set()
    for item in parsed:
        net = item["net_qty"]
        if net <= 0.0001 or item["quantity"] <= 0.0001:
            continue
        lines_net = line_sums.get(item["sale_id"]) or 0.0
        factor = (item["sale_total"] / lines_net) if lines_net > 0.009 else 1.0
        amount = item["line_total"] * net / item["quantity"] * factor
        covered = min(item["covered_qty"], net)
        gap = round(net - covered, 4)
        if covered > 0.0001:
            revenue += amount * covered / net
            key = (item["sale_id"], int(item["product_id"] or 0))
            if key not in seen_cost:
                seen_cost.add(key)
                cogs += item["cogs"]
            if gap <= 0.0001:
                costed_lines += 1
        if gap > 0.0001:
            uncosted += amount * gap / net
            uncosted_lines += 1
            uncosted_units += gap
            if item["product_id"]:
                products.add(int(item["product_id"]))
    return {
        'profit': round(revenue - cogs, 2),
        'revenue_costed': round(revenue, 2),
        'cogs': round(cogs, 2),
        'uncosted_revenue': round(uncosted, 2),
        'uncosted_lines': uncosted_lines,
        'uncosted_units': round(uncosted_units, 4),
        'uncosted_products': len(products),
        'costed_lines': costed_lines,
    }


def inventory_valuation(db) -> dict:
    """Remaining quantity and cost from the batch ledger, not the latest product cost."""
    ensure_cost_layers(db)
    row = db.execute(
        "SELECT COALESCE(SUM(remaining_qty),0), COALESCE(SUM(remaining_qty * unit_cost),0) "
        "FROM cost_layers"
    ).fetchone()
    layered_qty = round(float(row[0] or 0), 4)
    result = {
        'quantity': layered_qty,
        'value': round(float(row[1] or 0), 2),
    }
    try:
        held = db.execute(
            "SELECT COALESCE(SUM(stock),0) FROM products WHERE COALESCE(is_active,1)=1"
        ).fetchone()
        product_units = round(float(held[0] or 0), 4)
        result['product_units'] = product_units
        result['unlayered_units'] = round(max(product_units - layered_qty, 0), 4)
    except Exception:
        pass
    try:
        from desktop.utils.cost_health import summary_counts
        result.update(summary_counts(db))
    except Exception:
        logger.exception('cost health summary')
    if float(result.get('unlayered_units') or 0) > 0.05:
        result['costing_incomplete'] = True
    return result


def allocate_delivery_extra(lines, total_extra) -> dict:
    """Split one delivery cost across lines by buy value. The last line takes the remainder."""
    try:
        total = round(float(total_extra or 0), 4)
    except (TypeError, ValueError):
        return {'error': 'Enter a valid additional delivery cost.'}
    if total < 0:
        return {'error': 'Additional delivery cost cannot be negative.'}
    if not lines:
        return {'error': 'Add at least one product.'}
    weights = []
    for line in lines:
        buy = line.get('unit_cost')
        buy = 0 if buy is None else float(buy)
        weights.append(max(float(line['quantity']) * buy, 0))
    weight_sum = sum(weights)
    if weight_sum <= 0.0001:
        weights = [float(line['quantity']) for line in lines]
        weight_sum = sum(weights)
    allocated = 0.0
    shares = []
    for index, line in enumerate(lines):
        if index == len(lines) - 1:
            share = round(total - allocated, 4)
        else:
            share = round(total * weights[index] / weight_sum, 4) if weight_sum else 0
            allocated = round(allocated + share, 4)
        qty = float(line['quantity'])
        line['extra_unit_cost'] = round(share / qty, 4) if qty else 0
        shares.append(share)
    return {'success': True, 'shares': shares, 'total': total}


def correct_opening_cost(db, layer_id: int, unit_cost: float) -> dict:
    """Correct an inherited opening cost. Sales already taken keep their recorded cost."""
    ensure_cost_layers(db)
    try:
        cost = round(float(unit_cost), 4)
    except (TypeError, ValueError):
        return {'error': 'Enter a valid cost.'}
    if cost < 0:
        return {'error': 'Cost cannot be negative.'}
    row = db.execute(
        "SELECT id, source_type FROM cost_layers WHERE id=?",
        (int(layer_id),),
    ).fetchone()
    if not row:
        return {'error': 'That batch was not found.'}
    if str(row['source_type'] or '') != 'opening':
        return {'error': 'Only an opening batch can be corrected here. A delivery keeps its original cost.'}
    db.execute(
        "UPDATE cost_layers SET unit_cost=?, purchase_unit_cost=? WHERE id=?",
        (cost, cost, int(layer_id)),
    )
    return {'success': True, 'id': int(layer_id), 'unit_cost': cost}


def product_batch_view(db, product_id: int, see_cost: bool = False) -> dict:
    """Remaining batches for one product. Costs are omitted unless see_cost."""
    ensure_cost_layers(db)
    rows = db.execute(
        "SELECT * FROM cost_layers WHERE product_id=? ORDER BY created_at, id",
        (int(product_id),),
    ).fetchall()
    card_price = None
    try:
        product = db.execute(
            "SELECT price FROM products WHERE id=?", (int(product_id),),
        ).fetchone()
        if product and product[0] not in (None, ''):
            card_price = round(float(product[0]), 4)
    except Exception:
        card_price = None
    batches = []
    for row in rows:
        original = round(float(row['original_qty'] or 0), 4)
        remaining = round(float(row['remaining_qty'] or 0), 4)
        landed = round(float(row['unit_cost'] or 0), 4)
        purchase = row['purchase_unit_cost']
        purchase = landed if purchase is None else round(float(purchase), 4)
        extra = round(float(row['extra_unit_cost'] or 0), 4)
        source = str(row['source_type'] or '')
        supplier = row['supplier_name'] or ''
        legacy = source == 'opening'
        if not supplier and legacy:
            supplier = 'Opening stock'
        origin = 'inherited' if legacy else ('adjustment' if source == 'adjust' else 'verified')
        custom = row['sell_price']
        custom_price = None if custom in (None, '') else round(float(custom), 4)
        item = {
            'id': row['id'],
            'batch_ref': f"B{len(batches) + 1:03d}",
            'product_id': row['product_id'],
            'product_name': row['product_name'] or '',
            'source_type': source,
            'source_id': row['source_id'],
            'supplier_name': supplier,
            'reference_note': row['reference_note'] or '',
            'created_at': row['created_at'],
            'username': row['username'] or '',
            'original_qty': original,
            'consumed_qty': round(original - remaining, 4),
            'remaining_qty': remaining,
            'status': (
                'exhausted' if remaining <= 0.0001
                else 'partial' if remaining + 0.0001 < original
                else 'available'
            ),
            'legacy': legacy,
            'cost_origin': origin,
            'sell_price': custom_price,
            'price_mode': 'custom' if custom_price is not None else 'normal',
            'effective_sell_price': custom_price if custom_price is not None else card_price,
        }
        if see_cost:
            item.update({
                'purchase_unit_cost': purchase,
                'extra_unit_cost': extra,
                'unit_cost': landed,
                'remaining_value': round(remaining * landed, 2),
            })
        batches.append(item)
    active = [batch for batch in batches if batch['remaining_qty'] > 0.0001]
    quantity = round(sum(batch['remaining_qty'] for batch in batches), 4)
    summary = {
        'quantity': quantity,
        'active_batches': len(active),
        'oldest_batch_id': active[0]['id'] if active else None,
        'latest_received': batches[-1]['created_at'] if batches else None,
    }
    if see_cost:
        value = round(sum(batch.get('remaining_value') or 0 for batch in batches), 2)
        summary['inventory_value'] = value
        summary['average_cost'] = round(value / quantity, 4) if quantity > 0.0001 else 0
        latest_cost = next(
            (batch.get('purchase_unit_cost') for batch in reversed(batches)
             if batch.get('source_type') == 'purchase'),
            None,
        )
        summary['latest_purchase_price'] = latest_cost
    return {'batches': batches, 'batch_summary': summary}


def set_batch_sell_price(db, layer_id: int, sell_price, username: str = '') -> dict:
    """Set or clear one batch's selling price. Blank returns it to the product price.

    An exhausted batch stays in history and cannot be repriced for new sales.
    """
    ensure_cost_layers(db)
    row = db.execute(
        "SELECT id, remaining_qty, unit_cost, sell_price FROM cost_layers WHERE id=?",
        (int(layer_id),),
    ).fetchone()
    if not row:
        return {'error': 'Batch was not found.'}
    if float(row['remaining_qty'] or 0) <= 0.0001:
        return {'error': 'That batch is finished. Its history stays, and it cannot be sold.'}
    old = row['sell_price']
    old_price = None if old in (None, '') else round(float(old), 4)
    if sell_price in (None, ''):
        new_price = None
    else:
        try:
            new_price = round(float(sell_price), 4)
        except (TypeError, ValueError):
            return {'error': 'Enter a valid selling price.'}
        if new_price < 0:
            return {'error': 'Selling price cannot be negative.'}
    if old_price == new_price:
        return {'success': True, 'unchanged': True, 'sell_price': new_price}
    db.execute(
        "UPDATE cost_layers SET sell_price=? WHERE id=?",
        (new_price, int(layer_id)),
    )
    landed = round(float(row['unit_cost'] or 0), 4)
    warning = ''
    if new_price is not None and new_price + 0.0001 < landed:
        warning = 'This selling price is below the landed cost of the batch.'
    return {
        'success': True,
        'id': int(layer_id),
        'old_sell_price': old_price,
        'sell_price': new_price,
        'price_mode': 'custom' if new_price is not None else 'normal',
        'warning': warning,
        'username': username or '',
    }


def quote_fifo_sell_prices(db, product_id: int, qty: float, product_price: float) -> dict:
    """The prices a FIFO sale would charge. Does not consume stock."""
    ensure_cost_layers(db)
    need = round(float(qty), 4)
    if need <= 0:
        return {'error': 'Quantity must be greater than zero'}
    try:
        card = round(float(product_price), 4)
    except (TypeError, ValueError):
        return {'error': 'Enter a valid selling price.'}
    if card < 0:
        return {'error': 'Selling price cannot be negative.'}
    refs = {
        int(_cost_value(row, 0, 'id')): f"B{index:03d}"
        for index, row in enumerate(db.execute(
            "SELECT id FROM cost_layers WHERE product_id=? ORDER BY created_at, id",
            (int(product_id),),
        ).fetchall(), start=1)
    }
    rows = db.execute(
        "SELECT id, remaining_qty, sell_price FROM cost_layers "
        "WHERE product_id=? AND remaining_qty>0 ORDER BY created_at, id",
        (int(product_id),),
    ).fetchall()
    left = need
    segments = []
    for row in rows:
        if left <= 0.0001:
            break
        take = round(min(left, float(row['remaining_qty'] or 0)), 4)
        if take <= 0:
            continue
        custom = row['sell_price']
        price = card if custom in (None, '') else round(float(custom), 4)
        segments.append({
            'layer_id': row['id'],
            'batch_ref': refs.get(int(row['id']), f"B{row['id']}"),
            'quantity': take,
            'unit_price': price,
            'price_mode': 'normal' if custom in (None, '') else 'custom',
        })
        left = round(left - take, 4)
    return {
        'segments': segments,
        'covered': round(need - max(left, 0), 4),
        'uncovered': round(max(left, 0), 4),
        'total': round(sum(part['quantity'] * part['unit_price'] for part in segments), 2),
    }


def quote_customer_lines(db, product_id: int, qty: float, product_price: float, product_name: str = '') -> dict:
    """Customer lines before payment.

    Different batch prices stay on separate lines, labelled with the batch
    reference. The same price stays one line, with the batch allocations kept.
    """
    quote = quote_fifo_sell_prices(db, product_id, qty, product_price)
    if quote.get('error'):
        return quote
    name = product_name or 'Product'
    segments = quote.get('segments') or []
    prices = {round(float(part['unit_price']), 4) for part in segments}
    split = len(prices) > 1
    lines = []
    if split:
        for part in segments:
            lines.append({
                'quantity': part['quantity'],
                'unit_price': part['unit_price'],
                'batch_refs': [part['batch_ref']],
                'label': f"{name} · {part['batch_ref']}",
                'allocations': [part],
                'split': True,
            })
    elif segments:
        lines.append({
            'quantity': round(sum(part['quantity'] for part in segments), 4),
            'unit_price': segments[0]['unit_price'],
            'batch_refs': [part['batch_ref'] for part in segments],
            'label': name,
            'allocations': segments,
            'split': False,
        })
    uncovered = round(float(quote.get('uncovered') or 0), 4)
    if uncovered > 0.0001:
        card = round(float(product_price), 4)
        if lines and not split and abs(lines[0]['unit_price'] - card) < 0.0001:
            lines[0]['quantity'] = round(lines[0]['quantity'] + uncovered, 4)
        else:
            lines.append({
                'quantity': uncovered,
                'unit_price': card,
                'batch_refs': [],
                'label': name,
                'allocations': [],
                'split': bool(lines),
                'uncovered': True,
            })
    quote['lines'] = lines
    quote['product_name'] = name
    return quote


def quote_chosen_batches(db, product_id: int, picks, product_price: float, product_name: str = '') -> dict:
    """Price a sale that takes named batches instead of the oldest stock."""
    cleaned = []
    for pick in picks or []:
        try:
            layer_id = int(pick.get('layer_id') or 0)
            qty = round(float(pick.get('quantity') or 0), 4)
        except (TypeError, ValueError):
            return {'error': 'Enter a valid batch and quantity.'}
        if layer_id <= 0 or qty <= 0:
            return {'error': 'Enter a valid batch and quantity.'}
        cleaned.append((layer_id, qty))
    if not cleaned:
        return {'error': 'Choose at least one batch.'}
    seen = set()
    for layer_id, _qty in cleaned:
        if layer_id in seen:
            return {'error': 'That batch is already on this allocation.'}
        seen.add(layer_id)
    total_qty = round(sum(qty for _layer, qty in cleaned), 4)
    fifo = quote_customer_lines(db, product_id, total_qty, product_price, product_name)
    if fifo.get('error'):
        return fifo
    refs = {
        int(_cost_value(row, 0, 'id')): f"B{index:03d}"
        for index, row in enumerate(db.execute(
            "SELECT id FROM cost_layers WHERE product_id=? ORDER BY created_at, id",
            (int(product_id),),
        ).fetchall(), start=1)
    }
    name = product_name or 'Product'
    lines = []
    for layer_id, qty in cleaned:
        row = db.execute(
            "SELECT id, product_id, remaining_qty, sell_price FROM cost_layers WHERE id=?",
            (layer_id,),
        ).fetchone()
        if not row or int(_cost_value(row, 1, 'product_id') or 0) != int(product_id):
            return {'error': 'That batch does not belong to this product.'}
        remaining = round(float(_cost_value(row, 2, 'remaining_qty') or 0), 4)
        if remaining + 0.0001 < qty:
            return {'error': 'That batch does not have enough stock left.'}
        custom = _cost_value(row, 3, 'sell_price')
        price = round(float(product_price), 4) if custom in (None, '') else round(float(custom), 4)
        ref = refs.get(layer_id, f"B{layer_id}")
        lines.append({
            'quantity': qty,
            'unit_price': price,
            'layer_id': layer_id,
            'batch_refs': [ref],
            'label': f"{name} · {ref}",
            'split': True,
            'fifo_override': True,
        })
    return {
        'lines': lines,
        'total': round(sum(line['quantity'] * line['unit_price'] for line in lines), 2),
        'fifo_lines': fifo.get('lines') or [],
        'fifo_total': fifo.get('total'),
        'product_name': name,
    }


def list_batches(db, search: str = '', see_cost: bool = False, limit: int = 400) -> list:
    """Every batch in the shop, oldest first within each product."""
    ensure_cost_layers(db)
    needle = (search or '').strip().lower()
    rows = db.execute(
        "SELECT c.id, c.product_id, c.created_at, c.supplier_name, c.reference_note, "
        "c.original_qty, c.remaining_qty, c.unit_cost, c.purchase_unit_cost, "
        "c.extra_unit_cost, c.sell_price, c.source_type, "
        "p.name, p.price, p.sku "
        "FROM cost_layers c LEFT JOIN products p ON p.id = c.product_id "
        "ORDER BY p.name, c.created_at, c.id"
    ).fetchall()
    sequence = {}
    found = []
    for row in rows:
        pid = int(_cost_value(row, 1, 'product_id') or 0)
        sequence[pid] = sequence.get(pid, 0) + 1
        name = _cost_value(row, 12, 'name') or ''
        supplier = _cost_value(row, 3, 'supplier_name') or ''
        note = _cost_value(row, 4, 'reference_note') or ''
        batch_ref = f"B{sequence[pid]:03d}"
        if needle and needle not in f"{name} {batch_ref} {supplier} {note} {_cost_value(row, 14, 'sku') or ''}".lower():
            continue
        original = round(float(_cost_value(row, 5, 'original_qty') or 0), 4)
        remaining = round(float(_cost_value(row, 6, 'remaining_qty') or 0), 4)
        custom = _cost_value(row, 10, 'sell_price')
        custom_price = None if custom in (None, '') else round(float(custom), 4)
        card = _cost_value(row, 13, 'price')
        card_price = None if card in (None, '') else round(float(card), 4)
        item = {
            'id': int(_cost_value(row, 0, 'id')),
            'batch_ref': batch_ref,
            'product_id': pid,
            'product_name': name,
            'sku': _cost_value(row, 14, 'sku') or '',
            'created_at': _cost_value(row, 2, 'created_at'),
            'supplier_name': supplier,
            'reference_note': note,
            'original_qty': original,
            'remaining_qty': remaining,
            'status': 'exhausted' if remaining <= 0.0001 else 'available',
            'sell_price': custom_price,
            'price_mode': 'custom' if custom_price is not None else 'normal',
            'effective_sell_price': custom_price if custom_price is not None else card_price,
        }
        if see_cost:
            item['unit_cost'] = round(float(_cost_value(row, 7, 'unit_cost') or 0), 4)
            item['purchase_unit_cost'] = round(float(_cost_value(row, 8, 'purchase_unit_cost') or item['unit_cost']), 4)
            item['extra_unit_cost'] = round(float(_cost_value(row, 9, 'extra_unit_cost') or 0), 4)
        found.append(item)
        if len(found) >= int(limit):
            break
    return found


def batch_price_sale_review(db, items) -> dict | None:
    """Stop a sale that ignores a custom batch selling price.

    A normal product price, including a cashier discount, is left alone.
    A custom batch price must be charged on its own line. The sale is not posted.
    """
    grouped = {}
    for item in items or []:
        pid = item.get('product_id')
        if not pid or item.get('layer_id') or item.get('fifo_override'):
            continue
        try:
            qty = round(float(item.get('quantity') or 0), 4)
            price = round(float(item.get('unit_price') or 0), 4)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        bucket = grouped.setdefault(int(pid), {'qty': 0.0, 'amount': 0.0})
        bucket['qty'] = round(bucket['qty'] + qty, 4)
        bucket['amount'] = round(bucket['amount'] + qty * price, 2)
    reviews = []
    for pid, bucket in grouped.items():
        row = db.execute(
            "SELECT name, price FROM products WHERE id=?", (pid,),
        ).fetchone()
        if not row:
            continue
        name = _cost_value(row, 0, 'name') or ''
        card = _cost_value(row, 1, 'price') or 0
        quote = quote_fifo_sell_prices(db, pid, bucket['qty'], card)
        if quote.get('error') or float(quote.get('uncovered') or 0) > 0.0001:
            continue
        segments = quote.get('segments') or []
        if not any(part.get('price_mode') == 'custom' for part in segments):
            continue
        if abs(bucket['amount'] - float(quote.get('total') or 0)) <= 0.05:
            continue
        reviews.append({
            'product_id': pid,
            'product_name': name,
            'quantity': bucket['qty'],
            'charged': bucket['amount'],
            'expected': quote['total'],
            'segments': segments,
        })
    if not reviews:
        return None
    return {
        'error': (
            'This sale uses batches with their own selling prices. '
            'The cart has been split. Take payment again.'
        ),
        'code': 'batch_price_review',
        'lines': reviews,
    }


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
        tracked = db.execute(
            "SELECT 1 FROM cost_layers WHERE product_id=? AND source_type!='opening' LIMIT 1",
            (pid,),
        ).fetchone()
        if tracked:
            report.append({'product_id': pid, 'name': name, 'status': 'already_tracked'})
            continue
        if cost is None or float(cost) < 0:
            report.append({'product_id': pid, 'name': name, 'status': 'missing_cost'})
            continue
        result = add_layer(
            db, pid, qty, float(cost), 'opening', str(pid),
            product_name=name,
            purchase_unit_cost=float(cost),
            extra_unit_cost=0,
            supplier_name='Opening stock',
            reference_note='Inherited from the product cost. Supplier unknown.',
        )
        report.append({
            'product_id': pid,
            'name': name,
            'status': 'duplicate' if result.get('duplicate') else 'created',
            'quantity': qty,
            'unit_cost': float(cost),
        })
    return report
