"""One column layout for the till, the dashboard, and thermal paper.

58 mm paper is 32 columns. 80 mm paper is 48 columns. Those counts are the
printable character widths at Font A, not the nominal paper width.
"""
from __future__ import annotations

PAPER = {
    "58": {"mm": 58, "printable_mm": 48, "columns": 32, "dpi": 203},
    "80": {"mm": 80, "printable_mm": 72, "columns": 48, "dpi": 203},
}


def columns_for(paper: str) -> int:
    return PAPER["58"]["columns"] if str(paper or "80").strip() in ("58", "58mm") else PAPER["80"]["columns"]


def money(value) -> str:
    return f"{round(float(value or 0), 2):,.2f}"


def qty_text(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    if abs(number - round(number)) < 0.0001:
        return str(int(round(number)))
    return f"{number:.3f}".rstrip("0").rstrip(".")


def _fit(left: str, right: str, width: int) -> str:
    left = str(left or "")
    right = str(right or "")
    if len(left) + 1 + len(right) > width:
        keep = max(1, width - len(right) - 1)
        left = left[:keep]
    gap = width - len(left) - len(right)
    if gap < 1:
        return (left + " " + right)[:width]
    return left + (" " * gap) + right


def _wrap(text: str, width: int) -> list[str]:
    words = str(text or "").split()
    if not words:
        return [""]
    lines = []
    current = ""
    for word in words:
        piece = word if len(word) <= width else word[:width]
        extra = word[width:]
        trial = piece if not current else f"{current} {piece}"
        if len(trial) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = piece
        while extra:
            lines.append(extra[:width])
            extra = extra[width:]
            current = ""
    if current:
        lines.append(current)
    return lines or [""]


def sale_item_lines(items, width: int, *, show_money: bool = True) -> list[str]:
    """Product, quantity, unit, price, and total. Nothing overlaps."""
    lines = []
    wide = width >= 40 and show_money
    if wide:
        total_w, price_w, qty_w = 9, 8, 8
        name_w = width - total_w - price_w - qty_w - 3
        lines.append(
            f"{'Product':<{name_w}} {'Qty':>{qty_w}} {'Price':>{price_w}} {'Total':>{total_w}}"[:width]
        )
    else:
        lines.append("Product")
    for item in items or []:
        name = str(item.get("product_name") or item.get("name") or "Item")
        unit = str(item.get("unit") or "").strip()
        qty = qty_text(item.get("quantity"))
        qty_unit = f"{qty} {unit}".strip()
        if not show_money:
            lines.extend(_wrap(name, width))
            lines.append(f"  {qty_unit}"[:width])
            continue
        price = money(item.get("unit_price") if item.get("unit_price") is not None else item.get("unit_cost"))
        total = money(item.get("total") if item.get("total") is not None else item.get("total_cost"))
        fits = wide and len(qty_unit) <= qty_w and len(price) <= price_w and len(total) <= total_w
        if fits:
            name_lines = _wrap(name, name_w) or [""]
            first = (
                f"{name_lines[0]:<{name_w}} {qty_unit:>{qty_w}} {price:>{price_w}} {total:>{total_w}}"
            )
            lines.append(first[:width])
            for extra in name_lines[1:]:
                lines.append(extra[:width])
        else:
            lines.extend(_wrap(name, width))
            lines.append(_fit(f"  {qty_unit}", f"{price} {total}", width))
        discount = float(item.get("discount") or 0)
        if discount > 0:
            lines.append(_fit("  Discount", f"-{money(discount)}", width))
    return lines


def consumption_lines(detail: dict, width: int, *, show_cost: bool) -> list[str]:
    """Internal use. This document has no customer payment."""
    header = detail.get("header") or detail
    lines = [
        "=" * width,
        "INTERNAL CONSUMPTION".center(width)[:width],
        "Not a customer sale".center(width)[:width],
        "=" * width,
    ]
    shop = str(detail.get("shop_name") or header.get("shop_name") or "").strip()
    if shop:
        lines.insert(1, shop.center(width)[:width])
    voided = int(header.get("voided") or detail.get("voided") or 0) == 1
    requested = bool(header.get("void_requested") or detail.get("void_requested"))
    status = "Voided" if voided else "Void requested" if requested else "Posted"
    lines.append(_fit("Status:", status, width))
    lines.append(_fit("Number:", str(detail.get("reference") or header.get("reference_no") or ""), width))
    business = str(header.get("date") or "")[:10]
    recorded = str(header.get("created_at") or "")[:19].replace("T", " ")
    if business:
        lines.append(_fit("Business date:", business, width))
    if recorded:
        lines.append(_fit("Recorded:", recorded, width))
    lines.append(_fit("User:", str(header.get("created_by_name") or "—"), width))
    lines.append(_fit("Department:", str(header.get("department_name") or "—"), width))
    lines.append(_fit("Taken by:", str(header.get("taken_by") or "—"), width))
    lines.append(_fit("Purpose:", str(header.get("reason") or "—"), width))
    notes = str(header.get("notes") or "").strip()
    if notes:
        for note in _wrap(f"Notes: {notes}", width):
            lines.append(note)
    lines.append("-" * width)
    items = []
    for item in detail.get("lines") or detail.get("items") or []:
        row = dict(item)
        if show_cost and row.get("total") is None:
            row["total"] = row.get("total_cost")
            row["unit_price"] = row.get("unit_cost")
        items.append(row)
    lines.extend(sale_item_lines(items, width, show_money=show_cost))
    lines.append("-" * width)
    if show_cost:
        total = header.get("total_cost")
        if total is None:
            total = detail.get("total_cost") or 0
        lines.append(_fit("Stock cost:", money(total), width))
    lines.append("No customer payment.".center(width)[:width])
    if voided:
        lines.append("VOIDED".center(width)[:width])
        reason = str(header.get("void_reason") or "").strip()
        if reason:
            lines.extend(_wrap(f"Void reason: {reason}", width))
    return [line[:width] for line in lines]


def centre_lines(detail: dict, width: int) -> list[str]:
    """Plain reading of a receipt-centre document that is not a sale."""
    header = detail.get("header") or {}
    kind = str(detail.get("kind") or "document").replace("_", " ").upper()
    lines = ["=" * width, kind.center(width)[:width], "=" * width]
    lines.append(_fit("Number:", str(detail.get("reference") or ""), width))
    status = str(header.get("status") or header.get("voided") or "").strip()
    if status:
        lines.append(_fit("Status:", status, width))
    when = str(header.get("created_at") or header.get("date") or "")[:19].replace("T", " ")
    if when:
        lines.append(_fit("When:", when, width))
    who = header.get("cashier_name") or header.get("username") or header.get("created_by_name")
    if who:
        lines.append(_fit("Who:", str(who), width))
    lines.append("-" * width)
    lines.extend(sale_item_lines(detail.get("lines") or [], width, show_money=True))
    lines.append("Reprint of a saved document.".center(width)[:width])
    return [line[:width] for line in lines]
