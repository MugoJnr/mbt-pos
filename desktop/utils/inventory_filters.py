"""Inventory list filters. They read stock and categories. They do not write them.

Available stock is products.stock. Sales, receipts, and adjustments already
keep that quantity current, including decimal amounts. There is no second
reserved-stock column to subtract.
"""
from __future__ import annotations

UNCATEGORISED = "__uncategorised__"


def available_qty(product) -> float:
    raw = (product or {}).get("stock")
    if raw is None or raw == "":
        return 0.0
    try:
        qty = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if qty != qty:
        return 0.0
    return qty


def reorder_level(product):
    """The product's own threshold. Missing means this product has no low-stock line."""
    raw = (product or {}).get("min_stock")
    if raw is None or raw == "":
        return None
    try:
        level = float(raw)
    except (TypeError, ValueError):
        return None
    if level != level:
        return None
    return level


def stock_band(product) -> str:
    """in, low, or out. Zero and negative stock are out, never in stock."""
    qty = available_qty(product)
    if qty <= 0:
        return "out"
    level = reorder_level(product)
    if level is not None and qty <= level:
        return "low"
    return "in"


def assigned_category(product) -> str:
    return " ".join(str((product or {}).get("category") or "").replace("\u00a0", " ").split())


def catalog_matches(query, product) -> bool:
    """Name, SKU, or barcode. Empty search matches every product."""
    q = " ".join(str(query or "").strip().lower().split())
    if not q:
        return True
    for key in ("name", "sku", "barcode"):
        text = " ".join(str((product or {}).get(key) or "").strip().lower().split())
        if q in text:
            return True
    return False


def category_matches(product, selected: str) -> bool:
    choice = str(selected or "").strip()
    if choice in ("", "all"):
        return True
    label = assigned_category(product)
    if choice == UNCATEGORISED:
        return label == ""
    return label.casefold() == " ".join(choice.split()).casefold()


def filter_inventory(products, *, query="", status="all", category="all") -> list:
    band = str(status or "all")
    matched = []
    for product in products or []:
        if not catalog_matches(query, product):
            continue
        if band not in ("", "all") and stock_band(product) != band:
            continue
        if not category_matches(product, category):
            continue
        matched.append(product)
    return matched


def _stamp(product, key: str) -> str:
    return str((product or {}).get(key) or "").strip()


def _name(product) -> str:
    return str((product or {}).get("name") or "").casefold()


def _pid(product) -> int:
    try:
        return int((product or {}).get("id") or 0)
    except (TypeError, ValueError):
        return 0


def sort_inventory(products, mode: str = "name_asc") -> list:
    """Return a new list. The caller's product records stay in their original order."""
    rows = list(products or [])
    kind = mode or "name_asc"
    if kind == "name_desc":
        rows.sort(key=lambda product: (_name(product), _pid(product)), reverse=True)
    elif kind == "stock_asc":
        rows.sort(key=lambda product: (available_qty(product), _name(product), _pid(product)))
    elif kind == "stock_desc":
        rows.sort(key=lambda product: (-available_qty(product), _name(product), _pid(product)))
    elif kind == "price_asc":
        rows.sort(key=lambda product: (float(product.get("price") or 0), _name(product), _pid(product)))
    elif kind == "price_desc":
        rows.sort(key=lambda product: (-float(product.get("price") or 0), _name(product), _pid(product)))
    elif kind == "category_asc":
        rows.sort(key=lambda product: (assigned_category(product).casefold(), _name(product), _pid(product)))
    elif kind == "category_desc":
        rows.sort(key=lambda product: (assigned_category(product).casefold(), _name(product), _pid(product)), reverse=True)
    elif kind in ("created", "updated"):
        field = "created_at" if kind == "created" else "updated_at"
        dated = [product for product in rows if _stamp(product, field)]
        undated = [product for product in rows if not _stamp(product, field)]
        dated.sort(key=lambda product: (_name(product), _pid(product)))
        dated.sort(key=lambda product: _stamp(product, field), reverse=True)
        undated.sort(key=lambda product: (_name(product), _pid(product)))
        return dated + undated
    else:
        rows.sort(key=lambda product: (_name(product), _pid(product)))
    return rows
