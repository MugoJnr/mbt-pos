"""
Natural-language search stub — maps intents to safe filter dicts.
Never executes arbitrary SQL. Callers apply filters through existing APIs.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List


def parse_nl_search(query: str, module: str = 'inventory') -> Dict[str, Any]:
    """
    Returns:
      {
        'intent': str,
        'filters': dict,   # safe key/value filters
        'explanation': str,
        'supported': bool,
      }
    """
    q = (query or '').strip().lower()
    filters: Dict[str, Any] = {}
    intent = 'unknown'
    explanation = 'Could not map that query to a safe filter yet.'
    supported = False

    if not q:
        return {
            'intent': 'empty',
            'filters': {},
            'explanation': 'Enter a search phrase.',
            'supported': False,
        }

    if any(w in q for w in ('low stock', 'reorder', 'out of stock', 'restock')):
        intent = 'low_stock'
        filters = {'low_stock_only': True}
        explanation = 'Filter: products at or below reorder level.'
        supported = True
    elif re.search(r'\b(debt|overdue|credit)\b', q):
        intent = 'debt_overdue'
        filters = {'status': 'overdue'} if 'overdue' in q else {'has_debt': True}
        explanation = 'Filter: credit customers / overdue debts.'
        supported = True
    elif re.search(r'\b(today|today\'s)\b.*\b(sales?|receipts?)\b', q) or 'sales today' in q:
        intent = 'sales_today'
        filters = {'period': 'today'}
        explanation = 'Filter: sales for today.'
        supported = True
    elif module == 'inventory' and len(q) >= 2:
        intent = 'product_name_contains'
        # Strip filler words
        name = re.sub(
            r'\b(find|show|search|products?|items?|for|me|please)\b', ' ', q)
        name = ' '.join(name.split()).strip()
        if name:
            filters = {'name_contains': name[:80]}
            explanation = f'Filter: product name contains “{name[:80]}”.'
            supported = True
    elif module == 'sales' and re.search(r'receipt\s*#?\s*(\w+)', q):
        m = re.search(r'receipt\s*#?\s*(\w+)', q)
        intent = 'receipt_lookup'
        filters = {'receipt_no': m.group(1)}
        explanation = f'Filter: receipt {m.group(1)}.'
        supported = True

    return {
        'intent': intent,
        'filters': filters,
        'explanation': explanation,
        'supported': supported,
        'query': query,
        'module': module,
    }
