"""Display helpers: product category vs supplier-tag strings."""
from __future__ import annotations

import re

_SUPPLIER_TAG_RE = re.compile(
    r'(#\d{3,})|(farmcare)|(supplies?\b)|(ltd\.?\b)|(limited\b)|(\bco\.?\b)',
    re.I,
)

# Product-name → retail category (agrovet-first; extend as needed)
_NAME_CAT_HINTS = [
    (('fertilizer', 'fertiliser', 'npk', 'dap', 'urea', 'can ', 'ssp',
      '17-17', '23-23', '20-20', '18-46', '12-24', '10-26', 'diammonium'),
     'Fertilizer'),
    (('pesticide', 'insecticide', 'herbicide', 'fungicide', 'actellic',
      'roundup', 'weed', 'acaricide', 'miticide'), 'Pesticide'),
    (('deworm', 'antibiotic', 'veterinary', 'vet ', 'animal health',
      'oxytet', 'penstrep', 'ivermectin'), 'Veterinary'),
    (('feed', 'dairy meal', 'maize bran', 'pollard', 'layers', 'broiler'),
     'Animal Feed'),
    (('seed', 'seedling', 'hybrid'), 'Seeds'),
    (('tool', 'sprayer', 'knapsack', 'hose'), 'Farm Tools'),
    (('milk', 'yogurt', 'cheese', 'ghee'), 'Dairy'),
]


def looks_like_supplier_tag(value: str) -> bool:
    s = (value or '').strip()
    if not s:
        return False
    if _SUPPLIER_TAG_RE.search(s):
        return True
    # Long free-text with digits often means supplier invoice refs
    if len(s) > 28 and any(ch.isdigit() for ch in s):
        return True
    return False


def infer_category_from_name(product_name: str) -> str:
    low = (product_name or '').strip().lower()
    if not low:
        return ''
    for keys, label in _NAME_CAT_HINTS:
        if any(k in low for k in keys):
            return label
    return ''


def display_category(raw_category: str, product_name: str = '') -> tuple[str, str]:
    """
    Return (label, tooltip) for the Category column / card meta.

    Supplier-like strings (e.g. "Sagana Farmcare #56628") are never shown as
    the category label — we infer from product name or fall back to Uncategorized.
    """
    raw = (raw_category or '').strip()
    name = (product_name or '').strip()

    if raw and not looks_like_supplier_tag(raw):
        tip = raw
        if name:
            tip = f'{raw}\n{name}'
        return raw, tip

    inferred = infer_category_from_name(name)
    if inferred:
        tip = f'Category inferred from product name'
        if raw:
            tip += f'\nSupplier / source tag: {raw}'
        return inferred, tip

    if raw:
        return 'General', f'Supplier / source tag: {raw}'
    return 'General', 'No category set'


def normalize_product_name(name: str) -> str:
    """Light display normalize: NPK dots → hyphens (23.23.0 → 23-23-0)."""
    s = (name or '').strip()
    if not s:
        return s
    # Only touch classic NPK triple patterns
    return re.sub(
        r'\b(\d{1,2})\.(\d{1,2})\.(\d{1,2})\b',
        r'\1-\2-\3',
        s,
    )
