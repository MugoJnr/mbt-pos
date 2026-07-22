"""
MBT Cloud Platform Service — live multi-tenant orgs, auth bridge, licenses.
Uses Supabase Auth + schema_v2 tables with service-role for server APIs.
"""
from __future__ import annotations

import csv
import io
import logging
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from backend.cloud_backup.paths import is_cloud_configured, load_cloud_config, load_identity
from backend.cloud_backup.supabase_client import SupabaseClient, SupabaseError
from backend.cloud.license_server import get_license_server

logger = logging.getLogger('cloud.platform')

try:
    NAIROBI_TZ = ZoneInfo('Africa/Nairobi')
except Exception:
    # Windows installs may lack the tzdata package; Nairobi is permanently UTC+3.
    NAIROBI_TZ = timezone(timedelta(hours=3), name='Africa/Nairobi')
ANALYTICS_FULL_ROLES = frozenset({'owner', 'admin', 'superadmin', 'platform_admin'})
ANALYTICS_ALLOWED_ROLES = frozenset({*ANALYTICS_FULL_ROLES, 'manager'})
ANALYTICS_EXPORT_MAX = 10_000
ANALYTICS_FETCH_PAGE = 1000
_CREDIT_METHODS = frozenset({'credit sale', 'credit', 'part payment'})
_VOID_STATUSES = frozenset({'void', 'voided'})
_SENSITIVE_DEBT_KEYS = frozenset({
    'national_id', 'id_number', 'payment_reference', 'mpesa_ref', 'mpesa_reference',
})
_COST_KEYS = frozenset({
    'cost_price', 'unit_cost', 'cost', 'cost_of_goods', 'cogs', 'sold_cost',
    'gross_profit', 'profit', 'gross_margin_pct', 'margin_pct', 'inventory_value',
    'inventory_cost_value',
})


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


def service_select_strict(table: str, query: str = '', *, prefer: str = '') -> list:
    """Service-role select that raises on HTTP/config failures (never silent empty)."""
    client = _svc()
    if not client.configured:
        raise SupabaseError('Cloud is not configured', 503)
    url = client._url(f'/rest/v1/{table}')
    if query:
        url = f'{url}?{query}'
    headers = _service_headers(client)
    if prefer:
        headers['Prefer'] = prefer
    r = client._session.get(url, headers=headers, timeout=60)
    if r.status_code >= 400:
        raise SupabaseError(
            f'select {table} failed ({r.status_code}): {r.text[:300]}',
            r.status_code,
        )
    return r.json() if r.content else []


def service_select_page(
    table: str,
    query: str,
    *,
    limit: int,
    offset: int,
) -> tuple[list, int]:
    """Paginated select with Prefer: count=exact. Returns (rows, total_count)."""
    client = _svc()
    if not client.configured:
        raise SupabaseError('Cloud is not configured', 503)
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    base = query.strip('&')
    page_q = f'{base}&limit={limit}&offset={offset}' if base else f'limit={limit}&offset={offset}'
    url = client._url(f'/rest/v1/{table}?{page_q}')
    headers = _service_headers(client)
    headers['Prefer'] = 'count=exact'
    headers['Range-Unit'] = 'items'
    headers['Range'] = f'{offset}-{offset + limit - 1}'
    r = client._session.get(url, headers=headers, timeout=60)
    if r.status_code >= 400:
        raise SupabaseError(
            f'select {table} failed ({r.status_code}): {r.text[:300]}',
            r.status_code,
        )
    rows = r.json() if r.content else []
    total = len(rows)
    content_range = r.headers.get('Content-Range') or r.headers.get('content-range') or ''
    if '/' in content_range:
        tail = content_range.rsplit('/', 1)[-1].strip()
        if tail.isdigit():
            total = int(tail)
    return rows if isinstance(rows, list) else [], total


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


def require_org_access(user_id: str, org_id: str, *, admin: bool = False,
                       platform_role: str = '') -> dict:
    """Authorize a service-role operation before it bypasses Supabase RLS."""
    # Platform operators can manage any organization.
    if str(platform_role or '').lower() == 'platform_admin':
        return {'org_id': str(org_id), 'user_id': str(user_id), 'role': 'platform_admin'}
    membership = get_org_membership(user_id, org_id)
    if not membership:
        raise PermissionError('Organization access denied')
    role = str(membership.get('role') or '').lower()
    if admin and role not in {'owner', 'superadmin', 'admin', 'manager', 'platform_admin'}:
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

    # Prefer an org already linked on the business row.
    linked_org_id = business.get('org_id')
    if linked_org_id:
        linked = service_select(
            'organizations',
            f'id=eq.{quote(str(linked_org_id), safe="")}&select=*&limit=1',
        )
        if linked:
            return linked[0]

    existing = service_select(
        'organizations',
        f'owner_user_id=eq.{quote(owner_user_id, safe="")}&select=*&limit=1',
    )
    if existing:
        org = existing[0]
        if biz_id and not business.get('org_id'):
            try:
                service_update('businesses', f'id=eq.{biz_id}', {'org_id': org['id']})
            except Exception:
                pass
        return org

    # Slug is globally unique — include a short user suffix to avoid collisions
    # with leftover "my-business" rows from earlier signups.
    base_slug = slugify(name)
    slug = f'{base_slug}-{str(owner_user_id).replace("-", "")[:8]}'
    try:
        org = service_insert('organizations', {
            'name': name,
            'slug': slug,
            'owner_user_id': owner_user_id,
            'plan': 'unlicensed',
            'status': 'active',
        })
    except Exception as e:
        # Race / leftover: reclaim by slug or owner if insert collides.
        logger.warning('organizations insert retry: %s', e)
        by_slug = service_select('organizations', f'slug=eq.{quote(slug, safe="")}&select=*&limit=1')
        if by_slug:
            org = by_slug[0]
        else:
            owned = service_select(
                'organizations',
                f'owner_user_id=eq.{quote(owner_user_id, safe="")}&select=*&limit=1',
            )
            if owned:
                org = owned[0]
            else:
                raise

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
    return _session_payload(session, user, email)


