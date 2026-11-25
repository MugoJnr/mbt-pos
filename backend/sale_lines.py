"""Shared sale-line fields for the till and the dashboard.

A missing line total is calculated from quantity, price, and discount.
An explicit total, including zero, is kept. A blank name or SKU is filled
from the product row when a product id is present.
"""


def fill_sale_line(db, item: dict) -> dict:
    from desktop.utils.quantities import QuantityError, money_amount, parse_quantity
    pid = item.get('product_id')
    unit = item.get('unit')
    product_name = (item.get('product_name') or '').strip()
    sku = (item.get('sku') or '').strip()
    decimal_qty = item.get('allow_decimal_qty', None)
    if pid:
        named = None
        try:
            named = db.execute(
                "SELECT name, sku, unit, allow_decimal_qty FROM products WHERE id=?", (pid,)
            ).fetchone()
        except Exception:
            try:
                named = db.execute(
                    "SELECT name, sku, unit FROM products WHERE id=?", (pid,)
                ).fetchone()
            except Exception:
                named = None
        if named is not None:
            if hasattr(named, 'keys'):
                stored_name = named['name'] or ''
                stored_sku = named['sku'] or ''
                stored_unit = named['unit'] if 'unit' in named.keys() else ''
                if 'allow_decimal_qty' in named.keys():
                    decimal_qty = named['allow_decimal_qty']
            else:
                stored_name = named[0] or ''
                stored_sku = named[1] or ''
                stored_unit = named[2] if len(named) > 2 else ''
            product_name = product_name or stored_name
            sku = sku or stored_sku
            unit = stored_unit or unit
    raw_qty = item.get('quantity', None)
    try:
        if raw_qty is None or raw_qty == '':
            qty = 1.0
        else:
            qty = parse_quantity(raw_qty, unit, decimal_qty=decimal_qty)
    except QuantityError as exc:
        message = str(exc)
        if 'whole units' in message and product_name:
            raise ValueError(f"'{product_name}' is sold in whole units.") from exc
        raise ValueError(message) from exc
    from decimal import Decimal
    try:
        unit_price = float(money_amount(item.get('unit_price') or 0))
        discount = float(money_amount(item.get('discount') or 0))
    except QuantityError as exc:
        raise ValueError(str(exc)) from exc
    if unit_price < 0 or discount < 0:
        raise ValueError('Price and discount cannot be negative')
    raw_total = item.get('total')
    expected = float(money_amount(
        Decimal(str(qty)) * Decimal(str(unit_price)) - Decimal(str(discount))
    ))
    if raw_total is None or raw_total == '':
        line_total = expected
    else:
        line_total = float(raw_total)
        if abs(line_total - expected) > 0.05:
            raise ValueError(
                f"Line total {line_total:.2f} does not match "
                f"{qty:g} at {unit_price:.2f}."
            )
    return {
        'product_id': pid,
        'product_name': product_name,
        'sku': sku,
        'quantity': qty,
        'unit_price': unit_price,
        'discount': discount,
        'total': line_total,
    }
