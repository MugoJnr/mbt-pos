"""Administrator correction for sold lines that have no cost record.

A correction writes an audit row and a cost use. It does not change the sale total.
"""
from __future__ import annotations

from datetime import datetime


def _money(value) -> float:
    return round(float(value or 0), 2)


def ensure_reconciliation(db) -> None:
    from desktop.utils.stock_layers import ensure_cost_layers
    ensure_cost_layers(db)
    db.execute(
        """CREATE TABLE IF NOT EXISTS cost_reconciliations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER,
            product_id INTEGER,
            product_name TEXT,
            quantity REAL,
            previous_unit_cost REAL,
            new_unit_cost REAL,
            revenue REAL,
            reason TEXT NOT NULL,
            evidence TEXT,
            username TEXT,
            created_at TEXT,
            affects_historical_profit INTEGER DEFAULT 1
        )"""
    )
    cols = {row[1] for row in db.execute("PRAGMA table_info(sale_items)").fetchall()}
    if "returned_qty" not in cols:
        db.execute("ALTER TABLE sale_items ADD COLUMN returned_qty REAL DEFAULT 0")


def _stamp(value) -> str:
    return str(value or "").replace("T", " ")[:19]


def classify_missing_cost(db, product_id, sold_at) -> str:
    """Why a sold line has no cost use. This does not invent a cost."""
    if not product_id:
        return "missing_product"
    product = db.execute(
        "SELECT cost_price FROM products WHERE id=?",
        (int(product_id),),
    ).fetchone()
    if not product:
        return "missing_product"
    raw = product["cost_price"] if hasattr(product, "keys") else product[0]
    try:
        card = float(raw)
    except (TypeError, ValueError):
        card = None
    known = raw is not None and card is not None and card > 0
    layers = db.execute(
        """SELECT COUNT(*), MIN(created_at),
                  SUM(CASE WHEN source_type IN ('purchase', 'receipt') THEN 1 ELSE 0 END)
           FROM cost_layers WHERE product_id=?""",
        (int(product_id),),
    ).fetchone()
    count = int(layers[0] or 0)
    if count <= 0:
        return "cost_on_card_not_copied" if known else "no_buying_price"
    earliest = _stamp(layers[1])
    sold = _stamp(sold_at)
    if earliest and sold and earliest > sold:
        return "sold_before_cost_layers"
    if int(layers[2] or 0) > 0:
        return "purchase_layers_not_applied"
    return "layers_present_but_not_applied"


def list_uncosted(db, start: str, end: str, sample_limit: int = 100) -> dict:
    ensure_reconciliation(db)
    start = str(start or "")[:10]
    end = str(end or start)[:10]
    day = "COALESCE(NULLIF(s.sale_date,''), date(s.created_at))"
    rows = db.execute(
        f"""SELECT s.id, s.receipt_number, s.created_at, s.total,
                   si.product_id, si.product_name,
                   CASE WHEN COALESCE(si.quantity,0)=0 THEN 0
                        ELSE si.total * (COALESCE(si.quantity,0) - COALESCE(si.returned_qty,0))
                             / si.quantity END AS net_total,
                   COALESCE(si.quantity,0) - COALESCE(si.returned_qty,0) AS net_qty
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            WHERE {day} BETWEEN ? AND ?
              AND COALESCE(s.status,'completed')='completed'
              AND NOT EXISTS (
                  SELECT 1 FROM cost_layer_uses u
                  WHERE u.sale_id=si.sale_id AND u.product_id=si.product_id
                    AND COALESCE(u.reversed,0)=0
              )""",
        (start, end),
    ).fetchall()
    categories = {}
    sample = []
    revenue = 0.0
    for row in rows:
        item = dict(row) if hasattr(row, "keys") else None
        if item is None:
            item = {
                "id": row[0], "receipt_number": row[1], "created_at": row[2],
                "total": row[3], "product_id": row[4], "product_name": row[5],
                "net_total": row[6], "net_qty": row[7],
            }
        net = float(item.get("net_total") or 0)
        revenue += net
        category = classify_missing_cost(db, item.get("product_id"), item.get("created_at"))
        bucket = categories.setdefault(category, {"lines": 0, "revenue": 0.0})
        bucket["lines"] += 1
        bucket["revenue"] = _money(bucket["revenue"] + net)
        if len(sample) < sample_limit:
            sample.append({
                "sale_id": item.get("id"),
                "receipt_number": item.get("receipt_number") or "",
                "product_id": item.get("product_id"),
                "product_name": item.get("product_name") or "",
                "quantity": round(float(item.get("net_qty") or 0), 4),
                "revenue": _money(net),
                "category": category,
            })
    for bucket in categories.values():
        bucket["revenue"] = _money(bucket["revenue"])
    return {
        "period_start": start,
        "period_end": end,
        "lines": len(rows),
        "revenue": _money(revenue),
        "categories": categories,
        "sample": sample,
    }


