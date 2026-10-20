"""
Minimal Supabase client via requests (Auth + PostgREST + Storage).
No supabase-py dependency required.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
import threading
from typing import Any, Optional
from urllib.parse import quote

import requests

from backend.cloud_backup.paths import (
    is_cloud_configured,
    load_cloud_config,
    load_identity,
    save_identity,
)

logger = logging.getLogger('cloud_backup.supabase')

DEFAULT_TIMEOUT = 12  # Fail open quickly when Portal/Supabase unreachable


class _GatedSession(requests.Session):
    """Skip hostname DNS/TLS when the shop has no IP route, and never wait past the deadline.

    The busy lock belongs to this session only. A timed-out call marks the
    session abandoned and the client opens a new one. The abandoned worker
    must not keep every later cloud call waiting.
    """

    def __init__(self):
        super().__init__()
        self._busy = threading.Lock()
        self._abandoned = False

    def request(self, method, url, **kwargs):
        import time
        from backend.cloud.net_gate import (
            bounded_timeout, call_with_deadline, mark_network_down, network_up,
        )
        from backend.cloud.reliability_log import note
        started = time.perf_counter()
        if self._abandoned:
            note('net', 'supabase', 0, 'abandoned', 'session replaced after timeout')
            raise requests.ConnectionError('MugoByte Cloud is still not answering')
        if not network_up(1.0):
            mark_network_down()
            note('net', 'supabase', (time.perf_counter() - started) * 1000, 'offline')
            raise requests.ConnectionError('Offline — MugoByte Cloud unreachable')
        if not self._busy.acquire(blocking=False):
            note('net', 'supabase', 0, 'busy', 'previous cloud call still running')
            raise requests.ConnectionError('MugoByte Cloud is still not answering')
        limit = bounded_timeout(kwargs.get('timeout') or DEFAULT_TIMEOUT)
        kwargs['timeout'] = limit

        def _call():
            try:
                return super(_GatedSession, self).request(method, url, **kwargs)
            finally:
                self._busy.release()

        try:
            result = call_with_deadline(_call, limit, label='supabase')
            note('net', 'supabase', (time.perf_counter() - started) * 1000, 'ok')
            return result
        except TimeoutError as exc:
            self._abandoned = True
            mark_network_down(20)
            note('net', 'supabase', (time.perf_counter() - started) * 1000, 'timeout', str(exc))
            raise requests.ConnectionError(str(exc)) from exc
        except requests.RequestException as exc:
            mark_network_down()
            note('net', 'supabase', (time.perf_counter() - started) * 1000, 'error', type(exc).__name__)
            raise
UPLOAD_TIMEOUT = 300
DOWNLOAD_TIMEOUT = 300


_TOKEN_RE = re.compile(r'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')


def redact_tokens(text: str) -> str:
    return _TOKEN_RE.sub('<redacted-token>', str(text or ''))


def _looks_like_expired_session(err: Exception) -> bool:
    if not isinstance(err, SupabaseError) or err.status not in (400, 401, 403):
        return False
    text = str(err).lower()
    return (
        'exp" claim' in text
        or 'exp claim' in text
        or 'jwt expired' in text
        or 'token is expired' in text
    )


class SupabaseError(Exception):
    def __init__(self, message: str, status: int = 0, payload: Any = None):
        super().__init__(redact_tokens(message))
        self.status = status
        self.payload = payload


class SupabaseClient:
    def __init__(self, config: dict | None = None):
        self.cfg = config or load_cloud_config()
        self.base = (self.cfg.get('supabase_url') or '').rstrip('/')
        self.anon = self.cfg.get('anon_key') or ''
        self.service = self.cfg.get('service_key') or ''
        self.bucket = self.cfg.get('bucket') or 'mbt-backups'
        self._http = _GatedSession()

    @property
    def _session(self):
        """A timed-out session stays with its abandoned worker. The next call gets a new one."""
        http = self.__dict__.get('_http')
        if http is None or getattr(http, '_abandoned', False):
            self._http = _GatedSession()
        return self._http

    @property
    def configured(self) -> bool:
        return bool(self.base and self.anon)

    def _headers(self, use_service: bool = False, token: str | None = None) -> dict:
        key = self.service if (use_service and self.service) else self.anon
        h = {
            'apikey': key,
            'Authorization': f'Bearer {token or key}',
            'Content-Type': 'application/json',
            'Prefer': 'return=representation',
        }
        return h

    def _url(self, path: str) -> str:
        return f'{self.base}{path}'

    def _raise(self, r: requests.Response, action: str):
        try:
            body = r.json()
        except Exception:
            body = r.text[:500]
        msg = f'{action} failed ({r.status_code})'
        if isinstance(body, dict):
            msg = body.get('msg') or body.get('message') or body.get('error_description') or msg
        raise SupabaseError(str(msg), status=r.status_code, payload=body)

    # ── Auth ──────────────────────────────────────────────────────────────────

    def sign_up(
        self,
        email: str,
        password: str,
        metadata: dict | None = None,
        redirect_to: str = '',
    ) -> dict:
        payload: dict[str, Any] = {'email': email, 'password': password}
        if metadata:
            payload['data'] = metadata
        if redirect_to:
            payload['email_redirect_to'] = redirect_to
            payload['redirect_to'] = redirect_to
        r = self._session.post(
            self._url(
                '/auth/v1/signup'
                + (f'?redirect_to={requests.utils.quote(redirect_to, safe="")}' if redirect_to else '')
            ),
            headers=self._headers(),
            json=payload,
            timeout=DEFAULT_TIMEOUT,
        )
        if r.status_code >= 400:
            self._raise(r, 'Sign up')
        return r.json()

    def generate_auth_link(
        self,
        *,
        email: str,
        link_type: str = 'signup',
        redirect_to: str = 'https://portal.mugobyte.com/auth/callback',
        password: str = '',
        metadata: dict | None = None,
    ) -> dict:
        """Admin generate_link — returns action_link for reliable Resend delivery."""
        if not self.service:
            raise SupabaseError('Service role key required to generate auth links', 503)
        payload: dict[str, Any] = {
            'type': link_type,
            'email': email,
            'options': {'redirect_to': redirect_to},
            'redirect_to': redirect_to,
        }
        if password:
            payload['password'] = password
        if metadata:
            payload['data'] = metadata
        r = self._session.post(
            self._url('/auth/v1/admin/generate_link'),
            headers=self._headers(use_service=True),
            json=payload,
            timeout=DEFAULT_TIMEOUT,
        )
        if r.status_code >= 400:
            self._raise(r, 'Generate auth link')
        data = r.json()
        # GoTrue sometimes stamps Site URL instead of options.redirect_to.
        # Rewrite so verify/magic/recovery land on the Portal auth routes.
        try:
            from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

            action = data.get('action_link') or (data.get('properties') or {}).get('action_link') or ''
            if action and redirect_to:
                parts = urlparse(action)
                qs = parse_qs(parts.query)
                qs['redirect_to'] = [redirect_to]
                new_query = urlencode({k: v[0] for k, v in qs.items()})
                fixed = urlunparse(parts._replace(query=new_query))
                data['action_link'] = fixed
                props = data.get('properties')
                if isinstance(props, dict):
                    props['action_link'] = fixed
        except Exception:
            pass
        return data

    def sign_in(self, email: str, password: str, *, persist: bool = True) -> dict:
        r = self._session.post(
            self._url('/auth/v1/token?grant_type=password'),
            headers=self._headers(),
            json={'email': email, 'password': password},
            timeout=DEFAULT_TIMEOUT,
        )
        if r.status_code >= 400:
            self._raise(r, 'Sign in')
        data = r.json()
        if persist:
            ident = load_identity()
            ident['access_token'] = data.get('access_token') or ''
            ident['refresh_token'] = data.get('refresh_token') or ''
            user = data.get('user') or {}
            ident['user_id'] = user.get('id') or ident.get('user_id') or ''
            ident['email'] = email
            save_identity(ident)
        return data

    def refresh_session(self) -> dict:
        ident = load_identity()
        refresh = ident.get('refresh_token') or ''
        if not refresh:
            raise SupabaseError('No refresh token')
        r = self._session.post(
            self._url('/auth/v1/token?grant_type=refresh_token'),
            headers=self._headers(),
            json={'refresh_token': refresh},
            timeout=DEFAULT_TIMEOUT,
        )
        if r.status_code >= 400:
            self._raise(r, 'Refresh token')
        data = r.json()
        ident['access_token'] = data.get('access_token') or ''
        ident['refresh_token'] = data.get('refresh_token') or refresh
        save_identity(ident)
        return data

    def access_token(self) -> str:
        return (load_identity().get('access_token') or '').strip()

    def _authed_headers(self, prefer: str | None = None) -> dict:
        token = self.access_token()
        if not token:
            raise SupabaseError('Not signed in')
        h = self._headers(token=token)
        if prefer:
            h['Prefer'] = prefer
        return h

    def with_auth_retry(self, fn):
        try:
            return fn()
        except SupabaseError as e:
            if e.status not in (401, 403) and not _looks_like_expired_session(e):
                raise
            self.refresh_session()
            return fn()

    # ── REST helpers ──────────────────────────────────────────────────────────

    def rest_select(
        self,
        table: str,
        query: str = '',
        single: bool = False,
    ) -> Any:
        def _do():
            url = self._url(f'/rest/v1/{table}')
            if query:
                url = f'{url}?{query}'
            h = self._authed_headers()
            if single:
                h['Accept'] = 'application/vnd.pgrst.object+json'
            r = self._session.get(url, headers=h, timeout=DEFAULT_TIMEOUT)
            if r.status_code >= 400:
                self._raise(r, f'Select {table}')
            if not r.content:
                return None if single else []
            return r.json()

        return self.with_auth_retry(_do)

    def rest_insert(self, table: str, rows: dict | list, upsert: bool = False,
                    on_conflict: str = '') -> Any:
        def _do():
            prefer = 'return=representation'
            if upsert:
                prefer += ',resolution=merge-duplicates'
            h = self._authed_headers(prefer=prefer)
            url = self._url(f'/rest/v1/{table}')
            if upsert and on_conflict:
                url = f'{url}?on_conflict={on_conflict}'
            r = self._session.post(
                url,
                headers=h,
                json=rows,
                timeout=DEFAULT_TIMEOUT,
            )
            if r.status_code >= 400:
                self._raise(r, f'Insert {table}')
            return r.json() if r.content else None

        return self.with_auth_retry(_do)

    def rest_update(self, table: str, query: str, patch: dict) -> Any:
        def _do():
            h = self._authed_headers()
            r = self._session.patch(
                self._url(f'/rest/v1/{table}?{query}'),
                headers=h,
                json=patch,
                timeout=DEFAULT_TIMEOUT,
            )
            if r.status_code >= 400:
                self._raise(r, f'Update {table}')
            return r.json() if r.content else None

        return self.with_auth_retry(_do)

    def rest_delete(self, table: str, query: str) -> Any:
        def _do(use_service: bool = False):
            if use_service and self.service:
                h = {
                    'apikey': self.service,
                    'Authorization': f'Bearer {self.service}',
                    'Prefer': 'return=minimal',
                }
            else:
                h = self._authed_headers(prefer='return=minimal')
            r = self._session.delete(
                self._url(f'/rest/v1/{table}?{query}'),
                headers=h,
                timeout=DEFAULT_TIMEOUT,
            )
            if r.status_code >= 400:
                self._raise(r, f'Delete {table}')
            return r.json() if r.content else None

        try:
            return self.with_auth_retry(lambda: _do(False))
        except SupabaseError as e:
            if self.service and e.status in (400, 401, 403):
                return _do(True)
            raise

    # ── Domain helpers ────────────────────────────────────────────────────────

    def upsert_business(self, name: str, owner_user_id: str) -> dict:
        # Try find existing owned business
        rows = self.rest_select(
            'businesses',
            f'owner_user_id=eq.{quote(owner_user_id, safe="")}&select=*&limit=1',
        ) or []
        if rows:
            biz = rows[0]
            if name and biz.get('name') != name:
                self.rest_update('businesses', f'id=eq.{biz["id"]}', {'name': name})
                biz['name'] = name
            return biz
        inserted = self.rest_insert('businesses', {
            'name': name or 'My Business',
            'owner_user_id': owner_user_id,
        })
        if isinstance(inserted, list):
            return inserted[0]
        return inserted

    def register_device(self, business_id: str, device_id: str, hostname: str = '',
                        platform_str: str = '', mbt_version: str = '') -> dict:
        row = {
            'business_id': business_id,
            'device_id': device_id,
            'hostname': hostname,
            'platform': platform_str,
            'mbt_version': mbt_version,
            'last_seen_at': 'now()',
            'is_active': True,
        }
        # PostgREST 'now()' as string won't work — use ISO from client
        from datetime import datetime, timezone
        row['last_seen_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        return self.rest_insert(
            'devices',
            row,
            upsert=True,
            on_conflict='business_id,device_id',
        )

    def insert_backup_meta(self, meta: dict) -> dict:
        try:
            result = self.rest_insert('backups', meta)
            return result[0] if isinstance(result, list) else result
        except SupabaseError as e:
            # Fallback for stale identity / RLS edge cases when service role is available.
            if self.service and ('row-level security' in str(e).lower() or e.status in (401, 403)):
                from backend.cloud.platform_service import service_insert
                result = service_insert('backups', meta)
                return result[0] if isinstance(result, list) else result
            raise

    def upsert_backup_meta(self, meta: dict) -> dict:
        """Update-in-place for rolling slots (latest / daily) so metadata does not grow forever."""
        path = str((meta or {}).get('storage_path') or '').strip()
        if not path:
            return self.insert_backup_meta(meta)
        existing = self.rest_select(
            'backups',
            f'storage_path=eq.{quote(path, safe="")}&select=id&limit=1',
        ) or []
        patch = {
            'size_bytes': meta.get('size_bytes'),
            'content_hash': meta.get('content_hash'),
            'mbt_version': meta.get('mbt_version'),
            'schema_version': meta.get('schema_version'),
            'backup_type': meta.get('backup_type') or 'full_snapshot',
            'reason': meta.get('reason'),
            'created_at': meta.get('created_at'),
            'device_id': meta.get('device_id'),
            'business_id': meta.get('business_id'),
        }
        if existing and existing[0].get('id'):
            rid = existing[0]['id']
            try:
                updated = self.rest_update('backups', f'id=eq.{quote(str(rid), safe="")}', patch)
                if isinstance(updated, list) and updated:
                    return updated[0]
                row = dict(existing[0])
                row.update(patch)
                return row
            except SupabaseError:
                pass
        return self.insert_backup_meta(meta)

    def list_backups(self, business_id: str, limit: int = 20) -> list:
        return self.rest_select(
            'backups',
            f'business_id=eq.{quote(business_id, safe="")}'
            f'&order=created_at.desc&limit={int(limit)}&select=*',
        ) or []

    def list_devices(self, business_id: str) -> list:
        return self.rest_select(
            'devices',
            f'business_id=eq.{quote(business_id, safe="")}'
            f'&order=last_seen_at.desc&select=*',
        ) or []

    def log_sync(self, entry: dict) -> None:
        try:
            self.rest_insert('sync_logs', entry)
        except Exception as e:
            logger.debug('sync_logs insert skipped: %s', e)

    def log_restore(self, entry: dict) -> None:
        try:
            self.rest_insert('restore_history', entry)
        except Exception as e:
            logger.debug('restore_history insert skipped: %s', e)

    # ── Storage ───────────────────────────────────────────────────────────────

    def upload_file(self, object_path: str, file_path: str, content_type: str = '') -> str:
        """Upload to storage bucket. Returns object path."""
        if not content_type:
            content_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'

        def _do(use_service: bool = False):
            token = self.service if use_service and self.service else self.access_token()
            key = self.service if use_service and self.service else self.anon
            url = self._url(
                f'/storage/v1/object/{self.bucket}/{object_path}'
            )
            headers = {
                'apikey': key,
                'Authorization': f'Bearer {token}',
                'Content-Type': content_type,
                'x-upsert': 'true',
            }
            with open(file_path, 'rb') as f:
                r = self._session.post(url, headers=headers, data=f, timeout=300)
            if r.status_code >= 400:
                self._raise(r, 'Storage upload')
            return object_path

        try:
            return self.with_auth_retry(lambda: _do(False))
        except SupabaseError as e:
            if self.service and e.status in (400, 401, 403):
                logger.warning('Storage user upload failed (%s); retrying with service role', e)
                return _do(True)
            raise

    def download_file(self, object_path: str, dest_path: str) -> int:
        def _do():
            token = self.access_token()
            url = self._url(
                f'/storage/v1/object/{self.bucket}/{object_path}'
            )
            headers = {
                'apikey': self.anon,
                'Authorization': f'Bearer {token}',
            }
            r = self._session.get(url, headers=headers, timeout=300, stream=True)
            if r.status_code >= 400:
                self._raise(r, 'Storage download')
            os.makedirs(os.path.dirname(dest_path) or '.', exist_ok=True)
            total = 0
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(1024 * 256):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
            return total

        return self.with_auth_retry(_do)

    def delete_files(self, object_paths: list) -> int:
        """Delete storage objects. Returns number requested (API is best-effort)."""
        paths = [p for p in (object_paths or []) if p]
        if not paths:
            return 0

        def _do(use_service: bool = False):
            token = self.service if use_service and self.service else self.access_token()
            key = self.service if use_service and self.service else self.anon
            url = self._url(f'/storage/v1/object/{self.bucket}')
            headers = {
                'apikey': key,
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            }
            r = self._session.request(
                'DELETE', url, headers=headers, json={'prefixes': paths}, timeout=120,
            )
            # Some Storage versions expect a bare path array.
            if r.status_code >= 400:
                r = self._session.request(
                    'DELETE', url, headers=headers, json=paths, timeout=120,
                )
            if r.status_code >= 400:
                self._raise(r, 'Storage delete')
            return len(paths)

        try:
            return self.with_auth_retry(lambda: _do(False))
        except SupabaseError as e:
            if self.service and e.status in (400, 401, 403):
                return _do(True)
            raise

    def ping(self) -> bool:
        if not self.configured:
            return False
        try:
            r = self._session.get(
                self._url('/auth/v1/health'),
                headers=self._headers(),
                timeout=10,
            )
            return r.status_code < 500
        except Exception:
            return False


def get_client() -> SupabaseClient:
    return SupabaseClient()


def cloud_ready() -> bool:
    return is_cloud_configured() and get_client().configured
