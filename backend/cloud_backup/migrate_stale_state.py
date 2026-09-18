"""
Sanitize stale cloud backup queue / state after Supabase project migrations.

Edmus-class hang: cloud_config points at the live project while
cloud_backup_state / offline queue still reference a retired host → endless
failed DNS/HTTP against the dead project.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

from backend.cloud_backup.defaults import PRODUCTION_SUPABASE_URL
from backend.cloud_backup.paths import (
    backup_state_path,
    cloud_config_path,
    load_json,
    offline_queue_path,
    save_json,
)

logger = logging.getLogger('cloud_backup.migrate_state')

# Keep in sync with paths.ensure_production_cloud_config
RETIRED_PROJECT_REFS = frozenset({'uynfglgttkaibyeglsrt'})
RETIRED_HOSTS = frozenset({'uynfglgttkaibyeglsrt.supabase.co'})

# Never probe these — they do not exist / are not client endpoints.
DEAD_OPTIONAL_HOSTS = frozenset({
    'api.mugobyte.com',
    'cloud.mugobyte.com',
    'licensing.mugobyte.com',
})


def _host_of(url_or_path: str) -> str:
    text = (url_or_path or '').strip()
    if not text:
        return ''
    if '://' not in text:
        # storage path style: business_id/device/file — no host
        if re.match(r'^[a-z0-9.-]+\.[a-z]{2,}/', text, re.I):
            return text.split('/', 1)[0].lower()
        return ''
    try:
        return (urlparse(text).hostname or '').lower()
    except Exception:
        return ''


def _ref_in_text(text: str) -> str:
    low = (text or '').lower()
    for ref in RETIRED_PROJECT_REFS:
        if ref in low:
            return ref
    return ''


def active_supabase_host() -> str:
    """Resolve active Supabase host without calling ``load_cloud_config``.

    Critical: ``load_cloud_config`` → ``ensure_production_cloud_config`` →
    ``sanitize_stale_cloud_state`` → here. Calling ``load_cloud_config`` from
    this helper recreates an infinite recursion that burns CPU, trips
    ``RecursionError`` (swallowed by ensure_production), and starves the Qt
    GIL so the POS UI appears frozen while Windows still reports Responding.
    """
    env_url = os.environ.get('MBT_SUPABASE_URL', '').strip()
    if env_url:
        host = _host_of(env_url)
        if host:
            return host
    cfg = load_json(cloud_config_path(), {}) or {}
    host = _host_of(str(cfg.get('supabase_url') or PRODUCTION_SUPABASE_URL))
    return host or _host_of(PRODUCTION_SUPABASE_URL)


def is_stale_cloud_target(text: str, *, active_host: str | None = None) -> bool:
    """True when text references a retired project or wrong Supabase host."""
    raw = text or ''
    if _ref_in_text(raw):
        return True
    host = _host_of(raw)
    if host in RETIRED_HOSTS or host in DEAD_OPTIONAL_HOSTS:
        return True
    active = (active_host or active_supabase_host() or '').lower()
    if host and host.endswith('.supabase.co') and active and host != active:
        return True
    return False


def sanitize_stale_cloud_state(*, reason: str = 'stale_project_ref') -> dict[str, Any]:
    """
    Abandon offline-queue / backup-state entries that target retired/mismatched hosts.

    Idempotent. Safe to run on every startup.
    """
    active_host = active_supabase_host()
    report: dict[str, Any] = {
        'active_host': active_host,
        'queue_abandoned': 0,
        'state_cleared': False,
        'already_clean': True,
    }

    queue = load_json(offline_queue_path(), {'items': []})
    items = list(queue.get('items') or [])
    kept = []
    dropped = 0
    for item in items:
        if not isinstance(item, dict):
            dropped += 1
            continue
        if item.get('abandoned'):
            dropped += 1
            continue
        blob = ' '.join(
            str(item.get(k) or '')
            for k in ('storage_path', 'local_enc_path', 'supabase_url', 'project_ref')
        )
        meta = item.get('meta') if isinstance(item.get('meta'), dict) else {}
        blob = f"{blob} {meta.get('supabase_url') or ''} {meta.get('project_ref') or ''}"
        if is_stale_cloud_target(blob, active_host=active_host):
            dropped += 1
            continue
        kept.append(item)

    if dropped:
        report['already_clean'] = False
        report['queue_abandoned'] = dropped
        save_json(offline_queue_path(), {'items': kept})
        logger.warning(
            'Abandoned %s stale cloud queue item(s) (%s); active host=%s',
            dropped, reason, active_host,
        )

    state = load_json(backup_state_path(), {})
    dirty = False
    for key in ('last_storage_path', 'last_error', 'last_upload_url', 'last_bucket'):
        val = str(state.get(key) or '')
        if val and is_stale_cloud_target(val, active_host=active_host):
            state[key] = ''
            dirty = True
    last_err = str(state.get('last_error') or '')
    if any(h in last_err for h in RETIRED_HOSTS) or _ref_in_text(last_err):
        state['last_error'] = f'cleared:{reason}'
        dirty = True
    if dirty:
        state['stale_project_migrated_at'] = __import__(
            'datetime'
        ).datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        state['stale_project_migration_reason'] = reason
        save_json(backup_state_path(), state)
        report['state_cleared'] = True
        report['already_clean'] = False
        logger.warning(
            'Cleared stale cloud_backup_state fields (%s); active host=%s',
            reason, active_host,
        )

    return report