def cloud_session_from_tokens(access_token: str, refresh_token: str = '') -> dict:
    """Establish Portal session from Auth redirect tokens (verify / magic / recovery)."""
    access_token = (access_token or '').strip()
    if not access_token:
        raise SupabaseError('Access token required', 400)
    client = _svc()
    r = client._session.get(
        client._url('/auth/v1/user'),
        headers=client._headers(token=access_token),
        timeout=30,
    )
    if r.status_code >= 400:
        raise SupabaseError('Invalid or expired session token', r.status_code)
    user = r.json() or {}
    email = (user.get('email') or '').strip().lower()
    user_id = user.get('id') or ''
    if not user_id:
        raise SupabaseError('No user id from token')
    session = {
        'access_token': access_token,
        'refresh_token': (refresh_token or '').strip(),
        'user': user,
    }
    return _session_payload(session, user, email)


def _session_payload(session: dict, user: dict, email: str) -> dict:
    user_id = user.get('id') or ''
    # Ensure org exists
    biz_rows = service_select('businesses', f'owner_user_id=eq.{quote(user_id, safe="")}&select=*&limit=1')
    if biz_rows:
        ensure_org_for_business(biz_rows[0], user_id)
    else:
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


def list_all_licenses(limit: int = 200) -> list[dict]:
    """Platform-admin listing across every organization."""
    lim = max(1, min(int(limit or 200), 500))
    return service_select(
        'licenses',
        f'select=*&order=created_at.desc&limit={lim}',
    ) or []


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


def _device_is_revoked(device: dict | None) -> bool:
    """True when an admin explicitly rejected or deactivated the device."""
    if not device:
        return False
    status = str(device.get('approval_status') or '').lower()
    return status in {'rejected', 'deactivated'}


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
    platform_role: str = '',
    verify_org_access: bool = False,
) -> dict:
    """Register a desktop installation.

    Authenticated org members auto-approve new/pending devices in one write.
    Explicitly rejected or deactivated devices stay revoked (security).
    """
    if not org_id or not device_id:
        raise SupabaseError('org_id and device_id are required', 400)
    if verify_org_access:
        if not actor_user_id:
            raise PermissionError('Authenticated user required for device registration')
        require_org_access(
            actor_user_id, org_id, platform_role=platform_role,
        )
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
        'updated_at': now,
    }
    if business_id:
        patch['business_id'] = business_id
    if branch:
        patch['sync_status'] = patch.get('sync_status') or 'idle'
    if existing:
        if _device_is_revoked(existing):
            # Heartbeat metadata only — never undo an explicit revocation.
            service_update('devices', f'id=eq.{existing["id"]}', patch)
            row = {**existing, **patch}
            _log_device_event(org_id, existing['id'], 'heartbeat', actor_user_id, {
                'device_id': device_id,
                'computer_name': name,
                'mbt_version': mbt_version,
                'approval_status': existing.get('approval_status'),
                'revoked': True,
            })
            return row

        status = str(existing.get('approval_status') or 'pending').lower()
        if status in {'', 'pending'}:
            patch['approval_status'] = 'approved'
            patch['approved_at'] = now
            patch['approved_by'] = actor_user_id
            patch['rejected_at'] = None
            patch['deactivated_at'] = None
            patch['is_active'] = True
            event = 'approved'
        else:
            # Already approved (or unknown non-revoked status): keep active.
            patch['is_active'] = True
            event = 'heartbeat'

        service_update('devices', f'id=eq.{existing["id"]}', patch)
        row = {**existing, **patch}
        _log_device_event(org_id, existing['id'], event, actor_user_id, {
            'device_id': device_id,
            'computer_name': name,
            'mbt_version': mbt_version,
            'approval_status': row.get('approval_status'),
        })
        return row

    # New device: register and approve atomically in a single upsert.
    row = {
        **patch,
        'device_id': device_id,
        'approval_status': 'approved',
        'approved_at': now,
        'approved_by': actor_user_id,
        'is_active': True,
    }
    inserted = service_insert('devices', row, upsert=True, on_conflict='business_id,device_id')
    if isinstance(inserted, list):
        inserted = inserted[0] if inserted else row
    if not isinstance(inserted, dict):
        inserted = row
    # Upsert may return a revoked row if a conflict matched an old record —
    # never overwrite an explicit revocation via the insert path either.
    if _device_is_revoked(inserted):
        _log_device_event(org_id, inserted.get('id'), 'registered', actor_user_id, {
            'device_id': device_id,
            'computer_name': name,
            'approval_status': inserted.get('approval_status'),
            'revoked': True,
        })
        return inserted
    # If upsert returned a stale pending row, force-approve in one follow-up.
    if str(inserted.get('approval_status') or '').lower() != 'approved':
        approve_patch = {
            'approval_status': 'approved',
            'approved_at': now,
            'approved_by': actor_user_id,
            'rejected_at': None,
            'deactivated_at': None,
            'is_active': True,
            'updated_at': now,
            'last_seen_at': now,
        }
        if inserted.get('id'):
            service_update('devices', f'id=eq.{inserted["id"]}', approve_patch)
            inserted = {**inserted, **approve_patch}
    _log_device_event(org_id, inserted.get('id'), 'registered', actor_user_id, {
        'device_id': device_id,
        'computer_name': name,
        'approval_status': 'approved',
        'auto_approved': True,
    })
    try:
        from backend.cloud.notification_engine import get_notification_engine
        get_notification_engine().publish(
            'new_device',
            f'Device registered — {name or device_id}',
            f'{os_info or platform_str} · v{mbt_version or "unknown"} · auto-approved',
            'info',
            meta={'device_id': device_id, 'org_id': org_id, 'approval_status': 'approved'},
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
                         issued_by: str | None = None, *, include_inactive: bool = False) -> dict:
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
        include_inactive=include_inactive,
    )
    return {'ok': True, 'license': lic, 'commands_issued': len([x for x in issued if x])}


