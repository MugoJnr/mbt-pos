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


def restock_lines(detail: dict, width: int) -> list[str]:
    """Thermal restocking request. Quantities are wrapped, not cut off."""
    width = max(16, int(width or 32))
    lines = ["=" * width, "RESTOCKING REQUEST".center(width)[:width]]
    shop = str(detail.get("shop_name") or "").strip()
    if shop:
        lines.extend(_wrap(shop, width))
    contact = " ".join(
        part for part in (str(detail.get("shop_address") or "").strip(), str(detail.get("shop_phone") or "").strip()) if part
    )
    if contact:
        lines.extend(_wrap(contact, width))
    lines.extend(_wrap("Not a sale, tax invoice, or goods received note.", width))
    lines.append("=" * width)
    lines.extend(_wrap(f"Ref: {detail.get('reference') or ''}", width))
    lines.extend(_wrap(f"List: {detail.get('name') or ''}", width))
    lines.extend(_wrap(f"Status: {detail.get('status_label') or detail.get('status') or ''}", width))
    lines.extend(_wrap(f"Priority: {detail.get('priority') or ''}", width))
    lines.extend(_wrap(f"Prepared: {detail.get('created_at') or ''} {detail.get('created_name') or ''}".strip(), width))
    buyer = detail.get("buyer_name") or detail.get("external_buyer") or "Not assigned"
    lines.extend(_wrap(f"Buyer: {buyer}", width))
    printed = str(detail.get("printed_at") or "").strip()
    if printed:
        lines.extend(_wrap(f"Printed: {printed}", width))
    instructions = str(detail.get("instructions") or "").strip()
    if instructions:
        lines.extend(_wrap(f"Instructions: {instructions}", width))
    lines.append("-" * width)
    for index, line in enumerate(detail.get("lines") or [], start=1):
        unit = str(line.get("unit") or "").strip()
        name = str(line.get("product_name") or "Product")
        sku = str(line.get("sku") or "").strip()
        lines.extend(_wrap(f"{index}. {name}", width))
        if sku:
            lines.extend(_wrap(f"SKU {sku}", width))
        lines.extend(_wrap(f"Asked: {qty_text(line.get('quantity'))} {unit}".strip(), width))
        lines.extend(_wrap(f"Bought: {qty_text(line.get('purchased_qty'))} {unit}".strip(), width))
        lines.extend(_wrap(f"Unavailable: {qty_text(line.get('unavailable_qty'))} {unit}".strip(), width))
        lines.extend(_wrap(f"Received: {qty_text(line.get('received_qty'))} {unit}".strip(), width))
        lines.extend(_wrap(f"Rejected: {qty_text(line.get('rejected_qty'))} {unit}".strip(), width))
        lines.extend(_wrap(f"Outstanding: {qty_text(line.get('outstanding_qty'))} {unit}".strip(), width))
        note = str(line.get("notes") or line.get("purchase_notes") or "").strip()
        if note:
            lines.extend(_wrap(f"Note: {note}", width))
        lines.append("-" * width)
    receipts = detail.get("receipts") or []
    if receipts:
        lines.append("Deliveries".center(width)[:width])
        for receipt in receipts:
            lines.extend(_wrap(
                f"{receipt.get('receipt_number') or receipt.get('receipt_id')} "
                f"accepted {qty_text(receipt.get('qty_accepted'))} "
                f"rejected {qty_text(receipt.get('qty_rejected'))}",
                width,
            ))
        lines.append("-" * width)
    lines.extend(_wrap(
        "THIS IS A RESTOCKING REQUEST. IT IS NOT A SUPPLIER INVOICE OR GOODS RECEIVED NOTE.",
        width,
    ))
    return lines


def goods_received_lines(receipt: dict, width: int = 48, *, show_cost: bool = True) -> list[str]:
    """Supplier goods-received note. This is not a customer sale receipt."""
    width = max(32, int(width or 48))
    lines = ["=" * width, "GOODS RECEIVED NOTE".center(width)[:width]]
    shop = str(receipt.get("shop_name") or "").strip()
    if shop:
        lines.extend(_wrap(shop, width))
    lines.extend(_wrap("Supplier delivery. Not a customer sale.", width))
    lines.append("=" * width)
    lines.extend(_wrap(f"GRN: {receipt.get('receipt_number') or ''}", width))
    lines.extend(_wrap(f"Supplier: {receipt.get('supplier_name') or ''}", width))
    invoice = receipt.get("reference") or receipt.get("reference_note") or ""
    if str(invoice).strip():
        lines.extend(_wrap(f"Supplier invoice: {invoice}", width))
    when = str(receipt.get("effective_date") or receipt.get("created_at") or "")[:19].replace("T", " ")
    if when:
        lines.extend(_wrap(f"Received: {when}", width))
    who = receipt.get("username") or ""
    if who:
        lines.extend(_wrap(f"Received by: {who}", width))
    status = str(receipt.get("status") or "posted")
    lines.extend(_wrap(f"Status: {status}", width))
    notes = str(receipt.get("notes") or "").strip()
    if notes:
        lines.extend(_wrap(f"Notes: {notes}", width))
    lines.append("-" * width)
    for index, line in enumerate(receipt.get("lines") or [], start=1):
        name = line.get("product_name") or line.get("name") or "Product"
        unit = str(line.get("unit") or "").strip()
        lines.extend(_wrap(f"{index}. {name}", width))
        ordered = line.get("ordered_qty")
        received = line.get("quantity")
        rejected = line.get("rejected_qty") or 0
        lines.extend(_wrap(f"Received: {qty_text(received)} {unit}".strip(), width))
        if ordered not in (None, ""):
            lines.extend(_wrap(f"Ordered: {qty_text(ordered)} {unit}".strip(), width))
            try:
                outstanding = max(0.0, float(ordered) - float(received or 0) - float(rejected or 0))
            except (TypeError, ValueError):
                outstanding = 0
            lines.extend(_wrap(f"Outstanding: {qty_text(outstanding)} {unit}".strip(), width))
        if float(rejected or 0) > 0:
            lines.extend(_wrap(f"Rejected: {qty_text(rejected)} {unit} (not added to stock)".strip(), width))
        if show_cost and line.get("unit_cost") is not None:
            lines.extend(_wrap(f"Buying price: {money(line.get('unit_cost'))}", width))
            lines.extend(_wrap(f"Line total: {money(line.get('line_total'))}", width))
        lines.append("-" * width)
    if show_cost:
        lines.extend(_wrap(f"Invoice total: {money(receipt.get('grand_total'))}", width))
    lines.extend(_wrap(f"Paid: {money(receipt.get('amount_paid'))}", width))
    lines.extend(_wrap(f"Outstanding balance: {money(receipt.get('outstanding'))}", width))
    pay_status = receipt.get("payment_status") or ""
    if pay_status:
        lines.extend(_wrap(f"Payment status: {pay_status}", width))
    lines.extend(_wrap("Rejected goods are not sellable stock.", width))
    lines.extend(_wrap("Printing this note does not post the delivery again.", width))
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
