"""
MBT Cloud — Update Center.
Admin uploads POS versions; desktop checks periodically and reports results.

Checksum helpers here are shared with backend.updater for verified installs.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger('cloud.updates')

_SHA256_RE = re.compile(r'\b([a-fA-F0-9]{64})\b')
_CHECKSUM_TAG_RE = re.compile(
    r'\[(?:checksum_sha256|sha256)\s*:\s*([a-fA-F0-9]{64})\]',
    re.IGNORECASE,
)
_CHECKSUM_LINE_RE = re.compile(
    r'(?:checksum_sha256|sha256)\s*[:=]\s*([a-fA-F0-9]{64})',
    re.IGNORECASE,
)


def normalize_checksum(value: str | None) -> str:
    """Return lowercase 64-char hex SHA-256, or '' if invalid/missing."""
    if not value:
        return ''
    text = str(value).strip().lower()
    if text.startswith('sha256:'):
        text = text[7:].strip()
    text = text.replace(' ', '').replace('\r', '').replace('\n', '')
    # Allow "hex  filename" sidecar lines
    if '  ' in text or '\t' in text:
        text = re.split(r'[\s]', text, maxsplit=1)[0]
    if len(text) == 64 and _SHA256_RE.fullmatch(text):
        return text
    m = _SHA256_RE.search(str(value))
    return m.group(1).lower() if m else ''


def parse_checksum_from_text(text: str | None) -> str:
    """Extract SHA-256 from release notes / sidecar body."""
    if not text:
        return ''
    for rx in (_CHECKSUM_TAG_RE, _CHECKSUM_LINE_RE):
        m = rx.search(text)
        if m:
            return normalize_checksum(m.group(1))
    # Sidecar often is bare hex or "hex *MBT_POS_Setup.exe"
    first = text.strip().splitlines()[0] if text.strip() else ''
    return normalize_checksum(first)


def sha256_file(file_path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            h.update(chunk)
    return h.hexdigest()


class UpdateCenter:
    """Manages app version updates between cloud and desktop POS."""

    def get_latest(self) -> dict | None:
        """Return the newest active app_updates row (service role preferred)."""
        try:
            from backend.cloud_backup.supabase_client import SupabaseClient
            client = SupabaseClient()
            rows: list = []
            try:
                r = client._session.get(
                    client._url('/rest/v1/app_updates'),
                    headers=client._headers(use_service=True),
                    params={
                        'is_active': 'eq.true',
                        'select': '*',
                        'order': 'published_at.desc',
                        'limit': '1',
                    },
                    timeout=5,
                )
                if r.status_code < 400 and r.content:
                    rows = r.json() or []
            except Exception:
                rows = []
            if not rows:
                rows = client.rest_select(
                    'app_updates',
                    'is_active=eq.true&select=*&order=published_at.desc&limit=1',
                ) or []
            return rows[0] if rows else None
        except Exception as e:
            logger.debug('get_latest skipped: %s', e)
            return None

    def check_for_update(self, current_version: str) -> dict | None:
        try:
            # Prefer service role so shops can see published updates even when
            # anon RLS hides app_updates (common on locked-down portals).
            latest = self.get_latest()
            if not latest:
                return None
            if self._version_gt(latest['version'], current_version):
                return latest
            return None
        except Exception as e:
            logger.debug('Update check skipped: %s', e)
            return None

    def publish_update(self, version: str, download_url: str, checksum: str,
                       release_notes: str = '', is_mandatory: bool = False,
                       published_by: str | None = None) -> dict | None:
        checksum = normalize_checksum(checksum)
        if not checksum:
            logger.error('publish_update refused: missing/invalid checksum')
            return None
        try:
            from backend.cloud_backup.supabase_client import SupabaseClient
            client = SupabaseClient()
            row = {
                'version': version,
                'download_url': download_url,
                'checksum_sha256': checksum,
                'release_notes': release_notes,
                'is_mandatory': bool(is_mandatory),
                'is_active': True,
            }
            if published_by:
                row['published_by'] = published_by
            # Service role required — anon/authenticated RLS blocks inserts.
            r = client._session.post(
                client._url('/rest/v1/app_updates?on_conflict=version'),
                headers={
                    **client._headers(use_service=True),
                    'Prefer': 'resolution=merge-duplicates,return=representation',
                },
                json=row,
                timeout=30,
            )
            if r.status_code >= 400:
                body = r.text[:400] or f'HTTP {r.status_code}'
                if r.status_code == 400 and ('42P10' in body or 'ON CONFLICT' in body):
                    saved = self._publish_without_conflict_target(client, row)
                    if saved:
                        return saved
                raise RuntimeError(body)
            data = r.json() if r.content else None
            if isinstance(data, list):
                return data[0] if data else row
            return data or row
        except Exception as e:
            logger.error('publish_update failed: %s', e)
            return None

    def _publish_without_conflict_target(self, client, row: dict) -> dict | None:
        """Update or insert one release when version has no unique constraint."""
        version = row.get('version') or ''
        if not version:
            return None
        listed = client._session.get(
            client._url('/rest/v1/app_updates'),
            headers=client._headers(use_service=True),
            params={'version': f'eq.{version}', 'select': 'id,version'},
            timeout=30,
        )
        if listed.status_code >= 400:
            raise RuntimeError(listed.text[:400] or f'HTTP {listed.status_code}')
        existing = listed.json() if listed.content else []
        if isinstance(existing, list) and existing:
            patched = client._session.patch(
                client._url('/rest/v1/app_updates'),
                headers={
                    **client._headers(use_service=True),
                    'Prefer': 'return=representation',
                },
                params={'version': f'eq.{version}'},
                json=row,
                timeout=30,
            )
            if patched.status_code >= 400:
                raise RuntimeError(patched.text[:400] or f'HTTP {patched.status_code}')
            data = patched.json() if patched.content else None
            if isinstance(data, list):
                return data[0] if data else row
            return data or row
        created = client._session.post(
            client._url('/rest/v1/app_updates'),
            headers={
                **client._headers(use_service=True),
                'Prefer': 'return=representation',
            },
            json=row,
            timeout=30,
        )
        if created.status_code >= 400:
            raise RuntimeError(created.text[:400] or f'HTTP {created.status_code}')
        data = created.json() if created.content else None
        if isinstance(data, list):
            return data[0] if data else row
        return data or row

    def record_update_result(self, device_id: str, from_version: str, to_version: str,
                             success: bool, error: str = '', org_id: str | None = None):
        try:
            from backend.cloud_backup.supabase_client import SupabaseClient
            client = SupabaseClient()
            client.rest_insert('update_history', {
                'device_id': device_id,
                'org_id': org_id,
                'from_version': from_version,
                'to_version': to_version,
                'status': 'completed' if success else 'failed',
                'error': error,
                'completed_at': datetime.now().isoformat(),
            })
        except Exception as e:
            logger.debug('record_update_result skipped: %s', e)

    def verify_checksum(self, file_path: str, expected: str) -> bool:
        want = normalize_checksum(expected)
        if not want:
            return False
        try:
            return sha256_file(file_path) == want
        except Exception as e:
            logger.warning('verify_checksum failed: %s', e)
            return False

    @staticmethod
    def _version_gt(a: str, b: str) -> bool:
        def parts(v):
            v = str(v or '').lstrip('v').strip()
            return [int(x) for x in v.split('.') if x.isdigit()]
        pa, pb = parts(a), parts(b)
        for i in range(max(len(pa), len(pb))):
            va = pa[i] if i < len(pa) else 0
            vb = pb[i] if i < len(pb) else 0
            if va > vb:
                return True
            if va < vb:
                return False
        return False


_center: UpdateCenter | None = None


def get_update_center() -> UpdateCenter:
    global _center
    if _center is None:
        _center = UpdateCenter()
    return _center
