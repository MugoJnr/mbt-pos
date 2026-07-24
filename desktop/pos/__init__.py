"""MBT POS multi-layout checkout — shared controller shells, one backend."""

from desktop.pos.layout_ids import (
    CHECKOUT_LAYOUT_KEY,
    CHECKOUT_LAYOUTS,
    DEFAULT_CHECKOUT_LAYOUT,
    LAYOUT_CHECKOUT_PRO,
    LAYOUT_PRODUCT_EXPLORER,
    LAYOUT_RETAIL_CLASSIC,
    layout_label,
    normalize_layout_id,
)

__all__ = [
    'CHECKOUT_LAYOUT_KEY',
    'CHECKOUT_LAYOUTS',
    'DEFAULT_CHECKOUT_LAYOUT',
    'LAYOUT_CHECKOUT_PRO',
    'LAYOUT_PRODUCT_EXPLORER',
    'LAYOUT_RETAIL_CLASSIC',
    'layout_label',
    'normalize_layout_id',
]
