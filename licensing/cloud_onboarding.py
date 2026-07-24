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


def _persist_org_id(org_id: str) -> None:
    if not org_id:
        return
    try:
        from backend.cloud_backup.paths import load_identity, save_identity
        ident = load_identity()
        if ident.get('org_id') != org_id:
            ident['org_id'] = org_id
            save_identity(ident)
    except Exception as e:
        logger.info('persist org_id failed: %s', e)


def _resolve_org_id(ident: dict) -> str:
    """Best-effort org id for the signed-in user (works on shop PCs without service-role)."""
    org_id = str(ident.get('org_id') or '')
    if org_id:
        return org_id
    uid = str(ident.get('user_id') or '')
    if not uid:
        return ''

    try:
        from backend.cloud.platform_service import list_organizations_for_user
        orgs = list_organizations_for_user(uid) or []
        if orgs:
            oid = str(orgs[0].get('id') or '')
            _persist_org_id(oid)
            return oid
    except Exception as e:
        logger.info('list_organizations_for_user failed: %s', e)

    try:
        from backend.cloud.platform_service import service_select
        from urllib.parse import quote
        rows = service_select(
            'businesses',
            f'owner_user_id=eq.{quote(uid, safe="")}&select=id,name,org_id&limit=1',
        ) or []
        if rows and rows[0].get('org_id'):
            oid = str(rows[0]['org_id'])
            _persist_org_id(oid)
            return oid
        if rows:
            from backend.cloud.platform_service import ensure_org_for_business
            org = ensure_org_for_business(rows[0], uid)
            oid = str((org or {}).get('id') or '')
            _persist_org_id(oid)
            return oid
    except Exception as e:
        logger.info('org lookup via businesses failed: %s', e)

    try:
        from backend.cloud.platform_service import ensure_org_for_business
        org = ensure_org_for_business(
            {
                'id': ident.get('business_id'),
                'name': ident.get('business_name') or 'My Business',
            },
            uid,
        )
        oid = str((org or {}).get('id') or '')
        _persist_org_id(oid)
        return oid
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


def _pick_license(licenses: list[dict], device_id: str, identity_email: str = '') -> Optional[dict]:
    """Prefer reserved email/device matches, then existing activation, then free seats."""
    email = (identity_email or '').strip().lower()
    usable = [lic for lic in licenses if str(lic.get('status') or '') not in _TERMINAL_STATUSES]

    # Exact reserved device for this machine
    for lic in usable:
        reserved = str(lic.get('reserved_device_id') or '').strip()
        if reserved and reserved == device_id and _seats_free(lic):
            assigned = str(lic.get('assigned_email') or '').strip().lower()
            if not assigned or not email or assigned == email:
                return lic

    # Reserved for this signed-in email (any free seat / matching or empty device)
    if email:
        for lic in usable:
            assigned = str(lic.get('assigned_email') or '').strip().lower()
            if assigned != email or not _seats_free(lic):
                continue
            reserved = str(lic.get('reserved_device_id') or '').strip()
            if not reserved or reserved == device_id:
                return lic

    for lic in usable:
        if _device_already_on(lic, device_id):
            return lic
    for lic in usable:
        if str(lic.get('status') or '') in ('active', 'trial') and _seats_free(lic):
            reserved = str(lic.get('reserved_device_id') or '').strip()
            assigned = str(lic.get('assigned_email') or '').strip().lower()
            # Skip keys reserved for someone/something else
            if reserved and reserved != device_id:
                continue
            if assigned and email and assigned != email:
                continue
            return lic
    for lic in usable:
        if _seats_free(lic):
            reserved = str(lic.get('reserved_device_id') or '').strip()
            assigned = str(lic.get('assigned_email') or '').strip().lower()
            if reserved and reserved != device_id:
                continue
            if assigned and email and assigned != email:
                continue
            return lic
    return None


