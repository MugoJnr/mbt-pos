"""
MBT Cloud — Update Center.
Admin uploads POS versions; desktop checks periodically and reports results.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger('cloud.updates')


class UpdateCenter:
    """Manages app version updates between cloud and desktop POS."""

    def check_for_update(self, current_version: str) -> dict | None:
        try:
            from backend.cloud_backup.supabase_client import SupabaseClient
            client = SupabaseClient()
            rows = client.rest_select(
                'app_updates',
                f'is_active=eq.true&select=*&order=published_at.desc&limit=1',
            ) or []
            if not rows:
                return None
            latest = rows[0]
            if self._version_gt(latest['version'], current_version):
                return latest
            return None
        except Exception as e:
            logger.debug('Update check skipped: %s', e)
            return None

    def publish_update(self, version: str, download_url: str, checksum: str,
                       release_notes: str = '', is_mandatory: bool = False,
                       published_by: str | None = None) -> dict | None:
        try:
            from backend.cloud_backup.supabase_client import SupabaseClient
            client = SupabaseClient()
            row = {
                'version': version,
                'download_url': download_url,
                'checksum_sha256': checksum,
                'release_notes': release_notes,
                'is_mandatory': is_mandatory,
                'published_by': published_by,
                'is_active': True,
            }
            return client.rest_insert('app_updates', row, upsert=True, on_conflict='version')
        except Exception as e:
            logger.error('publish_update failed: %s', e)
            return None

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
        h = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest() == expected

    @staticmethod
    def _version_gt(a: str, b: str) -> bool:
        def parts(v):
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