def admin_suspend_license(license_id: str, actor: str | None = None) -> dict:
    # Push to currently active devices BEFORE clearing activations.
    pushed = push_license_command(license_id, 'suspend_license', {'reason': 'Admin suspended'}, actor)
    get_license_server().suspend(license_id, actor)
    try:
        push_license_command(
            license_id,
            'force_validate',
            {
                'license_key': (pushed.get('license') or {}).get('license_key'),
                'reason': 'Post-suspend validation',
            },
            actor,
            include_inactive=True,
        )
    except Exception:
        pass
    rows = service_select('licenses', f'id=eq.{quote(license_id, safe="")}&select=*')
    pushed['license'] = rows[0] if rows else pushed.get('license')
    return pushed


def admin_unsuspend_license(license_id: str, actor: str | None = None) -> dict:
    ok = get_license_server().unsuspend(license_id, actor)
    if not ok:
        raise SupabaseError('License is not suspended', 400)
    rows = service_select('licenses', f'id=eq.{quote(license_id, safe="")}&select=*')
    lic = rows[0] if rows else {}
    # Re-enable prior activations so devices can validate again after unsuspend.
    try:
        service_update('license_activations', f'license_id=eq.{quote(license_id, safe="")}', {'is_active': True})
    except Exception:
        pass
    return push_license_command(
        license_id,
        'force_validate',
        {'license_key': lic.get('license_key'), 'reason': 'Admin unsuspended'},
        actor,
        include_inactive=True,
    )


def admin_revoke_license(license_id: str, actor: str | None = None) -> dict:
    pushed = push_license_command(license_id, 'revoke_license', {'reason': 'Admin revoked'}, actor)
    get_license_server().revoke(license_id, actor)
    return pushed


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


# ── Cloud analytics (typed projection tables from schema_v4_analytics) ─────────

def analytics_require_role(membership: dict) -> tuple[str, bool]:
    """Return (role, can_see_finance). Raises PermissionError when role is not allowed."""
    role = str((membership or {}).get('role') or '').lower()
    if role not in ANALYTICS_ALLOWED_ROLES:
        raise PermissionError('Analytics access requires owner, admin, or manager role')
    return role, role in ANALYTICS_FULL_ROLES


def analytics_day_bounds(start: str, end: str = '') -> tuple[str, str, str, str]:
    """Inclusive Nairobi calendar days → UTC ISO half-open [start, end_exclusive)."""
    start_s = (start or '').strip()[:10]
    end_s = (end or start_s or '').strip()[:10]
    if not start_s:
        start_s = datetime.now(NAIROBI_TZ).date().isoformat()
    if not end_s:
        end_s = start_s
    try:
        start_d = date.fromisoformat(start_s)
        end_d = date.fromisoformat(end_s)
    except ValueError as exc:
        raise ValueError('start/end must be YYYY-MM-DD dates') from exc
    if end_d < start_d:
        start_d, end_d = end_d, start_d
        start_s, end_s = end_s, start_s
    start_local = datetime(start_d.year, start_d.month, start_d.day, tzinfo=NAIROBI_TZ)
    end_exclusive_local = datetime(
        end_d.year, end_d.month, end_d.day, tzinfo=NAIROBI_TZ,
    ) + timedelta(days=1)
    start_iso = start_local.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    end_iso = end_exclusive_local.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    return start_s, end_s, start_iso, end_iso


