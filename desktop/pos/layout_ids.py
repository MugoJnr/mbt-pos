"""Checkout layout identifiers — Settings key + display labels."""

CHECKOUT_LAYOUT_KEY = 'pos_checkout_layout'

LAYOUT_RETAIL_CLASSIC = 'retail_classic'
LAYOUT_SIMPLE_COUNTER = 'simple_counter'
LAYOUT_CHECKOUT_PRO = 'checkout_pro'

# Default is the streamlined counter: catalogue plus one clear sale/payment rail.
DEFAULT_CHECKOUT_LAYOUT = LAYOUT_SIMPLE_COUNTER

CHECKOUT_LAYOUTS = (
    (LAYOUT_RETAIL_CLASSIC, 'Retail Classic'),
    (LAYOUT_SIMPLE_COUNTER, 'Simple Counter'),
    (LAYOUT_CHECKOUT_PRO, 'Checkout Pro'),
)

_ALIASES = {
    'retail': LAYOUT_RETAIL_CLASSIC,
    'classic': LAYOUT_RETAIL_CLASSIC,
    'retail_classic': LAYOUT_RETAIL_CLASSIC,
    # Migrate the retired Product Explorer setting without leaving a shop on an
    # unavailable layout after update.
    'explorer': LAYOUT_SIMPLE_COUNTER,
    'product_explorer': LAYOUT_SIMPLE_COUNTER,
    'current': LAYOUT_SIMPLE_COUNTER,
    'simple': LAYOUT_SIMPLE_COUNTER,
    'simple_counter': LAYOUT_SIMPLE_COUNTER,
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
    return 'Simple Counter'
