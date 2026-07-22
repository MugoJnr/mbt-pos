"""Single-slot durable park/resume for the POS cart.

Persists one held sale snapshot under app data (`mbt_paths.get_data_dir()`).
Session + disk: survives SalesTab recreate / app restart; cleared on resume.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

HELD_SALE_FILENAME = 'held_sale.json'


def held_sale_path() -> str:
    from mbt_paths import ensure_data_dirs, get_data_dir

    ensure_data_dirs()
    return os.path.join(get_data_dir(), HELD_SALE_FILENAME)


def save_held_sale(snapshot: dict) -> bool:
    """Write a held-sale snapshot. Returns True on success."""
    if not isinstance(snapshot, dict) or not snapshot.get('cart'):
        return False
    path = held_sale_path()
    tmp = path + '.tmp'
    try:
        payload = {
            'version': 1,
            'cart': list(snapshot.get('cart') or []),
            'customer_id': snapshot.get('customer_id'),
            'disc': snapshot.get('disc') or '',
            'note': snapshot.get('note') or '',
            'payment': snapshot.get('payment') or 'Cash',
            'credit_to_apply': float(snapshot.get('credit_to_apply') or 0),
        }
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        logger.warning('save_held_sale failed: %s', e)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def load_held_sale() -> Optional[dict[str, Any]]:
    """Load held sale if present and valid; else None (and wipe corrupt file)."""
    path = held_sale_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            clear_held_sale()
            return None
        cart = data.get('cart')
        if not isinstance(cart, list) or not cart:
            clear_held_sale()
            return None
        return {
            'cart': cart,
            'customer_id': data.get('customer_id'),
            'disc': data.get('disc') or '',
            'note': data.get('note') or '',
            'payment': data.get('payment') or 'Cash',
            'credit_to_apply': float(data.get('credit_to_apply') or 0),
        }
    except Exception as e:
        logger.warning('load_held_sale failed: %s', e)
        clear_held_sale()
        return None


def clear_held_sale() -> None:
    """Remove durable held-sale file if it exists."""
    path = held_sale_path()
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception as e:
        logger.warning('clear_held_sale failed: %s', e)
