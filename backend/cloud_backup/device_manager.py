"""
Persistent device identity: MBT-PC-XXXX stored in AppData cloud_identity.json.
"""
from __future__ import annotations

import logging
import platform
import random
import string
from datetime import datetime, timezone

from backend.cloud_backup.paths import load_identity, save_identity

logger = logging.getLogger('cloud_backup.device')


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _random_suffix(n: int = 4) -> str:
    alphabet = string.ascii_uppercase + string.digits
    # Avoid ambiguous 0/O/1/I
    alphabet = alphabet.replace('0', '').replace('O', '').replace('1', '').replace('I', '')
    return ''.join(random.choice(alphabet) for _ in range(n))


def generate_device_id() -> str:
    """Stable MBT-PC id for this Windows install (not a new random id each launch)."""
    try:
        from licensing.license_engine import _win_machine_guid
        mg = (_win_machine_guid() or '').strip()
    except Exception:
        mg = ''
    if mg:
        import hashlib
        suffix = hashlib.sha256(f'mbt-pc:{mg}'.encode()).hexdigest()[:8].upper()
        return f'MBT-PC-{suffix}'
    return f'MBT-PC-{_random_suffix(4)}'


def get_or_create_device_id() -> str:
    ident = load_identity()
    did = (ident.get('device_id') or '').strip()

    # Always keep hardware_fingerprint aligned with stable MachineGuid bind id.
    try:
        from licensing.license_engine import _get_device_fingerprint
        fp = _get_device_fingerprint()
        if fp and str(ident.get('hardware_fingerprint') or '').strip() != fp:
            ident['hardware_fingerprint'] = fp
            save_identity(ident)
    except Exception:
        pass

    if did.startswith('MBT-PC-') and len(did) >= 10:
        return did
    if len(did) == 40 and all(c in '0123456789abcdef' for c in did.lower()):
        return did
    did = generate_device_id()
    ident['device_id'] = did
    if not ident.get('created_at'):
        ident['created_at'] = _utc_now()
    ident['hostname'] = platform.node() or ''
    ident['platform'] = platform.platform()
    try:
        from licensing.license_engine import _get_device_fingerprint
        ident['hardware_fingerprint'] = _get_device_fingerprint()
    except Exception:
        pass
    save_identity(ident)
    logger.info('Assigned device_id=%s', did)
    return did


def get_device_info() -> dict:
    ident = load_identity()
    did = get_or_create_device_id()
    return {
        'device_id': did,
        'hostname': ident.get('hostname') or platform.node() or '',
        'platform': ident.get('platform') or platform.platform(),
        'business_id': ident.get('business_id') or '',
        'business_name': ident.get('business_name') or '',
        'email': ident.get('email') or '',
        'created_at': ident.get('created_at') or '',
    }


def mark_cloud_skipped(skipped: bool = True) -> None:
    ident = load_identity()
    ident['cloud_skipped'] = bool(skipped)
    if not ident.get('device_id'):
        ident['device_id'] = generate_device_id()
    save_identity(ident)


def update_business_identity(
    business_id: str,
    business_name: str = '',
    user_id: str = '',
    email: str = '',
    access_token: str = '',
    refresh_token: str = '',
) -> dict:
    ident = load_identity()
    if not ident.get('device_id'):
        ident['device_id'] = generate_device_id()
    if not ident.get('created_at'):
        ident['created_at'] = _utc_now()
    ident['business_id'] = business_id
    if business_name:
        ident['business_name'] = business_name
    if user_id:
        ident['user_id'] = user_id
    if email:
        ident['email'] = email
    if access_token:
        ident['access_token'] = access_token
    if refresh_token:
        ident['refresh_token'] = refresh_token
    ident['cloud_skipped'] = False
    ident['hostname'] = platform.node() or ''
    ident['platform'] = platform.platform()
    save_identity(ident)
    return ident


def clear_session_tokens() -> None:
    """Sign out of MugoByte Cloud on this device.

    The sealed ``*_protected`` copies have to be cleared explicitly:
    ``save_identity`` deliberately keeps an existing ciphertext when the
    plaintext is empty, so that an identity which merely failed to decrypt is
    never destroyed. A real sign-out must leave nothing usable behind.
    """
    ident = load_identity()
    for name in ('access_token', 'refresh_token'):
        ident[name] = ''
        ident[f'{name}_protected'] = ''
    ident.pop('auth_state', None)
    ident.pop('auth_error', None)
    ident.pop('auth_unreadable_id', None)
    save_identity(ident)
