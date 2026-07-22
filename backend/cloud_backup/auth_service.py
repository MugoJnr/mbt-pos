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


def _kickoff_analytics_after_registration(device_row: dict | None) -> None:
    """After auto-approval, clear approval backoff and start backfill/sync ASAP."""
    status = str((device_row or {}).get('approval_status') or '').lower()
    if status != 'approved':
        return
    try:
        from backend.cloud_backup import get_sync_manager
        mgr = get_sync_manager()
        cleared = mgr.clear_device_approval_backoff()
        if cleared:
            logger.info('Cleared approval backoff on %s outbox row(s)', cleared)
        mgr.ensure_historical_backfill()
        mgr.flush_entity_outbox()
    except Exception as e:
        # Sync loop will retry; do not fail sign-in because of a transient kickoff.
        logger.info('Post-registration analytics kickoff deferred: %s', e)


def _register_device_for_business(business: dict, user_id: str, email: str, session: dict) -> None:
    """Register this desktop into Portal devices (auto-approved) and persist org_id."""
    from backend.cloud.platform_service import (
        ensure_org_for_business,
        register_or_refresh_device,
    )

    device = get_device_info()
    business_id = business.get('id') or ''
    business_name = business.get('name') or 'My Business'
    device_row = None
    try:
        org = ensure_org_for_business(business, user_id)
        device_row = register_or_refresh_device(
            org['id'],
            device_id=device['device_id'],
            business_id=business_id or None,
            computer_name=device.get('hostname') or '',
            hostname=device.get('hostname') or '',
            platform_str=device.get('platform') or '',
            mbt_version=_app_version(),
            hardware_fingerprint=device.get('device_id') or '',
            actor_user_id=user_id,
            verify_org_access=True,
        )
        ident = update_business_identity(
            business_id=business_id,
            business_name=business_name,
            user_id=user_id,
            email=email,
            access_token=session.get('access_token') or '',
            refresh_token=session.get('refresh_token') or '',
        )
        ident['org_id'] = org['id']
        save_identity(ident)
        _kickoff_analytics_after_registration(device_row)
    except Exception as e:
        logger.warning('Device register: %s', e)
        try:
            SupabaseClient().register_device(
                business_id,
                device['device_id'],
                hostname=device.get('hostname') or '',
                platform_str=device.get('platform') or '',
                mbt_version=_app_version(),
            )
        except Exception as e2:
            logger.warning('Legacy device register: %s', e2)


def create_business(
    email: str,
    password: str,
    business_name: str,
) -> dict[str, Any]:
    if not is_cloud_configured():
        raise SupabaseError('Configure Supabase URL + anon key first (cloud_config.json)')
    email = (email or '').strip().lower()
    business_name = (business_name or '').strip() or 'My Business'
    if len(password or '') < 12:
        raise SupabaseError('Password must be at least 12 characters')

    # Portal-first path: create unconfirmed Auth user + deliver verification email.
    # Do NOT auto-sign-in — license/device steps require a verified account.
    from backend.cloud.platform_service import cloud_sign_up

    result = cloud_sign_up(email, password, full_name='', business_name=business_name)
    if result.get('verification_required'):
        return {
            'ok': True,
            'verification_required': True,
            'email': email,
            'business_name': business_name,
            'email_sent': bool(result.get('email_sent')),
            'message': result.get('message')
            or 'Check your email to verify the account, then Sign In here.',
            'device_id': get_or_create_device_id(),
        }

    # Confirmed session already returned (should not happen in production).
    client = SupabaseClient()
    session = client.sign_in(email, password)
    user = session.get('user') or {}
    user_id = user.get('id') or ''
    if not user_id:
        raise SupabaseError('Auth succeeded but no user id returned')

    biz = client.upsert_business(business_name, user_id)
    business_id = biz.get('id') or ''
    if not business_id:
        raise SupabaseError('Could not create/find business row')

    _register_device_for_business(
        biz if isinstance(biz, dict) else {'id': business_id, 'name': business_name},
        user_id,
        email,
        session,
    )

    ident = update_business_identity(
        business_id=business_id,
        business_name=business_name,
        user_id=user_id,
        email=email,
        access_token=session.get('access_token') or '',
        refresh_token=session.get('refresh_token') or '',
    )
    _, ident = ensure_identity_key_material(ident, password=password)
    if not ident.get('encryption_salt'):
        ident['encryption_salt'] = generate_salt()
    if not ident.get('org_id'):
        try:
            from backend.cloud.platform_service import ensure_org_for_business
            org = ensure_org_for_business({'id': business_id, 'name': business_name}, user_id)
            ident['org_id'] = org.get('id')
        except Exception:
            pass
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

    _register_device_for_business(biz if isinstance(biz, dict) else {'id': business_id, 'name': business_name}, user_id, email, session)

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
