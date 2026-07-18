"""
Self-healing — SAFE autos only.

Allowed: clear cache, retry jobs (best-effort), refresh indexes, reconnect printer stub.
NEVER: delete/void/edit inventory/accounting/SQL without explicit approval dialog + audit.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import time
from typing import Any, Dict, List, Optional

from mbt_paths import get_data_dir, get_db_path, get_project_root, configure_sqlite_connection

log = logging.getLogger('ai.ops.healing')

SAFE_ACTIONS = {
    'clear_cache',
    'refresh_indexes',
    'reconnect_printer',
    'retry_sync_stub',
    'vacuum_analyze',  # SQLite ANALYZE only — vacuum is heavier, treat as needs approval
}

HIGH_RISK_ACTIONS = {
    'vacuum_db',
    'rebuild_stock',
    'void_sale',
    'delete_records',
    'run_sql',
    'edit_inventory',
    'edit_accounting',
}


def _audit(action: str, user: dict, detail: str, approved: bool, success: bool):
    try:
        from desktop.utils.ai.ops.knowledge import log_ops_event
        u = (user or {}).get('user') or (user or {})
        log_ops_event(
            kind='self_heal',
            title=action,
            detail=detail,
            user_id=str(u.get('id') or ''),
            username=str(u.get('username') or ''),
            meta={'approved': approved, 'success': success},
        )
    except Exception as e:
        log.debug('heal audit: %s', e)


def clear_cache() -> Dict[str, Any]:
    """Clear safe AI/app caches (not shop DB)."""
    removed = []
    data = get_data_dir()
    for name in ('cache', 'tmp', 'ai_cache'):
        path = os.path.join(data, name)
        if os.path.isdir(path):
            try:
                shutil.rmtree(path, ignore_errors=True)
                os.makedirs(path, exist_ok=True)
                removed.append(name)
            except Exception as e:
                return {'ok': False, 'action': 'clear_cache', 'error': str(e)}
    # Clear insights in-memory cache
    try:
        from desktop.utils.ai import insights as _ins
        _ins._CACHE.clear()
        removed.append('insights_memory')
    except Exception:
        pass
    return {
        'ok': True, 'action': 'clear_cache',
        'detail': f'Cleared: {", ".join(removed) or "nothing to clear"}',
    }


def refresh_indexes(db_path: Optional[str] = None) -> Dict[str, Any]:
    db_path = db_path or get_db_path()
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        configure_sqlite_connection(conn)
        try:
            conn.execute('ANALYZE')
            conn.commit()
        finally:
            conn.close()
        return {'ok': True, 'action': 'refresh_indexes', 'detail': 'SQLite ANALYZE completed'}
    except Exception as e:
        return {'ok': False, 'action': 'refresh_indexes', 'error': str(e)}


def reconnect_printer(api=None) -> Dict[str, Any]:
    """Best-effort — cannot force hardware; refresh settings path."""
    try:
        if api and hasattr(api, 'get_settings'):
            cfg = api.get_settings() or {}
            name = cfg.get('printer_name') or cfg.get('receipt_printer') or '(none)'
            return {
                'ok': True, 'action': 'reconnect_printer', 'stub': True,
                'detail': f'Reloaded printer settings ({name}). Verify a test print from Settings.',
            }
        return {
            'ok': True, 'action': 'reconnect_printer', 'stub': True,
            'detail': 'Printer reconnect stub — open Settings to reselect printer.',
        }
    except Exception as e:
        return {'ok': False, 'action': 'reconnect_printer', 'error': str(e)}


def retry_sync_stub() -> Dict[str, Any]:
    return {
        'ok': True, 'action': 'retry_sync_stub', 'stub': True,
        'detail': 'Sync retry queued (best-effort stub). Check Cloudflare/Telegram status.',
    }


def run_safe_heal(action: str, *, api=None, user: dict = None,
                  approved: bool = False) -> Dict[str, Any]:
    action = (action or '').strip().lower()
    if action in HIGH_RISK_ACTIONS:
        if not approved:
            return {
                'ok': False, 'action': action, 'needs_approval': True,
                'error': 'High-risk action requires explicit approval. Never auto-run.',
            }
        # Even with approval, v1 refuses destructive DB edits
        result = {
            'ok': False, 'action': action, 'needs_approval': False,
            'error': 'v1 refuses destructive heals (void/delete/SQL/inventory/accounting). '
                     'Use the relevant module manually.',
        }
        _audit(action, user or {}, result['error'], True, False)
        return result

    if action not in SAFE_ACTIONS and action != 'vacuum_analyze':
        return {'ok': False, 'action': action, 'error': f'Unknown heal action: {action}'}

    if action == 'clear_cache':
        result = clear_cache()
    elif action in ('refresh_indexes', 'vacuum_analyze'):
        result = refresh_indexes()
    elif action == 'reconnect_printer':
        result = reconnect_printer(api)
    elif action == 'retry_sync_stub':
        result = retry_sync_stub()
    else:
        result = {'ok': False, 'action': action, 'error': 'Not implemented'}

    _audit(action, user or {}, result.get('detail') or result.get('error') or '', False, result.get('ok', False))
    return result


def list_safe_actions() -> List[Dict[str, str]]:
    return [
        {'id': 'clear_cache', 'label': 'Clear cache', 'risk': 'safe'},
        {'id': 'refresh_indexes', 'label': 'Refresh DB indexes (ANALYZE)', 'risk': 'safe'},
        {'id': 'reconnect_printer', 'label': 'Reconnect printer (best-effort)', 'risk': 'safe'},
        {'id': 'retry_sync_stub', 'label': 'Retry sync jobs', 'risk': 'safe'},
    ]
