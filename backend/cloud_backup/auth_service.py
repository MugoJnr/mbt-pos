"""
Business registration & login against Supabase Auth + businesses/devices tables.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.cloud_backup.device_manager import (
    get_device_info,
    get_or_create_device_id,
    mark_cloud_skipped,
    update_business_identity,
)
from backend.cloud_backup.encryption import ensure_identity_key_material, generate_salt
from backend.cloud_backup.paths import (
    is_cloud_configured,
    load_cloud_config,
    load_identity,
    save_cloud_config,
    save_identity,
)
from backend.cloud_backup.supabase_client import SupabaseClient, SupabaseError
from backend.cloud_backup.sync_manager import _app_version

logger = logging.getLogger('cloud_backup.auth')


def create_business(
    email: str,
    password: str,
    business_name: str,
) -> dict[str, Any]:
    if not is_cloud_configured():
        raise SupabaseError('Configure Supabase URL + anon key first (cloud_config.json)')
    email = (email or '').strip().lower()
    business_name = (business_name or '').strip() or 'My Business'
    if len(password or '') < 6:
        raise SupabaseError('Password must be at least 6 characters')

    client = SupabaseClient()
    # Sign up (may already exist — then sign in)
    user_id = ''
    try:
        signup = client.sign_up(email, password, metadata={'business_name': business_name})
        user = signup.get('user') or signup
        user_id = (user.get('id') if isinstance(user, dict) else '') or ''
        # Some projects disable auto-confirm; try sign-in anyway
    except SupabaseError as e:
        logger.info('Sign up note: %s — trying sign in', e)

    session = client.sign_in(email, password)
    user = session.get('user') or {}
    user_id = user.get('id') or user_id
    if not user_id:
        raise SupabaseError('Auth succeeded but no user id returned')

    biz = client.upsert_business(business_name, user_id)
    business_id = biz.get('id') or ''
    if not business_id:
        raise SupabaseError('Could not create/find business row')

    device = get_device_info()
    try:
        client.register_device(
            business_id,
            device['device_id'],
            hostname=device.get('hostname') or '',
            platform_str=device.get('platform') or '',
            mbt_version=_app_version(),
        )
    except Exception as e:
        logger.warning('Device register: %s', e)

    ident = update_business_identity(
        business_id=business_id,
        business_name=business_name,
        user_id=user_id,
        email=email,
        access_token=session.get('access_token') or '',
        refresh_token=session.get('refresh_token') or '',
    )
    # Ensure encryption salt
    _, ident = ensure_identity_key_material(ident, password=password)
    if not ident.get('encryption_salt'):
        ident['encryption_salt'] = generate_salt()
    save_identity(ident)

    cfg = load_cloud_config()
    cfg['enabled'] = True
    save_cloud_config(cfg)

    return {
        'ok': True,
        'business_id': business_id,
        'business_name': business_name,
        'user_id': user_id,
        'email': email,
        'device_id': get_or_create_device_id(),
    }


def login_existing(email: str, password: str) -> dict[str, Any]:
    if not is_cloud_configured():
        raise SupabaseError('Configure Supabase URL + anon key first (cloud_config.json)')
    email = (email or '').strip().lower()
    client = SupabaseClient()
    session = client.sign_in(email, password)
    user = session.get('user') or {}
    user_id = user.get('id') or ''
    if not user_id:
        raise SupabaseError('No user id from login')

    rows = client.rest_select(
        'businesses',
        f'owner_user_id=eq.{user_id}&select=*&limit=1',
    ) or []
    if not rows:
        # Create a business if missing (legacy account)
        biz = client.upsert_business('My Business', user_id)
    else:
        biz = rows[0]
    business_id = biz.get('id') or ''
    business_name = biz.get('name') or 'My Business'

    device = get_device_info()
    try:
        client.register_device(
            business_id,
            device['device_id'],
            hostname=device.get('hostname') or '',
            platform_str=device.get('platform') or '',
            mbt_version=_app_version(),
        )
    except Exception as e:
        logger.warning('Device register: %s', e)

    ident = update_business_identity(
        business_id=business_id,
        business_name=business_name,
        user_id=user_id,
        email=email,
        access_token=session.get('access_token') or '',
        refresh_token=session.get('refresh_token') or '',
    )
    _, ident = ensure_identity_key_material(ident, password=password)
    save_identity(ident)

    cfg = load_cloud_config()
    cfg['enabled'] = True
    save_cloud_config(cfg)

    backups = []
    try:
        backups = client.list_backups(business_id, limit=5)
    except Exception:
        pass

    return {
        'ok': True,
        'business_id': business_id,
        'business_name': business_name,
        'user_id': user_id,
        'email': email,
        'device_id': get_or_create_device_id(),
        'backups': backups,
        'has_backups': bool(backups),
    }


def skip_cloud() -> None:
    mark_cloud_skipped(True)
    cfg = load_cloud_config()
    cfg['enabled'] = False
    save_cloud_config(cfg)


def logout() -> None:
    from backend.cloud_backup.device_manager import clear_session_tokens
    clear_session_tokens()
    cfg = load_cloud_config()
    cfg['enabled'] = False
    save_cloud_config(cfg)
