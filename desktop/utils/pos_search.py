"""In-memory POS catalog search — name / SKU / barcode, ranked, no UI.

Cashiers type into the checkout search bar. The catalog is already loaded;
this module must stay cheap on every keystroke (no difflib unless a miss).
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

SEARCH_LIMIT = 48
_FUZZY_MAX_CATALOG = 800
_FUZZY_MIN_LEN = 3


def normalize_query(text) -> str:
    return ' '.join(str(text or '').strip().lower().split())


def _norm_field(value) -> str:
    return ' '.join(str(value or '').strip().lower().split())


def _compact(value: str) -> str:
    return ''.join(ch for ch in (value or '') if ch.isalnum())


def product_search_fields(product: dict) -> tuple:
    name = _norm_field(product.get('name'))
    sku = _norm_field(product.get('sku'))
    barcode = _norm_field(product.get('barcode'))
    pid = str(product.get('id') or '').strip().lower()
    return name, sku, barcode, pid


def match_score(query: str, product: dict, *, in_category: bool = True) -> Optional[int]:
    """Lower is better. None = no match. Category boost is a small rank bump only."""
    q = normalize_query(query)
    if not q:
        return 50
    name, sku, barcode, pid = product_search_fields(product)
    q_c = _compact(q)
    sku_c = _compact(sku)
    bar_c = _compact(barcode)

    if q == sku or q == barcode or q == pid:
        base = 0
    elif q_c and len(q_c) >= 4 and (q_c == sku_c or q_c == bar_c):
        base = 0
    elif name == q:
        base = 1
    elif sku.startswith(q) or barcode.startswith(q) or (q_c and (sku_c.startswith(q_c) or bar_c.startswith(q_c))):
        base = 2
    elif name.startswith(q) or f' {q}' in f' {name}':
        base = 3
    elif q in name or q in sku or q in barcode:
        base = 4
    elif q_c and len(q_c) >= 3 and (q_c in sku_c or q_c in bar_c):
        base = 4
    else:
        return None
    if not in_category:
        base += 8
    return base


def filter_pos_products(
    products: Iterable[dict],
    query: str,
    *,
    category: str = '',
    cat_match: Optional[Callable[[dict], bool]] = None,
    limit: int = SEARCH_LIMIT,
) -> list:
    """Return ranked matches. Empty query = browse (category applies, catalog order).

    Non-empty query searches the whole sellable catalog so a leftover category
    chip cannot hide a valid name/SKU/barcode hit. Same-category rows still
    rank first.
    """
    items = list(products or [])
    q = normalize_query(query)
    cat = (category or '').strip()
    browse_cat = cat not in ('', 'All Categories', 'All')

    def _in_cat(p) -> bool:
        if not browse_cat:
            return True
        if cat_match is not None:
            try:
                return bool(cat_match(p))
            except Exception:
                return (p.get('category') or 'General') == cat
        return (p.get('category') or 'General') == cat

    if not q:
        if not browse_cat:
            return items
        return [p for p in items if _in_cat(p)]

    scored = []
    for p in items:
        score = match_score(q, p, in_category=_in_cat(p))
        if score is None:
            continue
        scored.append((score, (p.get('name') or '').lower(), p))
    if not scored and len(q) >= _FUZZY_MIN_LEN and len(items) <= _FUZZY_MAX_CATALOG:
        scored = _fuzzy_fallback(items, q, _in_cat)
    scored.sort(key=lambda row: (row[0], row[1]))
    return [p for _, __, p in scored[:limit]]


def _fuzzy_fallback(items, q: str, in_cat) -> list:
    import difflib
    names = {}
    for p in items:
        n = _norm_field(p.get('name'))
        if n and n not in names:
            names[n] = p
    close = difflib.get_close_matches(q, names.keys(), n=12, cutoff=0.72)
    out = []
    for n in close:
        p = names[n]
        out.append((20 if in_cat(p) else 28, n, p))
    return out
