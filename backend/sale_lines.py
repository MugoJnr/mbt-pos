"""Shared sale-line fields for the till and the dashboard.

A missing line total is calculated from quantity, price, and discount.
An explicit total, including zero, is kept. A blank name or SKU is filled
from the product row when a product id is present.
"""


def fill_sale_line(db, item: dict) -> dict:
    pid = item.get('product_id')
    qty = float(item.get('quantity') or 1)
    unit_price = float(item.get('unit_price') or 0)
    discount = float(item.get('discount') or 0)
    raw_total = item.get('total')
    if raw_total is None or raw_total == '':
        line_total = round(qty * unit_price - discount, 2)
    else:
        line_total = float(raw_total)
    product_name = (item.get('product_name') or '').strip()
    sku = (item.get('sku') or '').strip()
    if pid and (not product_name or not sku):
        named = db.execute(
            "SELECT name, sku FROM products WHERE id=?", (pid,)
        ).fetchone()
        if named is not None:
            if hasattr(named, 'keys'):
                stored_name = named['name'] or ''
                stored_sku = named['sku'] or ''
            else:
                stored_name = named[0] or ''
                stored_sku = named[1] or ''
            product_name = product_name or stored_name
            sku = sku or stored_sku
    return {
        'product_id': pid,
        'product_name': product_name,
        'sku': sku,
        'quantity': qty,
        'unit_price': unit_price,
        'discount': discount,
        'total': line_total,
    }
