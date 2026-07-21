"""
MBT Cloud Platform Service — live multi-tenant orgs, auth bridge, licenses.
Uses Supabase Auth + schema_v2 tables with service-role for server APIs.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from backend.cloud_backup.paths import is_cloud_configured, load_cloud_config, load_identity
from backend.cloud_backup.supabase_client import SupabaseClient, SupabaseError
from backend.cloud.license_server import get_license_server

logger = logging.getLogger('cloud.platform')


def _svc() -> SupabaseClient:
    return SupabaseClient()


def _service_headers(client: SupabaseClient) -> dict:
    key = client.service or client.anon
    return {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation',
    }


def service_select(table: str, query: str = '') -> list:
    client = _svc()
    if not client.configured:
        return []
    url = client._url(f'/rest/v1/{table}')
    if query:
        url = f'{url}?{query}'
    r = client._session.get(url, headers=_service_headers(client), timeout=30)
    if r.status_code >= 400:
        logger.warning('service_select %s failed: %s %s', table, r.status_code, r.text[:200])
        return []
    return r.json() if r.content else []


def service_insert(table: str, row: dict, upsert: bool = False, on_conflict: str = '') -> Any:
    client = _svc()
    prefer = 'return=representation'
    if upsert:
        prefer += ',resolution=merge-duplicates'
    h = _service_headers(client)
    h['Prefer'] = prefer
    url = client._url(f'/rest/v1/{table}')
    if upsert and on_conflict:
        url = f'{url}?on_conflict={on_conflict}'
    r = client._session.post(url, headers=h, json=row, timeout=30)
    if r.status_code >= 400:
        raise SupabaseError(f'Insert {table} failed ({r.status_code}): {r.text[:300]}', r.status_code)
    data = r.json() if r.content else None
    return data[0] if isinstance(data, list) and data else data


def service_update(table: str, query: str, patch: dict) -> Any:
    client = _svc()
    r = client._session.patch(
        client._url(f'/rest/v1/{table}?{query}'),
        headers=_service_headers(client),
        json=patch,
        timeout=30,
    )
    if r.status_code >= 400:
        raise SupabaseError(f'Update {table} failed ({r.status_code}): {r.text[:300]}', r.status_code)
    return r.json() if r.content else None


def service_rpc(function_name: str, payload: dict) -> Any:
    client = _svc()
    if not client.configured or not client.service:
        raise SupabaseError('Cloud service role is not configured', 503)
    r = client._session.post(
        client._url(f'/rest/v1/rpc/{function_name}'),
        headers=_service_headers(client),
        json=payload,
        timeout=60,
    )
    if r.status_code >= 400:
        raise SupabaseError(
            f'RPC {function_name} failed ({r.status_code}): {r.text[:300]}',
            r.status_code,
        )
    return r.json() if r.content else None


def ingest_sync_batch(
    org_id: str,
    device_identifier: str,
    idempotency_key: str,
    entities: list[dict],
) -> dict:
    devices = service_select(
        'devices',
        f'device_id=eq.{quote(str(device_identifier), safe="")}'
        f'&org_id=eq.{quote(str(org_id), safe="")}'
        '&is_active=eq.true&approval_status=eq.approved&select=id&limit=1',
    )
    if not devices:
        raise PermissionError('Device is not approved for this organization')
    device_id = devices[0]['id']
    result = service_rpc('ingest_sync_batch', {
        'p_org_id': org_id,
        'p_device_id': device_id,
        'p_idempotency_key': idempotency_key,
        'p_entities': entities,
    })
    return result if isinstance(result, dict) else {'ok': True, 'result': result}


def get_org_membership(user_id: str, org_id: str) -> dict | None:
    """Return active membership/ownership for a cloud user and organization."""
    if not user_id or not org_id:
        return None
    uid = quote(str(user_id), safe='')
    oid = quote(str(org_id), safe='')
    owners = service_select(
        'organizations',
        f'id=eq.{oid}&owner_user_id=eq.{uid}&select=id&limit=1',
    )
    if owners:
        return {'org_id': str(org_id), 'user_id': str(user_id), 'role': 'owner'}
    members = service_select(
        'org_members',
        f'org_id=eq.{oid}&user_id=eq.{uid}&is_active=eq.true'
        '&select=org_id,user_id,role&limit=1',
    )
    return members[0] if members else None


def require_org_access(user_id: str, org_id: str, *, admin: bool = False) -> dict:
    """Authorize a service-role operation before it bypasses Supabase RLS."""
    membership = get_org_membership(user_id, org_id)
    if not membership:
        raise PermissionError('Organization access denied')
    role = str(membership.get('role') or '').lower()
    if admin and role not in {'owner', 'superadmin', 'admin', 'manager'}:
        raise PermissionError('Organization administrator access required')
    return membership


def license_org_id(license_id: str) -> str:
    rows = service_select(
        'licenses',
        f'id=eq.{quote(str(license_id), safe="")}&select=org_id&limit=1',
    )
    return str(rows[0].get('org_id') or '') if rows else ''


def license_key_org_id(license_key: str) -> str:
    rows = service_select(
        'licenses',
        f'license_key=eq.{quote(str(license_key), safe="")}&select=org_id&limit=1',
    )
    return str(rows[0].get('org_id') or '') if rows else ''


def cloud_public_config() -> dict:
    cfg = load_cloud_config()
    return {
        'configured': is_cloud_configured(),
        'enabled': bool(cfg.get('enabled')),
        'supabase_url': cfg.get('supabase_url') or '',
        'anon_key': cfg.get('anon_key') or '',
        'project_ref': cfg.get('project_ref') or '',
        'bucket': cfg.get('bucket') or 'mbt-backups',
    }


def slugify(name: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', (name or 'org').lower()).strip('-')
    return s[:48] or 'org'


def ensure_org_for_business(business: dict, owner_user_id: str) -> dict:
    """Create or link an organization for an existing businesses row."""
    biz_id = business.get('id')
    name = business.get('name') or 'My Business'
    existing = service_select('organizations', f'owner_user_id=eq.{quote(owner_user_id, safe="")}&select=*&limit=1')
    if existing:
        org = existing[0]
        if biz_id and not business.get('org_id'):
            try:
                service_update('businesses', f'id=eq.{biz_id}', {'org_id': org['id']})
            except Exception:
                pass
        return org

    org = service_insert('organizations', {
        'name': name,
        'slug': slugify(name),
        'owner_user_id': owner_user_id,
        'plan': 'unlicensed',
        'status': 'active',
    })
    try:
        service_insert('org_members', {
            'org_id': org['id'],
            'user_id': owner_user_id,
            'role': 'owner',
            'is_active': True,
            'joined_at': datetime.now(timezone.utc).isoformat(),
        }, upsert=True, on_conflict='org_id,user_id')
    except Exception as e:
        logger.warning('org_members seed: %s', e)
    try:
        service_insert('branches', {
            'org_id': org['id'],
            'name': 'Main Branch',
            'is_primary': True,
            'is_active': True,
        })
    except Exception as e:
        logger.warning('branch seed: %s', e)
    if biz_id:
        try:
            service_update('businesses', f'id=eq.{biz_id}', {'org_id': org['id']})
        except Exception:
            pass
    return org


def list_organizations_for_user(user_id: str | None = None, email: str | None = None) -> list[dict]:
    """Live orgs for a user. Falls back to identity business → org."""
    if not is_cloud_configured():
        return []

    orgs: list[dict] = []
    if user_id:
        owned = service_select('organizations', f'owner_user_id=eq.{quote(user_id, safe="")}&select=*')
        member_rows = service_select(
            'org_members',
            f'user_id=eq.{quote(user_id, safe="")}&is_active=eq.true&select=*,organizations(*)',
        )
        seen = set()
        for o in owned or []:
            seen.add(o['id'])
            orgs.append({
                'id': o['id'],
                'name': o['name'],
                'slug': o.get('slug') or slugify(o['name']),
                'role': 'owner',
                'is_primary': True,
                'plan': o.get('plan'),
                'status': o.get('status'),
            })
        for m in member_rows or []:
            o = m.get('organizations') or {}
            oid = o.get('id') or m.get('org_id')
            if not oid or oid in seen:
                continue
            seen.add(oid)
            orgs.append({
                'id': oid,
                'name': o.get('name') or 'Organization',
                'slug': o.get('slug') or slugify(o.get('name') or 'org'),
                'role': m.get('role') or 'member',
                'is_primary': False,
                'plan': o.get('plan'),
                'status': o.get('status'),
            })

    if orgs:
        return orgs

    # Bootstrap from identity / businesses
    ident = load_identity()
    uid = user_id or ident.get('user_id') or ''
    if uid:
        biz = service_select('businesses', f'owner_user_id=eq.{quote(uid, safe="")}&select=*&limit=1')
        if biz:
            org = ensure_org_for_business(biz[0], uid)
            return [{
                'id': org['id'],
                'name': org['name'],
                'slug': org.get('slug') or slugify(org['name']),
                'role': 'owner',
                'is_primary': True,
                'plan': org.get('plan'),
                'status': org.get('status'),
            }]

    # Last resort: all orgs (admin view) if none for user — return empty
    return []


def cloud_sign_in(email: str, password: str) -> dict:
    client = _svc()
    session = client.sign_in(email, password, persist=False)
    user = session.get('user') or {}
    user_id = user.get('id') or ''
    if not user_id:
        raise SupabaseError('No user id from login')

    # Ensure org exists
    biz_rows = service_select('businesses', f'owner_user_id=eq.{quote(user_id, safe="")}&select=*&limit=1')
    if biz_rows:
        ensure_org_for_business(biz_rows[0], user_id)
    else:
        # Create business + org for brand-new cloud-only users
        biz = service_insert('businesses', {
            'name': (user.get('user_metadata') or {}).get('business_name') or 'My Business',
            'owner_user_id': user_id,
        })
        ensure_org_for_business(biz if isinstance(biz, dict) else biz[0], user_id)

    orgs = list_organizations_for_user(user_id)
    return {
        'token': session.get('access_token'),
        'refresh_token': session.get('refresh_token'),
        'provider': 'supabase',
        'user': {
            'id': user_id,
            'username': (email or '').split('@')[0],
            'full_name': (user.get('user_metadata') or {}).get('full_name') or (email or '').split('@')[0],
            'email': email,
            'role': (user.get('app_metadata') or {}).get('platform_role') or 'member',
            'tab_permissions': [],
        },
        'organizations': orgs,
    }


def _auth_redirect() -> str:
    return 'https://portal.mugobyte.com/auth/callback'


def _send_supabase_confirm_email(
    email: str,
    *,
    link_type: str = 'signup',
    password: str = '',
    metadata: dict | None = None,
) -> bool:
    """Generate a GoTrue action link and deliver it via Resend (reliable path)."""
    try:
        client = _svc()
        redirect = (
            'https://portal.mugobyte.com/reset-password'
            if link_type == 'recovery'
            else _auth_redirect()
        )
        data = client.generate_auth_link(
            email=email,
            link_type=link_type,
            redirect_to=redirect,
            password=password,
            metadata=metadata,
        )
        action = (
            data.get('action_link')
            or (data.get('properties') or {}).get('action_link')
            or ''
        )
        if not action:
            logger.warning('generate_link returned no action_link for %s', email)
            return False
        from backend.cloud.email_service import send_confirm_link_email
        if link_type == 'recovery':
            return bool(send_confirm_link_email(
                email, action,
                subject='Reset your MugoByte Platform password',
                title='Reset your password',
            ))
        return bool(send_confirm_link_email(email, action))
    except Exception as e:
        logger.warning('confirm email via Resend failed for %s: %s', email, e)
        return False


def cloud_sign_up(email: str, password: str, full_name: str = '', business_name: str = '') -> dict:
    """Create an unconfirmed Supabase user and require email verification."""
    client = _svc()
    email = (email or '').strip().lower()
    business_name = (business_name or '').strip() or 'My Business'
    meta = {
        'full_name': full_name or email.split('@')[0],
        'business_name': business_name,
    }
    session = client.sign_up(
        email,
        password,
        metadata=meta,
        redirect_to=_auth_redirect(),
    )
    if session.get('access_token'):
        raise SupabaseError(
            'Email confirmation is disabled in Supabase; production requires it.',
            503,
        )
    # Always deliver confirmation ourselves via Resend so signup does not depend
    # solely on Supabase SMTP template delivery (often silent / delayed).
    sent = _send_supabase_confirm_email(
        email, link_type='signup', password=password, metadata=meta,
    )
    if not sent:
        # Existing unconfirmed users: magiclink / signup regenerate
        sent = _send_supabase_confirm_email(email, link_type='magiclink')
    return {
        'ok': True,
        'verification_required': True,
        'email': email,
        'email_sent': bool(sent),
        'message': (
            'Check your email to verify the account, then sign in.'
            if sent else
            'Account created. If you do not see a verification email, use Resend on the verify page.'
        ),
    }


def cloud_forgot_password(email: str) -> bool:
    """Trigger password recovery — prefer Resend action link, fall back to Auth mailer."""
    email = (email or '').strip().lower()
    if _send_supabase_confirm_email(email, link_type='recovery'):
        return True
    client = _svc()
    redirect = 'https://portal.mugobyte.com/reset-password'
    r = client._session.post(
        client._url('/auth/v1/recover'),
        headers=client._headers(),
        json={'email': email, 'redirect_to': redirect},
        timeout=30,
    )
    return r.status_code < 400


def cloud_resend_verification(email: str) -> bool:
    """Resend confirmation via Resend action link (primary) + Auth /resend fallback."""
    email = (email or '').strip().lower()
    # Existing accounts cannot use type=signup generate_link — magiclink works for
    # both unconfirmed and confirmed users and still lands on /auth/callback.
    if _send_supabase_confirm_email(email, link_type='magiclink'):
        return True
    if _send_supabase_confirm_email(email, link_type='signup'):
        return True
    client = _svc()
    redirect = _auth_redirect()
    r = client._session.post(
        client._url('/auth/v1/resend'),
        headers=client._headers(),
        json={
            'type': 'signup',
            'email': email,
            'options': {'email_redirect_to': redirect},
        },
        timeout=30,
    )
    if r.status_code >= 400:
        r2 = client._session.post(
            client._url('/auth/v1/resend'),
            headers=client._headers(),
            json={'type': 'signup', 'email': email},
            timeout=30,
        )
        return r2.status_code < 400
    return True


def cloud_refresh_session(refresh_token: str) -> dict:
    client = _svc()
    r = client._session.post(
        client._url('/auth/v1/token?grant_type=refresh_token'),
        headers=client._headers(),
        json={'refresh_token': refresh_token},
        timeout=30,
    )
    if r.status_code >= 400:
        raise SupabaseError('Session refresh failed', r.status_code)
    return r.json()


def cloud_update_password(access_token: str, new_password: str) -> bool:
    client = _svc()
    r = client._session.put(
        client._url('/auth/v1/user'),
        headers=client._headers(token=access_token),
        json={'password': new_password},
        timeout=30,
    )
    if r.status_code >= 400:
        raise SupabaseError('Password update failed', r.status_code)
    return True


def list_licenses_for_org(org_id: str) -> list[dict]:
    return service_select('licenses', f'org_id=eq.{quote(org_id, safe="")}&select=*&order=created_at.desc') or []


def list_devices_for_org(org_id: str) -> list[dict]:
    # Prefer org_id column; also include business-linked devices
    devices = service_select('devices', f'org_id=eq.{quote(org_id, safe="")}&select=*&order=last_seen_at.desc') or []
    if devices:
        return devices
    # Fallback: via businesses.org_id
    biz = service_select('businesses', f'org_id=eq.{quote(org_id, safe="")}&select=id') or []
    out = []
    for b in biz:
        out.extend(service_select('devices', f'business_id=eq.{b["id"]}&select=*&order=last_seen_at.desc') or [])
    return out


def _log_device_event(
    org_id: str,
    device_row_id: str | None,
    event_type: str,
    actor_user_id: str | None = None,
    details: dict | None = None,
) -> None:
    try:
        service_insert('device_events', {
            'org_id': org_id,
            'device_id': device_row_id,
            'event_type': event_type,
            'actor_user_id': actor_user_id,
            'details': details or {},
        })
    except Exception as e:
        logger.debug('device_events insert skipped: %s', e)


def _find_org_device(org_id: str, device_identifier: str) -> dict | None:
    rows = service_select(
        'devices',
        f'org_id=eq.{quote(str(org_id), safe="")}'
        f'&device_id=eq.{quote(str(device_identifier), safe="")}'
        '&select=*&limit=1',
    )
    if rows:
        return rows[0]
    # Also allow lookup by UUID primary key
    rows = service_select(
        'devices',
        f'org_id=eq.{quote(str(org_id), safe="")}'
        f'&id=eq.{quote(str(device_identifier), safe="")}'
        '&select=*&limit=1',
    )
    return rows[0] if rows else None


def register_or_refresh_device(
    org_id: str,
    *,
    device_id: str,
    business_id: str | None = None,
    computer_name: str = '',
    hostname: str = '',
    platform_str: str = '',
    mbt_version: str = '',
    os_info: str = '',
    hardware_fingerprint: str = '',
    branch: str = '',
    actor_user_id: str | None = None,
) -> dict:
    """Register a desktop installation. New devices start pending approval."""
    if not org_id or not device_id:
        raise SupabaseError('org_id and device_id are required', 400)
    now = datetime.now(timezone.utc).isoformat()
    existing = _find_org_device(org_id, device_id)
    name = computer_name or hostname or ''
    patch = {
        'org_id': org_id,
        'hostname': hostname or name,
        'computer_name': name,
        'platform': platform_str,
        'mbt_version': mbt_version,
        'os_info': os_info,
        'hardware_fingerprint': hardware_fingerprint or device_id,
        'last_seen_at': now,
        'is_active': True,
        'updated_at': now,
    }
    if business_id:
        patch['business_id'] = business_id
    if branch:
        patch['sync_status'] = patch.get('sync_status') or 'idle'
    if existing:
        # Preserve approval_status for returning devices (never auto-approve again).
        service_update('devices', f'id=eq.{existing["id"]}', patch)
        row = {**existing, **patch}
        _log_device_event(org_id, existing['id'], 'heartbeat', actor_user_id, {
            'device_id': device_id,
            'computer_name': name,
            'mbt_version': mbt_version,
        })
        return row

    row = {
        **patch,
        'device_id': device_id,
        'approval_status': 'pending',
        'is_active': True,
    }
    inserted = service_insert('devices', row, upsert=True, on_conflict='business_id,device_id')
    if isinstance(inserted, list):
        inserted = inserted[0] if inserted else row
    if not isinstance(inserted, dict):
        inserted = row
    _log_device_event(org_id, inserted.get('id'), 'registered', actor_user_id, {
        'device_id': device_id,
        'computer_name': name,
        'approval_status': 'pending',
    })
    try:
        from backend.cloud.notification_engine import get_notification_engine
        get_notification_engine().publish(
            'new_device',
            f'Device pending approval — {name or device_id}',
            f'{os_info or platform_str} · v{mbt_version or "unknown"}',
            'warning',
            meta={'device_id': device_id, 'org_id': org_id},
        )
    except Exception:
        pass
    return inserted


def set_device_approval(
    org_id: str,
    device_identifier: str,
    *,
    approve: bool,
    actor_user_id: str | None = None,
    reason: str = '',
) -> dict:
    device = _find_org_device(org_id, device_identifier)
    if not device:
        raise SupabaseError('Device not found', 404)
    now = datetime.now(timezone.utc).isoformat()
    if approve:
        patch = {
            'approval_status': 'approved',
            'approved_at': now,
            'approved_by': actor_user_id,
            'rejected_at': None,
            'is_active': True,
            'deactivated_at': None,
            'updated_at': now,
        }
        event = 'approved'
    else:
        patch = {
            'approval_status': 'rejected',
            'rejected_at': now,
            'is_active': False,
            'deactivated_at': now,
            'updated_at': now,
        }
        event = 'rejected'
    service_update('devices', f'id=eq.{device["id"]}', patch)
    _log_device_event(org_id, device['id'], event, actor_user_id, {
        'device_id': device.get('device_id'),
        'reason': reason or '',
    })
    return {**device, **patch}


def rename_device(org_id: str, device_identifier: str, computer_name: str,
                  actor_user_id: str | None = None) -> dict:
    device = _find_org_device(org_id, device_identifier)
    if not device:
        raise SupabaseError('Device not found', 404)
    name = (computer_name or '').strip()
    if not name:
        raise SupabaseError('computer_name is required', 400)
    now = datetime.now(timezone.utc).isoformat()
    patch = {
        'computer_name': name,
        'hostname': name,
        'updated_at': now,
    }
    service_update('devices', f'id=eq.{device["id"]}', patch)
    _log_device_event(org_id, device['id'], 'renamed', actor_user_id, {
        'device_id': device.get('device_id'),
        'computer_name': name,
    })
    return {**device, **patch}


def deactivate_device(org_id: str, device_identifier: str,
                      actor_user_id: str | None = None, reason: str = '') -> dict:
    device = _find_org_device(org_id, device_identifier)
    if not device:
        raise SupabaseError('Device not found', 404)
    now = datetime.now(timezone.utc).isoformat()
    patch = {
        'is_active': False,
        'deactivated_at': now,
        'approval_status': 'deactivated',
        'updated_at': now,
    }
    service_update('devices', f'id=eq.{device["id"]}', patch)
    _log_device_event(org_id, device['id'], 'deactivated', actor_user_id, {
        'device_id': device.get('device_id'),
        'reason': reason or '',
    })
    return {**device, **patch}


def list_device_events(org_id: str, limit: int = 50) -> list[dict]:
    lim = max(1, min(int(limit or 50), 200))
    return service_select(
        'device_events',
        f'org_id=eq.{quote(str(org_id), safe="")}'
        f'&select=*&order=created_at.desc&limit={lim}',
    ) or []


def activate_license_on_device(license_key: str, device_id: str, org_id: str | None = None) -> dict:
    """Activate a cloud license key onto a device; also update local license engine when possible."""
    rows = service_select('licenses', f'license_key=eq.{quote(license_key, safe="")}&select=*')
    if not rows:
        raise SupabaseError('License key not found', 404)
    lic = rows[0]
    if lic.get('status') in ('revoked', 'suspended'):
        raise SupabaseError(f'License is {lic["status"]}', 403)
    license_org = str(lic.get('org_id') or '')
    if org_id and str(org_id) != license_org:
        raise PermissionError('License does not belong to the selected organization')
    oid = license_org
    ok, msg, data = get_license_server().activate(license_key, device_id, oid)
    if not ok:
        # Try service-role activation path directly
        if lic.get('activated_devices', 0) >= lic.get('max_devices', 1):
            raise SupabaseError(f'Device limit reached ({lic["max_devices"]})', 403)
        service_insert('license_activations', {
            'license_id': lic['id'],
            'device_id': device_id,
            'org_id': oid,
            'is_active': True,
            'last_validated_at': datetime.now(timezone.utc).isoformat(),
        }, upsert=True, on_conflict='license_id,device_id')
        service_update('licenses', f'id=eq.{lic["id"]}', {
            'activated_devices': int(lic.get('activated_devices') or 0) + 1,
            'activated_at': datetime.now(timezone.utc).isoformat(),
            'status': 'active',
        })
        data = {'plan': lic['plan'], 'expires_at': lic.get('expires_at')}
        msg = 'Activated'
    return {'ok': True, 'message': msg, 'license': lic, 'activation': data}


def push_license_command(license_id: str, command: str, params: dict | None = None,
                         issued_by: str | None = None) -> dict:
    """Update cloud license state (if needed) is caller's job; this pushes to devices."""
    from backend.cloud.command_center import get_command_center
    rows = service_select('licenses', f'id=eq.{quote(license_id, safe="")}&select=*')
    if not rows:
        raise SupabaseError('License not found', 404)
    lic = rows[0]
    org_id = lic.get('org_id') or ''
    center = get_command_center()
    issued = center.issue_to_license_devices(
        org_id, license_id, command, params or {}, issued_by,
    )
    return {'ok': True, 'license': lic, 'commands_issued': len([x for x in issued if x])}


