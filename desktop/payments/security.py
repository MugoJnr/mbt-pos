"""Payment security helpers — mask phones, never log secrets/PINs."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Optional


_SECRET_KEYS = frozenset({
    'consumer_secret', 'consumer_key', 'passkey', 'password', 'pin',
    'access_token', 'refresh_token', 'authorization', 'security_credential',
    'initiator_password', 'api_key', 'secret', 'token',
})


def normalize_ke_phone(raw: str) -> str:
    """Normalize Kenyan MSISDN to 2547XXXXXXXX. Empty if invalid."""
    digits = re.sub(r'\D+', '', str(raw or ''))
    if digits.startswith('0') and len(digits) == 10:
        digits = '254' + digits[1:]
    elif digits.startswith('7') and len(digits) == 9:
        digits = '254' + digits
    elif digits.startswith('254') and len(digits) == 12:
        pass
    else:
        return ''
    if not digits.startswith('2547') and not digits.startswith('2541'):
        # Allow 2547 / 2541 common ranges; reject garbage
        if not digits.startswith('254'):
            return ''
    return digits


def mask_phone(raw: str) -> str:
    """Mask MSISDN for UI/logs: 2547****123."""
    phone = normalize_ke_phone(raw) or re.sub(r'\D+', '', str(raw or ''))
    if len(phone) < 6:
        return '***'
    return f'{phone[:4]}****{phone[-3:]}'


def cart_fingerprint(cart: list, total: float) -> str:
    """Stable hash of cart lines + total for restart recovery."""
    parts = []
    for item in cart or []:
        parts.append(
            f"{item.get('product_id')}|{item.get('quantity')}|{item.get('unit_price')}|"
            f"{item.get('discount') or 0}"
        )
    blob = '\n'.join(parts) + f'\nTOTAL={round(float(total or 0), 2)}'
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:32]


def redact_for_log(payload: Any) -> Any:
    """Deep-redact secrets and full phone numbers from structures before logging."""
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            lk = str(k).lower()
            if lk in _SECRET_KEYS or any(s in lk for s in ('secret', 'passkey', 'password', 'pin')):
                out[k] = '***REDACTED***'
            elif 'phone' in lk:
                out[k] = mask_phone(str(v))
            else:
                out[k] = redact_for_log(v)
        return out
    if isinstance(payload, list):
        return [redact_for_log(x) for x in payload]
    return payload


def assert_no_pin(text: str) -> None:
    """Refuse to store/log anything that looks like an M-Pesa PIN entry."""
    # Soft guard — cashiers must never type PIN into POS
    if re.search(r'\bpin\s*[:=]\s*\d{4,6}\b', str(text or ''), re.I):
        raise ValueError('M-Pesa PIN must never be entered into POS.')
