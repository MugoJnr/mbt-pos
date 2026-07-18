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
    return f'MBT-PC-{_random_suffix(4)}'


def get_or_create_device_id() -> str:
    ident = load_identity()
    did = (ident.get('device_id') or '').strip()
    if did.startswith('MBT-PC-') and len(did) >= 10:
        return did
    did = generate_device_id()
    ident['device_id'] = did
    if not ident.get('created_at'):
        ident['created_at'] = _utc_now()
    ident['hostname'] = platform.node() or ''
    ident['platform'] = platform.platform()
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
    ident = load_identity()
    ident['access_token'] = ''
    ident['refresh_token'] = ''
    save_identity(ident)
