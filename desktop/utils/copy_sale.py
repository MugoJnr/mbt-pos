"""Turn a saved receipt into cart lines that can still be edited."""
from __future__ import annotations


def copied_cart_lines(items, products_by_id=None) -> list:
    """One editable cart row per saved line.

    Quantity, price and discount come from the receipt. The unit and category
    come from the current product, because a saved line does not store them.
    A line with no product, or a quantity of zero, is left out.
    """
    products_by_id = products_by_id or {}
    out = []
    for it in items or []:
        try:
            pid = int(it.get('product_id') or 0)
        except (TypeError, ValueError):
            continue
        try:
            qty = round(float(it.get('quantity') or 0), 2)
        except (TypeError, ValueError):
            continue
        if pid <= 0 or qty <= 0:
            continue
        product = products_by_id.get(pid) or {}
        try:
            price = round(float(it.get('unit_price') or 0), 2)
        except (TypeError, ValueError):
            price = 0.0
        gross = round(qty * price, 2)
        try:
            disc = float(it.get('discount') or 0)
        except (TypeError, ValueError):
            disc = 0.0
        disc = round(max(0.0, min(disc, gross)), 2)
        out.append({
            'product_id': pid,
            'product_name': it.get('product_name') or product.get('name') or '',
            'sku': it.get('sku') or product.get('sku') or '',
            'category': (product.get('category') or it.get('category') or '').strip(),
            'quantity': qty,
            'unit': product.get('unit') or it.get('unit') or 'pcs',
            'unit_price': price,
            'discount': disc,
            'total': round(gross - disc, 2),
        })
    return out


def place_copied_lines(cart, lines, *, replace: bool = False) -> list:
    """Add copied lines after the ones already in the cart.

    Replace clears the cart first. Each copied line stays its own row, so a
    second receipt does not wipe the first and each quantity can be changed.
    """
    fresh = [dict(line) for line in (lines or [])]
    if replace or not cart:
        return fresh
    return [dict(line) for line in cart] + fresh