def admin_revoke_license(license_id: str, actor: str | None = None) -> dict:
    get_license_server().revoke(license_id, actor)
    return push_license_command(license_id, 'revoke_license', {'reason': 'Admin revoked'}, actor)


def admin_suspend_license(license_id: str, actor: str | None = None) -> dict:
    get_license_server().suspend(license_id, actor)
    return push_license_command(license_id, 'suspend_license', {'reason': 'Admin suspended'}, actor)


def admin_renew_license(license_id: str, days: int = 30, actor: str | None = None) -> dict:
    ok = get_license_server().renew(license_id, days=days, actor=actor)
    if not ok:
        raise SupabaseError('Renew failed', 400)
    rows = service_select('licenses', f'id=eq.{quote(license_id, safe="")}&select=*')
    lic = rows[0] if rows else {}
    return push_license_command(
        license_id,
        'extend_license',
        {'days': days, 'expires_at': lic.get('expires_at'), 'reason': f'Renewed +{days}d'},
        actor,
    )


def admin_force_validate(license_id: str, actor: str | None = None) -> dict:
    rows = service_select('licenses', f'id=eq.{quote(license_id, safe="")}&select=*')
    if not rows:
        raise SupabaseError('License not found', 404)
    lic = rows[0]
    return push_license_command(
        license_id,
        'force_validate',
        {'license_key': lic.get('license_key')},
        actor,
    )