def try_login(email: str, password: str) -> dict:
    """Sign into the MugoByte account. Returns {ok, message}."""
    try:
        from backend.cloud_backup.paths import (
            is_cloud_configured, cloud_unconfigured_message,
            ensure_production_cloud_config,
        )
        ensure_production_cloud_config(persist=True)
        if not is_cloud_configured():
            return {'ok': False, 'reason': 'unconfigured',
                    'message': cloud_unconfigured_message()}
        from backend.cloud_backup.auth_service import login_existing
        r = login_existing((email or '').strip(), password or '')
        return {'ok': True, 'message': 'Signed in.',
                'business_id': r.get('business_id'),
                'has_backups': bool(r.get('has_backups'))}
    except Exception as e:
        return {'ok': False, 'reason': 'login_failed', 'message': str(e)}


def _activate_chosen(engine, license_key: str) -> dict:
    try:
        ok, msg = engine.activate_with_key(str(license_key or ''))
    except Exception as e:
        return {'ok': False, 'reason': 'activate_failed', 'message': str(e)}
    return {
        'ok': bool(ok),
        'message': msg,
        'reason': '' if ok else 'activate_failed',
        'license_key': license_key,
    }


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
            cloud_unconfigured_message, ensure_production_cloud_config,
        )
        ensure_production_cloud_config(persist=True)
    except Exception as e:
        return {'ok': False, 'reason': 'unconfigured', 'message': str(e)}

    if not is_cloud_configured():
        return {'ok': False, 'reason': 'unconfigured',
                'message': cloud_unconfigured_message()}

    if email and password:
        login = try_login(email, password)
        if not login.get('ok'):
            return {'ok': False, 'reason': 'login_failed',
                    'message': login.get('message') or 'Sign in failed.'}

    ident = load_identity()
    if not (ident.get('access_token') or is_logged_in()):
        return {'ok': False, 'reason': 'needs_login',
                'message': 'Sign in to your MugoByte account first.'}

    from backend.cloud_backup.device_manager import get_or_create_device_id
    device_id = get_or_create_device_id() or getattr(engine, 'device_id', '') or ''
    identity_email = (ident.get('email') or email or '').strip()

    # 1) Prefer email-reserved claim via Portal (works even when the key lives
    #    under a different org than the shop's own organization).
    try:
        from backend.cloud.platform_service import (
            claim_license_for_identity,
            claim_license_via_portal,
            has_service_role,
        )
        if has_service_role():
            claimed = claim_license_for_identity(
                email=identity_email,
                device_id=device_id,
                org_id=None,
            )
        else:
            claimed = claim_license_via_portal(
                email=identity_email,
                device_id=device_id,
                org_id=None,
            )
        key = str((claimed.get('license') or {}).get('license_key') or '')
        if claimed.get('ok') and key:
            local = _activate_chosen(engine, key)
            if local.get('ok'):
                org_from_lic = str((claimed.get('license') or {}).get('org_id') or '')
                _persist_org_id(org_from_lic)
                return local
            return local
    except Exception as e:
        logger.info('email claim path skipped: %s', e)

    # 2) Resolve / auto-create the shop org, then pick a free seat there.
    org_id = _resolve_org_id(ident)
    if not org_id:
        return {
            'ok': False,
            'reason': 'no_org',
            'message': (
                'No organization is linked to this account yet. '
                'Paste an MBT-… license key below, or ask Portal admin to '
                'create/assign an organization for this email.'
            ),
        }

    try:
        from backend.cloud.platform_service import list_licenses_for_org
        licenses = list_licenses_for_org(org_id) or []
    except Exception as e:
        logger.warning('license lookup failed: %s', e)
        return {'ok': False, 'reason': 'lookup_failed', 'message': str(e)}

    chosen = _pick_license(licenses, device_id, identity_email=identity_email)
    if not chosen:
        return {
            'ok': False,
            'reason': 'no_seat',
            'message': (
                'Signed in, but no license seat is available for this device. '
                'Enter a license key or free a seat in the Portal.'
            ),
            'license_count': len(licenses),
        }

    return _activate_chosen(engine, str(chosen.get('license_key') or ''))
