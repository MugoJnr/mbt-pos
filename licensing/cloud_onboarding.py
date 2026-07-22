"""
MBT POS — Cloud-first onboarding helper.

Implements the hybrid flow:
    login (MugoByte account) → check device/account for a license seat →
    auto-activate silently → (manual key entry only if no seat / offline).

All cloud calls are best-effort; every failure degrades to the manual
activation screen so an offline machine can still be licensed with a key.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger('cloud_onboarding')

_TERMINAL_STATUSES = frozenset({'revoked', 'suspended', 'expired', 'cancelled'})


def _resolve_org_id(ident: dict) -> str:
    """Best-effort org id for the signed-in user."""
    org_id = str(ident.get('org_id') or '')
    if org_id:
        return org_id
    uid = str(ident.get('user_id') or '')
    if not uid:
        return ''
    try:
        from backend.cloud.platform_service import service_select
        from urllib.parse import quote
        rows = service_select(
            'businesses',
            f'owner_user_id=eq.{quote(uid, safe="")}&select=id,org_id&limit=1',
        ) or []
        if rows and rows[0].get('org_id'):
            return str(rows[0]['org_id'])
    except Exception as e:
        logger.info('org lookup via businesses failed: %s', e)
    try:
        from backend.cloud.platform_service import ensure_org_for_business
        org = ensure_org_for_business(
            {'id': ident.get('business_id'),
             'name': ident.get('business_name') or 'My Business'},
            uid,
        )
        return str((org or {}).get('id') or '')
    except Exception as e:
        logger.info('ensure_org_for_business failed: %s', e)
    return ''


def _seats_free(lic: dict) -> bool:
    try:
        return int(lic.get('activated_devices') or 0) < int(lic.get('max_devices') or 1)
    except Exception:
        return True


def _device_already_on(lic: dict, device_id: str) -> bool:
    for act in (lic.get('activations') or lic.get('license_activations') or []):
        if isinstance(act, dict) and str(act.get('device_id')) == device_id and act.get('is_active', True):
            return True
    return False


def _pick_license(licenses: list[dict], device_id: str) -> Optional[dict]:
    """Prefer: this device already activated → active/trial with a free seat → any free seat."""
    for lic in licenses:
        if str(lic.get('status') or '') not in _TERMINAL_STATUSES and _device_already_on(lic, device_id):
            return lic
    for lic in licenses:
        if str(lic.get('status') or '') in ('active', 'trial') and _seats_free(lic):
            return lic
    for lic in licenses:
        if str(lic.get('status') or '') not in _TERMINAL_STATUSES and _seats_free(lic):
            return lic
    return None


def try_login(email: str, password: str) -> dict:
    """Sign into the MugoByte account. Returns {ok, message}."""
    try:
        from backend.cloud_backup.paths import is_cloud_configured
        if not is_cloud_configured():
            return {'ok': False, 'reason': 'unconfigured',
                    'message': 'Cloud is not configured on this PC.'}
        from backend.cloud_backup.auth_service import login_existing
        r = login_existing((email or '').strip(), password or '')
        return {'ok': True, 'message': 'Signed in.',
                'business_id': r.get('business_id'),
                'has_backups': bool(r.get('has_backups'))}
    except Exception as e:
        return {'ok': False, 'reason': 'login_failed', 'message': str(e)}


def auto_claim_device_license(engine, email: str = '', password: str = '') -> dict:
    """
    Login (optional here if already signed in) → find a license seat for this
    account/device → activate it locally via the normal cloud-key path.

    Returns dict: {ok, message, reason}. reason in
    {unconfigured, needs_login, no_org, no_seat, activate_failed, ''}.
    """
    try:
        from backend.cloud_backup.paths import (
            is_cloud_configured, is_logged_in, load_identity,
        )
    except Exception as e:
        return {'ok': False, 'reason': 'unconfigured', 'message': str(e)}

    if not is_cloud_configured():
        return {'ok': False, 'reason': 'unconfigured',
                'message': 'Cloud is not configured on this PC.'}

    if email and password:
        login = try_login(email, password)
        if not login.get('ok'):
            return {'ok': False, 'reason': 'login_failed',
                    'message': login.get('message') or 'Sign in failed.'}

    ident = load_identity()
    if not (ident.get('access_token') or is_logged_in()):
        return {'ok': False, 'reason': 'needs_login',
                'message': 'Sign in to your MugoByte account first.'}

    org_id = _resolve_org_id(ident)
    if not org_id:
        return {'ok': False, 'reason': 'no_org',
                'message': 'No organization is linked to this account yet.'}

    try:
        from backend.cloud.platform_service import list_licenses_for_org
        from backend.cloud_backup.device_manager import get_or_create_device_id
        device_id = get_or_create_device_id() or engine.device_id
        licenses = list_licenses_for_org(org_id) or []
    except Exception as e:
        logger.warning('license lookup failed: %s', e)
        return {'ok': False, 'reason': 'lookup_failed', 'message': str(e)}

    chosen = _pick_license(licenses, device_id)
    if not chosen:
        return {'ok': False, 'reason': 'no_seat',
                'message': ('Signed in, but no license seat is available for this device. '
                            'Enter a license key or free a seat in the Portal.'),
                'license_count': len(licenses)}

    try:
        ok, msg = engine.activate_with_key(str(chosen.get('license_key') or ''))
    except Exception as e:
        return {'ok': False, 'reason': 'activate_failed', 'message': str(e)}

    return {'ok': bool(ok), 'message': msg,
            'reason': '' if ok else 'activate_failed',
            'license_key': chosen.get('license_key')}