def admin_transfer_license(license_id: str, old_device_id: str, new_device_id: str,
                           actor: str | None = None) -> dict:
    ok, msg = get_license_server().transfer_device(license_id, old_device_id, new_device_id, actor)
    if not ok:
        raise SupabaseError(msg, 400)
    # Revoke on old device; force validate / activate on new when it comes online
    rows = service_select('licenses', f'id=eq.{quote(license_id, safe="")}&select=*')
    lic = rows[0] if rows else {}
    org_id = lic.get('org_id') or ''
    from backend.cloud.command_center import get_command_center
    center = get_command_center()
    center.issue_command(org_id, old_device_id, 'revoke_license', {
        'reason': f'Transferred to {new_device_id}',
    }, actor)
    center.issue_command(org_id, new_device_id, 'force_validate', {
        'license_key': lic.get('license_key'),
        'device_id': new_device_id,
    }, actor)
    return {'ok': True, 'message': msg, 'license': lic}


def list_license_history(license_id: str) -> list[dict]:
    return get_license_server().get_history(license_id) or []


def publish_security_event(org_id: str | None, title: str, body: str, meta: dict | None = None):
    """Push security/audit event to notifications + audit_logs."""
    try:
        from backend.cloud.notification_engine import get_notification_engine
        get_notification_engine().publish('security', title, body, 'warning', meta=meta or {})
    except Exception as e:
        logger.debug('security notify: %s', e)
    try:
        import json as _json
        row = {
            'action': 'SECURITY',
            'module': 'security',
            'details': f'{title} — {body}',
            'status': 'warning',
            'meta': meta or {'title': title, 'body': body},
        }
        if org_id:
            row['org_id'] = org_id
        service_insert('audit_logs', row)
    except Exception as e:
        logger.debug('security audit: %s', e)