def analytics_parse_page(args: dict, *, default_size: int = 25) -> tuple[int, int]:
    try:
        page = max(1, int(args.get('page') or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(args.get('page_size') or default_size)
    except (TypeError, ValueError):
        page_size = default_size
    page_size = max(1, min(page_size, 100))
    return page, page_size


def analytics_sort_clause(
    sort: str,
    order: str,
    *,
    allowed: set[str],
    default: str = 'source_created_at',
) -> str:
    col = (sort or default).strip()
    if col not in allowed:
        col = default
    direction = 'desc' if str(order or 'desc').lower() in ('desc', 'descending', '-1') else 'asc'
    # Tie-breaker keeps pagination deterministic across equal sort values.
    if col == 'source_id':
        return f'order={col}.{direction},source_created_at.{direction}'
    return f'order={col}.{direction},source_id.asc,device_id.asc'


def _fnum(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def analytics_is_void(sale: dict) -> bool:
    return str(sale.get('status') or '').lower() in _VOID_STATUSES


def analytics_is_unpaid_credit(sale: dict) -> bool:
    method = str(sale.get('payment_method') or '').strip().lower()
    if method not in _CREDIT_METHODS:
        return False
    if method == 'part payment':
        return _fnum(sale.get('amount_paid')) < 0.01
    return _fnum(sale.get('amount_paid')) < 0.01


def analytics_sale_collected_amount(sale: dict) -> float:
    """Tender received on a sale (excludes unpaid credit totals)."""
    if analytics_is_void(sale):
        return 0.0
    method = str(sale.get('payment_method') or '').strip().lower()
    paid = _fnum(sale.get('amount_paid'))
    change = _fnum(sale.get('change_amount'))
    if method in ('credit sale', 'credit') and paid < 0.01:
        return 0.0
    if method == 'part payment' and paid < 0.01:
        return 0.0
    return max(0.0, round(paid - change, 2))


def analytics_strip_sensitive(row: dict | None) -> dict:
    if not isinstance(row, dict):
        return {}
    return {k: v for k, v in row.items() if k not in _SENSITIVE_DEBT_KEYS}



def analytics_normalize_row(row: dict | None) -> dict:
    """Strip secrets and alias source_* timestamps for portal UI/export."""
    out = analytics_strip_sensitive(row)
    if out.get("source_created_at") and not out.get("created_at"):
        out["created_at"] = out["source_created_at"]
    if out.get("source_updated_at") and not out.get("updated_at"):
        out["updated_at"] = out["source_updated_at"]
    return out


def analytics_redact_row(row: dict | None, *, can_see_finance: bool, manager: bool = False) -> dict:
    out = analytics_strip_sensitive(row)
    if not can_see_finance:
        out = {k: v for k, v in out.items() if k not in _COST_KEYS}
        # Managers keep operational debt fields but not customer phone.
        if manager and 'customer_phone' in out:
            out['customer_phone'] = None
        if manager and 'phone' in out and 'customer_name' in out:
            out['phone'] = None
    return out


def analytics_redact_payload(payload: Any, *, can_see_finance: bool, role: str = '') -> Any:
    manager = str(role).lower() == 'manager'
    if isinstance(payload, list):
        return [
            analytics_redact_payload(item, can_see_finance=can_see_finance, role=role)
            for item in payload
        ]
    if not isinstance(payload, dict):
        return payload
    out = {}
    for key, value in payload.items():
        if key in _SENSITIVE_DEBT_KEYS:
            continue
        if not can_see_finance and key in _COST_KEYS:
            continue
        if isinstance(value, (dict, list)):
            out[key] = analytics_redact_payload(
                value, can_see_finance=can_see_finance, role=role,
            )
        else:
            out[key] = value
    if manager:
        if 'customer_phone' in out:
            out['customer_phone'] = None
        if 'phone' in out and ('customer_name' in out or 'name' in out):
            # Only scrub when this looks like a customer/debt party row.
            if any(k in out for k in ('invoice_number', 'balance', 'due_date', 'customer_id')):
                out['phone'] = None
    return out


def _org_eq(org_id: str) -> str:
    return f'org_id=eq.{quote(str(org_id), safe="")}'


def _ilike_or(columns: list[str], q: str) -> str:
    term = quote(f'*{q}*', safe='*')
    parts = ','.join(f'{col}.ilike.{term}' for col in columns)
    return f'or=({parts})'


def analytics_fetch_all(
    table: str,
    query: str,
    *,
    max_rows: int = ANALYTICS_EXPORT_MAX,
    page_size: int = ANALYTICS_FETCH_PAGE,
) -> list[dict]:
    """Deterministically page through matching rows up to max_rows."""
    rows: list[dict] = []
    offset = 0
    while len(rows) < max_rows:
        batch, total = service_select_page(
            table, query, limit=min(page_size, max_rows - len(rows)), offset=offset,
        )
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
        if offset >= total or len(batch) < page_size:
            break
    return rows[:max_rows]


def analytics_last_sync_at(org_id: str) -> str | None:
    rows = service_select_strict(
        'devices',
        f'{_org_eq(org_id)}&select=last_sync_at&order=last_sync_at.desc&limit=1',
    )
    if not rows:
        return None
    return rows[0].get('last_sync_at')


def _sales_base_query(
    org_id: str,
    start_iso: str,
    end_iso: str,
    *,
    status: str = '',
    payment: str = '',
    cashier: str = '',
    customer: str = '',
    q: str = '',
    sort: str = 'source_created_at',
    order: str = 'desc',
) -> str:
    parts = [
        _org_eq(org_id),
        f'source_created_at=gte.{quote(start_iso, safe=":")}',
        f'source_created_at=lt.{quote(end_iso, safe=":")}',
        'select=*',
        analytics_sort_clause(
            sort, order,
            allowed={
                'source_created_at', 'total', 'receipt_number', 'cashier_name',
                'payment_method', 'status', 'source_id', 'discount', 'tax',
            },
        ),
    ]
    if status:
        parts.append(f'status=eq.{quote(status, safe="")}')
    if payment:
        parts.append(f'payment_method=ilike.{quote(payment, safe="")}')
    if cashier:
        parts.append(f'cashier_name=ilike.{quote(f"*{cashier}*", safe="*")}')
    if customer:
        parts.append(f'customer_source_id=eq.{quote(customer, safe="")}')
    if q:
        parts.append(_ilike_or(
            ['receipt_number', 'cashier_name', 'payment_method', 'customer_source_id'],
            q,
        ))
    return '&'.join(parts)


def analytics_list_sales(
    org_id: str,
    *,
    start: str,
    end: str = '',
    page: int = 1,
    page_size: int = 25,
    sort: str = 'source_created_at',
    order: str = 'desc',
    status: str = '',
    payment: str = '',
    cashier: str = '',
    customer: str = '',
    q: str = '',
) -> dict:
    start_s, end_s, start_iso, end_iso = analytics_day_bounds(start, end)
    query = _sales_base_query(
        org_id, start_iso, end_iso,
        status=status, payment=payment, cashier=cashier, customer=customer, q=q,
        sort=sort, order=order,
    )
    offset = (page - 1) * page_size
    rows, total = service_select_page(query=query, table='cloud_sales', limit=page_size, offset=offset)
    pages = max(1, int(math.ceil(total / page_size))) if page_size else 1
    return {
        'org_id': org_id,
        'start': start_s,
        'end': end_s,
        'page': page,
        'page_size': page_size,
        'total': total,
        'total_count': total,
        'pages': pages,
        'sales': [analytics_normalize_row(r) for r in rows],
        'items': [analytics_normalize_row(r) for r in rows],
    }


def analytics_sale_detail(org_id: str, device_id: str, source_id: str) -> dict:
    oid = _org_eq(org_id)
    did = quote(str(device_id), safe='')
    sid = quote(str(source_id), safe='')
    sales = service_select_strict(
        'cloud_sales',
        f'{oid}&device_id=eq.{did}&source_id=eq.{sid}&select=*&limit=1',
    )
    if not sales:
        # Allow device_identifier string by resolving devices.device_id → devices.id
        devices = service_select_strict(
            'devices',
            f'{oid}&device_id=eq.{did}&select=id&limit=1',
        )
        if devices:
            sales = service_select_strict(
                'cloud_sales',
                f'{oid}&device_id=eq.{quote(str(devices[0]["id"]), safe="")}'
                f'&source_id=eq.{sid}&select=*&limit=1',
            )
    if not sales:
        raise LookupError('Sale not found')
    sale = analytics_normalize_row(sales[0])
    sale_device = quote(str(sale.get('device_id') or device_id), safe='')
    items = service_select_strict(
        'cloud_sale_items',
        f'{oid}&device_id=eq.{sale_device}'
        f'&or=(sale_source_id.eq.{sid},sale_id.eq.{sid})'
        f'&select=*&order=source_id.asc',
    )
    sale['items'] = [analytics_normalize_row(i) for i in (items or [])]
    sale['line_items'] = sale['items']
    return sale


def analytics_list_debts(
    org_id: str,
    *,
    start: str = '',
    end: str = '',
    page: int = 1,
    page_size: int = 25,
    sort: str = 'source_created_at',
    order: str = 'desc',
    status: str = '',
    customer: str = '',
    q: str = '',
    include_payments: bool = True,
) -> dict:
    parts = [_org_eq(org_id), 'select=*']
    if start or end:
        start_s, end_s, start_iso, end_iso = analytics_day_bounds(start or end, end or start)
        parts.extend([
            f'source_created_at=gte.{quote(start_iso, safe=":")}',
            f'source_created_at=lt.{quote(end_iso, safe=":")}',
        ])
    else:
        start_s = end_s = ''
    parts.append(analytics_sort_clause(
        sort, order,
        allowed={
            'source_created_at', 'due_date', 'total_amount', 'balance', 'amount_paid',
            'status', 'invoice_number', 'customer_name', 'source_id', 'source_updated_at',
        },
        default='source_created_at',
    ))
    if status:
        parts.append(f'status=eq.{quote(status, safe="")}')
    if customer:
        parts.append(
            f'or=(customer_name.ilike.{quote(f"*{customer}*", safe="*")},'
            f'customer_phone.ilike.{quote(f"*{customer}*", safe="*")})'
        )
    if q:
        parts.append(_ilike_or(
            ['invoice_number', 'receipt_number', 'customer_name', 'customer_phone'],
            q,
        ))
    query = '&'.join(parts)
    offset = (page - 1) * page_size
    rows, total = service_select_page('cloud_debt_invoices', query, limit=page_size, offset=offset)
    debts = []
    for inv in rows:
        clean = analytics_normalize_row(inv)
        # Party info: name/phone only
        party = {
            'customer_id': clean.get('customer_id'),
            'name': clean.get('customer_name'),
            'phone': clean.get('customer_phone'),
        }
        clean['customer'] = party
        if include_payments:
            inv_source = quote(str(clean.get('source_id') or ''), safe='')
            inv_id = quote(str(clean.get('id') or clean.get('source_id') or ''), safe='')
            device = str(clean.get('device_id') or '').strip()
            pay_parts = [
                _org_eq(org_id),
                f'or=(invoice_source_id.eq.{inv_source},invoice_id.eq.{inv_source},'
                f'invoice_id.eq.{inv_id})',
                'select=*',
                'order=source_created_at.asc,source_id.asc',
            ]
            if device:
                pay_parts.insert(1, f'device_id=eq.{quote(device, safe="")}')
            try:
                payments = service_select_strict('cloud_debt_payments', '&'.join(pay_parts))
            except SupabaseError:
                payments = []
            clean['payments'] = [
                analytics_normalize_row(p) for p in (payments or [])
            ]
            clean['payment_history'] = clean['payments']
        debts.append(clean)
    pages = max(1, int(math.ceil(total / page_size))) if page_size else 1
    return {
        'org_id': org_id,
        'start': start_s,
        'end': end_s,
        'page': page,
        'page_size': page_size,
        'total': total,
        'total_count': total,
        'pages': pages,
        'debts': debts,
        'items': debts,
    }


def analytics_list_debt_payments(
    org_id: str,
    *,
    start: str,
    end: str = '',
    page: int = 1,
    page_size: int = 25,
    sort: str = 'source_created_at',
    order: str = 'desc',
    payment: str = '',
    customer: str = '',
    q: str = '',
) -> dict:
    start_s, end_s, start_iso, end_iso = analytics_day_bounds(start, end)
    parts = [
        _org_eq(org_id),
        f'source_created_at=gte.{quote(start_iso, safe=":")}',
        f'source_created_at=lt.{quote(end_iso, safe=":")}',
        'select=*',
        analytics_sort_clause(
            sort, order,
            allowed={
                'source_created_at', 'amount', 'payment_method', 'source_id',
                'cashier_name', 'payment_receipt',
            },
        ),
    ]
    if payment:
        parts.append(f'payment_method=ilike.{quote(payment, safe="")}')
    if customer:
        parts.append(f'customer_id=eq.{quote(customer, safe="")}')
    if q:
        parts.append(_ilike_or(
            ['payment_receipt', 'cashier_name', 'notes', 'payment_method'],
            q,
        ))
    query = '&'.join(parts)
    offset = (page - 1) * page_size
    rows, total = service_select_page(
        'cloud_debt_payments', query, limit=page_size, offset=offset,
    )
    payments = [analytics_normalize_row(r) for r in rows]
    pages = max(1, int(math.ceil(total / page_size))) if page_size else 1
    return {
        'org_id': org_id,
        'start': start_s,
        'end': end_s,
        'page': page,
        'page_size': page_size,
        'total': total,
        'total_count': total,
        'pages': pages,
        'payments': payments,
        'items': payments,
    }


def analytics_list_inventory(
    org_id: str,
    *,
    page: int = 1,
    page_size: int = 25,
    sort: str = 'name',
    order: str = 'asc',
    q: str = '',
    stock: str = '',
    status: str = '',
) -> dict:
    parts = [
        _org_eq(org_id),
        'select=*',
        analytics_sort_clause(
            sort, order,
            allowed={
                'name', 'sku', 'category', 'stock', 'min_stock', 'price',
                'cost_price', 'source_updated_at', 'source_id',
            },
            default='name',
        ),
    ]
    stock_filter = (stock or status or '').strip().lower()
    if stock_filter in ('low', 'low_stock'):
        # PostgREST cannot easily express stock <= min_stock; fetch then filter.
        pass
    elif stock_filter in ('out', 'out_of_stock', 'oos'):
        parts.append('stock=lte.0')
    elif stock_filter in ('in', 'in_stock', 'ok'):
        parts.append('stock=gt.0')
    if q:
        parts.append(_ilike_or(['name', 'sku', 'category', 'barcode'], q))
    query = '&'.join(parts)

    if stock_filter in ('low', 'low_stock'):
        all_rows = analytics_fetch_all('cloud_products', query, max_rows=ANALYTICS_EXPORT_MAX)
        filtered = [
            r for r in all_rows
            if _fnum(r.get('stock')) <= _fnum(r.get('min_stock'), 0)
            and str(r.get('is_active', True)).lower() not in ('0', 'false')
        ]
        total = len(filtered)
        start_i = (page - 1) * page_size
        page_rows = filtered[start_i:start_i + page_size]
    else:
        offset = (page - 1) * page_size
        page_rows, total = service_select_page(
            'cloud_products', query, limit=page_size, offset=offset,
        )

    inventory = [analytics_normalize_row(r) for r in page_rows]
    for row in inventory:
        stock_qty = _fnum(row.get('stock'))
        min_stock = _fnum(row.get('min_stock'), 0)
        if stock_qty <= 0:
            row['stock_status'] = 'out of stock'
        elif stock_qty <= min_stock:
            row['stock_status'] = 'low stock'
        else:
            row['stock_status'] = 'in stock'
    pages = max(1, int(math.ceil(total / page_size))) if page_size else 1
    return {
        'org_id': org_id,
        'page': page,
        'page_size': page_size,
        'total': total,
        'total_count': total,
        'pages': pages,
        'inventory': inventory,
        'items': inventory,
    }


def analytics_filter_options(org_id: str) -> dict:
    """Distinct cashiers/payments/statuses/categories for filter dropdowns."""
    oid = _org_eq(org_id)
    sales = analytics_fetch_all(
        'cloud_sales',
        f'{oid}&select=cashier_name,payment_method,status&order=source_created_at.desc',
        max_rows=5000,
    )
    products = analytics_fetch_all(
        'cloud_products',
        f'{oid}&select=category&order=category.asc',
        max_rows=5000,
    )
    debts = analytics_fetch_all(
        'cloud_debt_invoices',
        f'{oid}&select=status&order=source_created_at.desc',
        max_rows=2000,
    )

    def _uniq(values: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for raw in values:
            v = str(raw or '').strip()
            if not v:
                continue
            key = v.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(v)
        return sorted(out, key=str.lower)

    return {
        'org_id': org_id,
        'cashiers': _uniq([s.get('cashier_name') for s in sales]),
        'payment_methods': _uniq([s.get('payment_method') for s in sales]),
        'sale_statuses': _uniq([s.get('status') for s in sales]),
        'debt_statuses': _uniq([d.get('status') for d in debts]),
        'categories': _uniq([p.get('category') for p in products]),
        'stock_filters': [
            {'value': 'all', 'label': 'All stock'},
            {'value': 'low', 'label': 'Low stock'},
            {'value': 'out', 'label': 'Out of stock'},
            {'value': 'in', 'label': 'In stock'},
        ],
    }


def analytics_overview(org_id: str, *, start: str, end: str = '') -> dict:
    start_s, end_s, start_iso, end_iso = analytics_day_bounds(start, end)
    sales_q = (
        f'{_org_eq(org_id)}'
        f'&source_created_at=gte.{quote(start_iso, safe=":")}'
        f'&source_created_at=lt.{quote(end_iso, safe=":")}'
        f'&select=*&order=source_created_at.asc,source_id.asc'
    )
    sales = analytics_fetch_all('cloud_sales', sales_q, max_rows=ANALYTICS_EXPORT_MAX)
    payments = analytics_fetch_all(
        'cloud_debt_payments',
        f'{_org_eq(org_id)}'
        f'&source_created_at=gte.{quote(start_iso, safe=":")}'
        f'&source_created_at=lt.{quote(end_iso, safe=":")}'
        f'&select=*&order=source_created_at.asc,source_id.asc',
        max_rows=ANALYTICS_EXPORT_MAX,
    )
    debt_invoices = analytics_fetch_all(
        'cloud_debt_invoices',
        f'{_org_eq(org_id)}&select=*&order=source_created_at.desc,source_id.asc',
        max_rows=ANALYTICS_EXPORT_MAX,
    )
    products = analytics_fetch_all(
        'cloud_products',
        f'{_org_eq(org_id)}&select=*&order=name.asc,source_id.asc',
        max_rows=ANALYTICS_EXPORT_MAX,
    )

    active_sales = [s for s in sales if not analytics_is_void(s)]
    void_sales = [s for s in sales if analytics_is_void(s)]
    gross_sales = round(sum(_fnum(s.get('total')) for s in active_sales), 2)
    collected_from_sales = round(
        sum(analytics_sale_collected_amount(s) for s in active_sales), 2,
    )
    debt_collected = round(sum(_fnum(p.get('amount')) for p in payments), 2)
    collected_revenue = round(collected_from_sales + debt_collected, 2)
    debt_issued = round(sum(
        _fnum(s.get('total')) for s in active_sales
        if str(s.get('payment_method') or '').lower() in ('credit sale', 'credit', 'part payment')
    ), 2)
    outstanding_invoices = [
        d for d in debt_invoices
        if str(d.get('status') or '').lower() not in ('paid', 'cancelled', 'canceled', 'written_off')
        and _fnum(d.get('balance')) > 0.009
    ]
    debt_outstanding = round(sum(_fnum(d.get('balance')) for d in outstanding_invoices), 2)
    today_nairobi = datetime.now(NAIROBI_TZ).date().isoformat()
    overdue = [
        d for d in outstanding_invoices
        if (d.get('due_date') or '')[:10] and str(d.get('due_date'))[:10] < today_nairobi
    ]
    debt_overdue = round(sum(_fnum(d.get('balance')) for d in overdue), 2)
    txns = len(active_sales)
    discounts = round(sum(_fnum(s.get('discount')) for s in active_sales), 2)
    tax = round(sum(_fnum(s.get('tax')) for s in active_sales), 2)
    avg_sale = round(gross_sales / txns, 2) if txns else 0.0

    # Line items for the sales in range (device-safe join keys)
    item_rows: list[dict] = []
    sale_keys = {
        (str(s.get('device_id') or ''), str(s.get('source_id') or ''))
        for s in active_sales
    }
    if sale_keys:
        raw_items = analytics_fetch_all(
            'cloud_sale_items',
            f'{_org_eq(org_id)}&select=*&order=source_created_at.asc,source_id.asc',
            max_rows=ANALYTICS_EXPORT_MAX,
        )
        for item in raw_items:
            key = (
                str(item.get('device_id') or ''),
                str(item.get('sale_source_id') or item.get('sale_id') or ''),
            )
            if key in sale_keys:
                item_rows.append(item)

    items_sold = round(sum(_fnum(i.get('quantity')) for i in item_rows), 3)
    line_items = len(item_rows)
    cost_of_goods = round(sum(
        _fnum(i.get('quantity')) * _fnum(i.get('unit_cost', i.get('cost_price')))
        for i in item_rows
    ), 2)
    # Prefer sale-time cost snapshot; fall back is already unit_cost/cost_price.
    item_revenue = round(sum(_fnum(i.get('total')) for i in item_rows), 2)
    gross_profit = round(item_revenue - cost_of_goods, 2)
    gross_margin_pct = round((gross_profit / item_revenue) * 100, 2) if item_revenue else 0.0

    # Payment mix uses collected tender (not unpaid credit totals)
    pay_map: dict[str, dict] = {}
    for s in active_sales:
        method = str(s.get('payment_method') or 'Unknown').strip() or 'Unknown'
        bucket = pay_map.setdefault(method, {'payment_method': method, 'count': 0, 'total': 0.0})
        bucket['count'] += 1
        bucket['total'] = round(bucket['total'] + analytics_sale_collected_amount(s), 2)
    payment_mix = sorted(pay_map.values(), key=lambda r: -r['total'])

    by_day: dict[str, dict] = {}
    by_hour: dict[str, dict] = {}
    for s in active_sales:
        created = str(s.get('source_created_at') or s.get('created_at') or '')
        try:
            dt = datetime.fromisoformat(created.replace('Z', '+00:00')).astimezone(NAIROBI_TZ)
            day = dt.date().isoformat()
            hour = f'{dt.hour:02d}'
        except ValueError:
            day = created[:10] or 'unknown'
            hour = (created[11:13] if len(created) >= 13 else '00') or '00'
        day_row = by_day.setdefault(day, {'date': day, 'day': day, 'transactions': 0, 'gross_sales': 0.0, 'txns': 0, 'revenue': 0.0})
        day_row['transactions'] += 1
        day_row['txns'] += 1
        day_row['gross_sales'] = round(day_row['gross_sales'] + _fnum(s.get('total')), 2)
        day_row['revenue'] = day_row['gross_sales']
        hour_row = by_hour.setdefault(hour, {'hour': hour, 'transactions': 0, 'txns': 0, 'revenue': 0.0})
        hour_row['transactions'] += 1
        hour_row['txns'] += 1
        hour_row['revenue'] = round(hour_row['revenue'] + _fnum(s.get('total')), 2)

    prod_map: dict[str, dict] = {}
    cat_map: dict[str, dict] = {}
    for i in item_rows:
        name = str(i.get('product_name') or 'Item')
        cat = str(i.get('category') or '').strip() or 'Uncategorized'
        rev = _fnum(i.get('total'))
        qty = _fnum(i.get('quantity'))
        cost = qty * _fnum(i.get('unit_cost', i.get('cost_price')))
        p = prod_map.setdefault(name, {
            'name': name, 'category': cat, 'qty': 0.0, 'revenue': 0.0, 'cost': 0.0, 'profit': 0.0,
        })
        p['qty'] = round(p['qty'] + qty, 3)
        p['revenue'] = round(p['revenue'] + rev, 2)
        p['cost'] = round(p['cost'] + cost, 2)
        p['profit'] = round(p['revenue'] - p['cost'], 2)
        c = cat_map.setdefault(cat, {'category': cat, 'qty': 0.0, 'revenue': 0.0})
        c['qty'] = round(c['qty'] + qty, 3)
        c['revenue'] = round(c['revenue'] + rev, 2)

    top_products = sorted(prod_map.values(), key=lambda r: -r['revenue'])[:25]
    top_categories = sorted(cat_map.values(), key=lambda r: -r['revenue'])[:20]

    active_products = [
        p for p in products
        if str(p.get('is_active', True)).lower() not in ('0', 'false')
    ]
    low_stock = [
        p for p in active_products
        if _fnum(p.get('stock')) <= _fnum(p.get('min_stock'), 0) and _fnum(p.get('stock')) > 0
    ]
    out_stock = [p for p in active_products if _fnum(p.get('stock')) <= 0]
    inventory_value = round(sum(
        _fnum(p.get('stock')) * _fnum(p.get('cost_price')) for p in active_products
    ), 2)

    summary = {
        'currency': 'KES',
        'gross_sales': gross_sales,
        'sales_total': gross_sales,
        'revenue': gross_sales,
        'collected_revenue': collected_revenue,
        'collected': collected_revenue,
        'collected_from_sales': collected_from_sales,
        'transactions': txns,
        'sales_count': txns,
        'avg_sale': avg_sale,
        'avg_ticket': avg_sale,
        'discounts': discounts,
        'tax': tax,
        'items_sold': items_sold,
        'line_items': line_items,
        'void_transactions': len(void_sales),
        'void_revenue': round(sum(_fnum(s.get('total')) for s in void_sales), 2),
        'debt_issued': debt_issued,
        'credit_sales': debt_issued,
        'debt_collected': debt_collected,
        'debt_payments': debt_collected,
        'debt_outstanding': debt_outstanding,
        'outstanding_debt': debt_outstanding,
        'debt_overdue': debt_overdue,
        'overdue_count': len(overdue),
        'outstanding_count': len(outstanding_invoices),
        'cost_of_goods': cost_of_goods,
        'gross_profit': gross_profit,
        'gross_margin_pct': gross_margin_pct,
        'inventory_value': inventory_value,
        'low_stock_count': len(low_stock) + len(out_stock),
        'out_of_stock_count': len(out_stock),
        'low_only_count': len(low_stock),
        'last_sync_at': analytics_last_sync_at(org_id),
    }
    return {
        'org_id': org_id,
        'start': start_s,
        'end': end_s,
        'currency': 'KES',
        'summary': summary,
        'kpis': summary,
        'payment_methods': payment_mix,
        'payment_mix': payment_mix,
        'by_day': [by_day[k] for k in sorted(by_day.keys())],
        'trend': [by_day[k] for k in sorted(by_day.keys())],
        'sales_trend': [by_day[k] for k in sorted(by_day.keys())],
        'by_hour': [by_hour[k] for k in sorted(by_hour.keys())],
        'top_products': top_products,
        'top_categories': top_categories,
        'by_category': top_categories,
        'low_stock': [
            analytics_strip_sensitive({
                'name': p.get('name'),
                'sku': p.get('sku'),
                'category': p.get('category'),
                'stock': p.get('stock'),
                'min_stock': p.get('min_stock'),
                'cost_price': p.get('cost_price'),
                'price': p.get('price'),
                'device_id': p.get('device_id'),
                'source_id': p.get('source_id'),
            })
            for p in sorted(
                low_stock + out_stock,
                key=lambda r: (_fnum(r.get('stock')), str(r.get('name') or '')),
            )
        ],
        'last_sync_at': summary['last_sync_at'],
    }


def analytics_export_rows(
    org_id: str,
    *,
    report: str,
    start: str,
    end: str = '',
    status: str = '',
    payment: str = '',
    cashier: str = '',
    customer: str = '',
    q: str = '',
    stock: str = '',
    sort: str = '',
    order: str = 'desc',
) -> tuple[list[dict], list[str]]:
    """Return (rows, fieldnames) for all matching export rows (bounded)."""
    kind = (report or 'sales').strip().lower()
    if kind in ('sales', 'all_sales', 'overview'):
        start_s, end_s, start_iso, end_iso = analytics_day_bounds(start, end)
        query = _sales_base_query(
            org_id, start_iso, end_iso,
            status=status, payment=payment, cashier=cashier, customer=customer, q=q,
            sort=sort or 'source_created_at', order=order,
        )
        rows = analytics_fetch_all('cloud_sales', query, max_rows=ANALYTICS_EXPORT_MAX)
        fields = [
            'device_id', 'source_id', 'receipt_number', 'created_at', 'cashier_name',
            'payment_method', 'status', 'subtotal', 'discount', 'tax', 'total',
            'amount_paid', 'change_amount', 'customer_name',
        ]
        return [analytics_normalize_row(r) for r in rows], fields
    if kind in ('debts', 'debt', 'debt_invoices'):
        if start or end:
            _start_s, _end_s, start_iso, end_iso = analytics_day_bounds(
                start or end, end or start,
            )
        else:
            start_iso = end_iso = ''
        parts = [_org_eq(org_id), 'select=*']
        if start_iso:
            parts.extend([
                f'source_created_at=gte.{quote(start_iso, safe=":")}',
                f'source_created_at=lt.{quote(end_iso, safe=":")}',
            ])
        if status:
            parts.append(f'status=eq.{quote(status, safe="")}')
        if customer:
            parts.append(
                f'or=(customer_name.ilike.{quote(f"*{customer}*", safe="*")},'
                f'customer_phone.ilike.{quote(f"*{customer}*", safe="*")})'
            )
        if q:
            parts.append(_ilike_or(
                ['invoice_number', 'receipt_number', 'customer_name', 'customer_phone'],
                q,
            ))
        parts.append(analytics_sort_clause(
            sort or 'source_created_at', order,
            allowed={
                'source_created_at', 'due_date', 'total_amount', 'balance', 'status',
                'invoice_number', 'source_id',
            },
        ))
        rows = analytics_fetch_all(
            'cloud_debt_invoices', '&'.join(parts), max_rows=ANALYTICS_EXPORT_MAX,
        )
        fields = [
            'device_id', 'source_id', 'invoice_number', 'receipt_number', 'created_at',
            'customer_name', 'customer_phone', 'total_amount', 'amount_paid', 'balance',
            'status', 'due_date',
        ]
        return [analytics_normalize_row(r) for r in rows], fields
    if kind in ('debt_payments', 'payments'):
        _start_s, _end_s, start_iso, end_iso = analytics_day_bounds(start, end)
        parts = [
            _org_eq(org_id),
            f'source_created_at=gte.{quote(start_iso, safe=":")}',
            f'source_created_at=lt.{quote(end_iso, safe=":")}',
            'select=*',
            analytics_sort_clause(
                sort or 'source_created_at', order,
                allowed={'source_created_at', 'amount', 'payment_method', 'source_id'},
            ),
        ]
        if payment:
            parts.append(f'payment_method=ilike.{quote(payment, safe="")}')
        if q:
            parts.append(_ilike_or(
                ['payment_receipt', 'cashier_name', 'notes', 'payment_method'], q,
            ))
        rows = analytics_fetch_all(
            'cloud_debt_payments', '&'.join(parts), max_rows=ANALYTICS_EXPORT_MAX,
        )
        fields = [
            'device_id', 'source_id', 'payment_receipt', 'source_created_at', 'amount',
            'payment_method', 'cashier_name', 'invoice_source_id', 'customer_id',
        ]
        return [analytics_normalize_row(r) for r in rows], fields
    if kind in ('inventory', 'products', 'stock'):
        parts = [_org_eq(org_id), 'select=*']
        if q:
            parts.append(_ilike_or(['name', 'sku', 'category', 'barcode'], q))
        parts.append(analytics_sort_clause(
            sort or 'name', order or 'asc',
            allowed={
                'name', 'sku', 'category', 'stock', 'min_stock', 'price',
                'cost_price', 'source_id',
            },
            default='name',
        ))
        rows = analytics_fetch_all(
            'cloud_products', '&'.join(parts), max_rows=ANALYTICS_EXPORT_MAX,
        )
        stock_filter = (stock or '').strip().lower()
        if stock_filter in ('low', 'low_stock'):
            rows = [
                r for r in rows
                if _fnum(r.get('stock')) <= _fnum(r.get('min_stock'), 0)
            ]
        elif stock_filter in ('out', 'out_of_stock', 'oos'):
            rows = [r for r in rows if _fnum(r.get('stock')) <= 0]
        fields = [
            'device_id', 'source_id', 'name', 'sku', 'category', 'price',
            'cost_price', 'stock', 'min_stock', 'unit', 'is_active',
        ]
        return [analytics_normalize_row(r) for r in rows], fields
    raise ValueError(f'Unsupported export report: {report}')


def analytics_rows_to_csv(rows: list[dict], fieldnames: list[str]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, '') for k in fieldnames})
    return '\ufeff' + buf.getvalue()
