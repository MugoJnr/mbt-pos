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
    have = {row[1] for row in db.execute("PRAGMA table_info(cost_layers)").fetchall()}
    for name, decl in (
        ("supplier_id", "INTEGER"),
        ("supplier_name", "TEXT"),
        ("reference_note", "TEXT"),
        ("purchase_unit_cost", "REAL"),
        ("extra_unit_cost", "REAL DEFAULT 0"),
        ("product_name", "TEXT"),
        ("username", "TEXT"),
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
        'extra_unit_cost', 'product_name', 'username',
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
    return {'success': True, 'restored': restored}


def restore_sale_product_qty(db, sale_id: int, product_id: int, qty: float) -> dict:
    """Put back the newest FIFO uses for one product on one sale, up to qty."""
    ensure_cost_layers(db)
    need = round(float(qty), 4)
    if need <= 0:
        return {'error': 'Quantity must be greater than zero'}
    uses = db.execute(
        "SELECT id, layer_id, quantity FROM cost_layer_uses "
        "WHERE sale_id=? AND product_id=? AND COALESCE(reversed,0)=0 "
        "ORDER BY id DESC",
        (int(sale_id), int(product_id)),
    ).fetchall()
    if not uses:
        return {'skipped': True, 'restored': 0}
    left = need
    restored = 0.0
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
        if take + 0.0001 >= available:
            db.execute("UPDATE cost_layer_uses SET reversed=1 WHERE id=?", (use[0],))
        else:
            db.execute(
                "UPDATE cost_layer_uses SET quantity=quantity-? WHERE id=?",
                (take, use[0]),
            )
        left = round(left - take, 4)
    return {'success': True, 'restored': restored, 'uncosted': round(max(left, 0), 4)}


def period_profit(db, start: str, end: str) -> dict:
    """Profit from the FIFO cost actually consumed. Sales with no layer are uncosted."""
    ensure_cost_layers(db)
    cols = {row[1] for row in db.execute("PRAGMA table_info(sale_items)").fetchall()}
    if "returned_qty" not in cols:
        db.execute("ALTER TABLE sale_items ADD COLUMN returned_qty REAL DEFAULT 0")
    day = "COALESCE(NULLIF(s.sale_date,''), date(s.created_at))"
    rows = db.execute(
        f"""
        SELECT CASE
                 WHEN COALESCE(si.quantity, 0) = 0 THEN 0
                 ELSE si.total * (
                   COALESCE(si.quantity, 0) - COALESCE(si.returned_qty, 0)
                 ) / si.quantity
               END AS total,
               (SELECT COUNT(*) FROM cost_layer_uses u
                WHERE u.sale_id=si.sale_id AND u.product_id=si.product_id
                  AND COALESCE(u.reversed,0)=0) AS uses,
               (SELECT COALESCE(SUM(u.quantity * u.unit_cost), 0) FROM cost_layer_uses u
                WHERE u.sale_id=si.sale_id AND u.product_id=si.product_id
                  AND COALESCE(u.reversed,0)=0) AS cogs
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        WHERE {day} BETWEEN ? AND ?
          AND COALESCE(s.status,'completed')='completed'
        """,
        (str(start)[:10], str(end)[:10]),
    ).fetchall()
    revenue = cogs = uncosted = 0.0
    costed_lines = uncosted_lines = 0
    for total, uses, line_cogs in rows:
        amount = float(total or 0)
        if int(uses or 0) > 0:
            revenue += amount
            cogs += float(line_cogs or 0)
            costed_lines += 1
        else:
            uncosted += amount
            uncosted_lines += 1
    return {
        'profit': round(revenue - cogs, 2),
        'revenue_costed': round(revenue, 2),
        'cogs': round(cogs, 2),
        'uncosted_revenue': round(uncosted, 2),
        'uncosted_lines': uncosted_lines,
        'costed_lines': costed_lines,
    }


def inventory_valuation(db) -> dict:
    """Remaining quantity and cost from the batch ledger, not the latest product cost."""
    ensure_cost_layers(db)
    row = db.execute(
        "SELECT COALESCE(SUM(remaining_qty),0), COALESCE(SUM(remaining_qty * unit_cost),0) "
        "FROM cost_layers"
    ).fetchone()
    return {
        'quantity': round(float(row[0] or 0), 4),
        'value': round(float(row[1] or 0), 2),
    }


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
        item = {
            'id': row['id'],
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
            'status': 'exhausted' if remaining <= 0.0001 else 'available',
            'legacy': legacy,
            'cost_origin': origin,
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