def apply_cost(db, sale_id: int, product_id: int, unit_cost, reason: str,
               username: str, evidence: str = "") -> dict:
    """Record a cost for one product on one completed sale. Revenue stays as sold."""
    ensure_reconciliation(db)
    reason = (reason or "").strip()
    evidence = (evidence or "").strip()
    try:
        sale_id = int(sale_id)
        product_id = int(product_id)
    except (TypeError, ValueError):
        return {"error": "Choose the sale and the product."}
    if len(reason) < 3:
        return {"error": "Enter a reason for this cost."}
    try:
        cost = round(float(unit_cost), 4)
    except (TypeError, ValueError):
        return {"error": "Enter a cost greater than zero."}
    if cost <= 0:
        return {"error": "Enter a cost greater than zero. A missing cost is not zero."}
    sale = db.execute(
        "SELECT id, total, status, receipt_number FROM sales WHERE id=?",
        (int(sale_id),),
    ).fetchone()
    if not sale:
        return {"error": "Sale was not found."}
    status = sale["status"] if hasattr(sale, "keys") else sale[2]
    if (status or "completed") != "completed":
        return {"error": "Only a completed sale can receive a cost correction."}
    sale_total = float((sale["total"] if hasattr(sale, "keys") else sale[1]) or 0)
    receipt = sale["receipt_number"] if hasattr(sale, "keys") else sale[3]
    existing = db.execute(
        """SELECT COUNT(*), COALESCE(SUM(quantity * unit_cost), 0)
           FROM cost_layer_uses
           WHERE sale_id=? AND product_id=? AND COALESCE(reversed,0)=0""",
        (int(sale_id), int(product_id)),
    ).fetchone()
    if int(existing[0] or 0) > 0:
        return {"error": "This sale already has a cost for that product."}
    line = db.execute(
        """SELECT COALESCE(SUM(COALESCE(quantity,0) - COALESCE(returned_qty,0)),0),
                  COALESCE(SUM(CASE WHEN COALESCE(quantity,0)=0 THEN 0
                       ELSE total * (COALESCE(quantity,0) - COALESCE(returned_qty,0))
                            / quantity END),0),
                  MAX(product_name)
           FROM sale_items WHERE sale_id=? AND product_id=?""",
        (int(sale_id), int(product_id)),
    ).fetchone()
    qty = round(float(line[0] or 0), 4)
    revenue = _money(line[1])
    name = line[2] or ""
    if qty <= 0:
        return {"error": "That product is not on this sale."}
    from desktop.utils.stock_layers import add_layer, consume_layer
    added = add_layer(
        db, int(product_id), qty, cost, "reconciliation",
        f"recon-{int(sale_id)}-{int(product_id)}",
        product_name=name,
        purchase_unit_cost=cost,
        extra_unit_cost=0,
        supplier_name="Cost correction",
        reference_note=reason,
        username=username or "",
    )
    if added.get("error"):
        return added
    used = consume_layer(
        db, int(added["id"]), qty, sale_id=int(sale_id), reference=receipt or "",
    )
    if not used.get("success"):
        return used if used.get("error") else {"error": "The cost could not be recorded."}
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        """INSERT INTO cost_reconciliations
           (sale_id, product_id, product_name, quantity, previous_unit_cost, new_unit_cost,
            revenue, reason, evidence, username, created_at, affects_historical_profit)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,1)""",
        (int(sale_id), int(product_id), name, qty, None, cost, revenue,
         reason, evidence, username or "", now),
    )
    fresh_total = db.execute("SELECT total FROM sales WHERE id=?", (int(sale_id),)).fetchone()
    return {
        "success": True,
        "sale_id": int(sale_id),
        "product_id": int(product_id),
        "product_name": name,
        "quantity": qty,
        "previous_unit_cost": None,
        "new_unit_cost": cost,
        "revenue": revenue,
        "sale_total": float(fresh_total[0] or 0),
        "sale_total_before": sale_total,
        "affects_historical_profit": True,
        "created_at": now,
    }
