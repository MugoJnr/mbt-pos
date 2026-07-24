"""Checkout layout identifiers — Settings key + display labels."""

CHECKOUT_LAYOUT_KEY = 'pos_checkout_layout'

LAYOUT_RETAIL_CLASSIC = 'retail_classic'
LAYOUT_PRODUCT_EXPLORER = 'product_explorer'
LAYOUT_CHECKOUT_PRO = 'checkout_pro'

# Default matches the prior POS chrome (card grid + Current Sale column).
DEFAULT_CHECKOUT_LAYOUT = LAYOUT_PRODUCT_EXPLORER

CHECKOUT_LAYOUTS = (
    (LAYOUT_RETAIL_CLASSIC, 'Retail Classic'),
    (LAYOUT_PRODUCT_EXPLORER, 'Product Explorer'),
    (LAYOUT_CHECKOUT_PRO, 'Checkout Pro'),
)

_ALIASES = {
    'retail': LAYOUT_RETAIL_CLASSIC,
    'classic': LAYOUT_RETAIL_CLASSIC,
    'retail_classic': LAYOUT_RETAIL_CLASSIC,
    'explorer': LAYOUT_PRODUCT_EXPLORER,
    'product_explorer': LAYOUT_PRODUCT_EXPLORER,
    'current': LAYOUT_PRODUCT_EXPLORER,
    'pro': LAYOUT_CHECKOUT_PRO,
    'checkout_pro': LAYOUT_CHECKOUT_PRO,
    'checkout-pro': LAYOUT_CHECKOUT_PRO,
}


def normalize_layout_id(value) -> str:
    raw = (value or '').strip().lower().replace(' ', '_').replace('-', '_')
    if not raw:
        return DEFAULT_CHECKOUT_LAYOUT
    if raw in _ALIASES:
        return _ALIASES[raw]
    valid = {k for k, _ in CHECKOUT_LAYOUTS}
    return raw if raw in valid else DEFAULT_CHECKOUT_LAYOUT


def layout_label(layout_id: str) -> str:
    lid = normalize_layout_id(layout_id)
    for key, label in CHECKOUT_LAYOUTS:
        if key == lid:
            return label
    return 'Product Explorer'
