"""Inventory costing badges.

A blank buying price is missing. A stored zero is an explicit free-stock price
only when the product was confirmed. An older zero, left by the column default,
stays "needs review" and is not relabelled as missing. This module never writes
cost layers or product prices.
"""
from __future__ import annotations


BADGES = {
    "missing_price": ("Missing buying price", "err"),
    "explicit_zero": ("Explicit zero cost", "warn"),
    "invalid_price": ("Invalid buying price", "err"),
    "zero_review": ("Zero buying price needs review", "warn"),
    "missing_fifo": ("Missing FIFO cost layer", "warn"),
    "stock_without_cost": ("Stock without a cost basis", "warn"),
    "inconsistent": ("Costing requires review", "warn"),
    "complete": ("Costing complete", "ok"),
}

_SEVERITY = (
    "invalid_price",
    "missing_price",
    "zero_review",
    "missing_fifo",
    "stock_without_cost",
    "inconsistent",
    "explicit_zero",
    "complete",
)


def _number(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify(cost_price, cost_confirmed, stock, layer_qty, layer_value) -> list:
    """Return badge codes, most serious first. Complete only when nothing else applies."""
    codes = []
    try:
        on_hand = float(stock or 0)
    except (TypeError, ValueError):
        on_hand = 0.0
    confirmed = int(cost_confirmed or 0) == 1
    cost = _number(cost_price)
    if cost_price not in (None, "") and cost is None:
        codes.append("invalid_price")
    elif cost is not None and cost < 0:
        codes.append("invalid_price")
    elif cost is None:
        codes.append("missing_price")
    elif abs(cost) <= 0.0000001 and confirmed:
        codes.append("explicit_zero")
    elif abs(cost) <= 0.0000001:
        codes.append("zero_review")

    try:
        layered = float(layer_qty or 0)
    except (TypeError, ValueError):
        layered = 0.0
    free = "explicit_zero" in codes
    if on_hand > 0.0001 and layered <= 0.0001 and not free:
        codes.append("missing_fifo")
    elif on_hand > 0.0001 and layered + 0.05 < on_hand and not free:
        codes.append("stock_without_cost")

    if cost is not None and cost > 0 and layered > 0.0001:
        try:
            average = float(layer_value or 0) / layered
        except (TypeError, ValueError, ZeroDivisionError):
            average = cost
        if abs(average - cost) > max(1.0, cost * 0.25):
            codes.append("inconsistent")

    if not codes:
        codes.append("complete")
    rank = {code: index for index, code in enumerate(_SEVERITY)}
    codes.sort(key=lambda code: rank.get(code, 99))
    return codes


def _layer_map(db) -> dict:
    from desktop.utils.stock_layers import ensure_cost_layers

    ensure_cost_layers(db)
    rows = db.execute(
        "SELECT product_id, "
        "COALESCE(SUM(CASE WHEN remaining_qty>0 THEN remaining_qty ELSE 0 END),0) AS qty, "
        "COALESCE(SUM(CASE WHEN remaining_qty>0 THEN remaining_qty * unit_cost ELSE 0 END),0) AS value "
        "FROM cost_layers GROUP BY product_id"
    ).fetchall()
    out = {}
    for row in rows:
        product_id = row["product_id"] if hasattr(row, "keys") else row[0]
        qty = row["qty"] if hasattr(row, "keys") else row[1]
        value = row["value"] if hasattr(row, "keys") else row[2]
        out[int(product_id)] = (qty, value)
    return out


def annotate(db, products) -> list:
    """Attach cost_health to product dicts already loaded for the inventory list."""
    if not products:
        return products
    try:
        layers = _layer_map(db)
    except Exception:
        layers = {}
    for product in products:
        if not isinstance(product, dict):
            continue
        try:
            product_id = int(product.get("id") or 0)
        except (TypeError, ValueError):
            product_id = 0
        qty, value = layers.get(product_id, (0, 0))
        codes = classify(
            product.get("cost_price"),
            product.get("cost_confirmed"),
            product.get("stock"),
            qty,
            value,
        )
        product["cost_health"] = {
            "primary": codes[0],
            "badges": [
                {"code": code, "label": BADGES[code][0], "tone": BADGES[code][1]}
                for code in codes
                if code in BADGES
            ],
        }
    return products


def summary_counts(db) -> dict:
    """Counts for the valuation banner. Does not change the FIFO value."""
    columns = {row[1] for row in db.execute("PRAGMA table_info(products)").fetchall()}
    confirmed_sql = "COALESCE(cost_confirmed,0)" if "cost_confirmed" in columns else "0"
    rows = db.execute(
        f"SELECT id, cost_price, {confirmed_sql} AS cost_confirmed, stock "
        "FROM products WHERE COALESCE(is_active,1)=1"
    ).fetchall()
    products = []
    for row in rows:
        if hasattr(row, "keys"):
            products.append({
                "id": row["id"],
                "cost_price": row["cost_price"],
                "cost_confirmed": row["cost_confirmed"],
                "stock": row["stock"],
            })
        else:
            products.append({
                "id": row[0], "cost_price": row[1], "cost_confirmed": row[2], "stock": row[3],
            })
    annotate(db, products)
    counts = {code: 0 for code in BADGES}
    needing = 0
    for product in products:
        badges = (product.get("cost_health") or {}).get("badges") or []
        codes = [item["code"] for item in badges]
        if any(code != "complete" for code in codes):
            needing += 1
        for code in codes:
            counts[code] = counts.get(code, 0) + 1
    return {
        "products_inspected": len(products),
        "products_needing_review": needing,
        "costing_incomplete": needing > 0,
        "missing_buying_price": counts.get("missing_price", 0),
        "explicit_zero_cost": counts.get("explicit_zero", 0),
        "zero_buying_price_review": counts.get("zero_review", 0),
        "invalid_buying_price": counts.get("invalid_price", 0),
        "missing_fifo_layer": counts.get("missing_fifo", 0),
        "stock_without_cost": counts.get("stock_without_cost", 0),
        "costing_review": counts.get("inconsistent", 0),
        "costing_complete": counts.get("complete", 0),
    }
