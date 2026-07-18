"""Support Report — ZIP/JSON with redacted diagnostics + optional AI summary."""
from __future__ import annotations

import json
import logging
import os
import time
import zipfile
from datetime import datetime
from typing import Any, Dict, Optional

from mbt_paths import get_project_root, get_db_path, get_data_dir
from desktop.utils.ai.security import redact_secrets, scrub_context
from desktop.utils.ai.ops.health import compute_health
from desktop.utils.ai.ops.integrity import run_integrity_scan
from desktop.utils.ai.ops.config_audit import audit_config

log = logging.getLogger('ai.ops.support')


def build_support_report(
    api,
    user: dict,
    *,
    include_ai_summary: bool = True,
    out_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Writes a ZIP under Desktop/MBT POS Exports or AppData exports.
    Never includes API keys, passwords, or full DB.
    """
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    if not out_dir:
        desk = os.path.join(os.path.expanduser('~'), 'Desktop', 'MBT POS Exports')
        os.makedirs(desk, exist_ok=True)
        out_dir = desk
    zip_path = os.path.join(out_dir, f'MBT_AI_Support_{ts}.zip')

    health = compute_health(api, get_db_path())
    integrity = run_integrity_scan(get_db_path())
    config = audit_config(api, user)

    # Redacted settings snapshot
    try:
        raw_settings = api.get_settings() if hasattr(api, 'get_settings') else {}
    except Exception:
        raw_settings = {}
    settings_safe = scrub_context(raw_settings)

    u = user.get('user') or user
    meta = {
        'generated_at': datetime.now().isoformat(),
        'app': 'MBT POS',
        'user': {
            'id': u.get('id'),
            'username': u.get('username'),
            'role': u.get('role'),
        },
        'db_path_hint': os.path.basename(get_db_path()),
        'data_root_hint': get_project_root(),
    }

    ai_summary = ''
    if include_ai_summary:
        try:
            from desktop.utils.ai.service import get_ai_service
            from desktop.utils.ai.connectivity import get_connectivity
            if get_connectivity().online:
                blob = {
                    'health_score': health.get('score'),
                    'alerts': health.get('alerts'),
                    'integrity_summary': integrity.get('summary'),
                    'config_summary': config.get('summary'),
                }
                ai_summary = get_ai_service().chat(
                    user_message=(
                        'Write a short support briefing (8 bullets max) for MugoByte support '
                        'from this redacted diagnostics JSON. No secrets.\n'
                        + json.dumps(blob)[:4000]
                    ),
                    api=api, user=user, module='diagnostics',
                    history=[], use_stream=False,
                ).get('text') or ''
            else:
                ai_summary = 'AI summary unavailable (offline). Local diagnostics attached.'
        except Exception as e:
            ai_summary = f'AI summary skipped: {e}'

    payload = {
        'meta': meta,
        'health': health,
        'integrity': {
            'summary': integrity.get('summary'),
            'counts': integrity.get('counts'),
            'high_severity': integrity.get('high_severity'),
            'issues_sample': (integrity.get('issues') or [])[:40],
        },
        'config_audit': config,
        'settings_redacted': settings_safe,
        'ai_summary': redact_secrets(ai_summary),
    }

    # Collect recent log tails (redacted)
    log_snippets = {}
    log_dir = os.path.join(get_project_root(), 'logs')
    if os.path.isdir(log_dir):
        files = sorted(
            [f for f in os.listdir(log_dir) if f.endswith(('.log', '.txt'))],
            key=lambda n: os.path.getmtime(os.path.join(log_dir, n)),
            reverse=True,
        )[:3]
        for name in files:
            path = os.path.join(log_dir, name)
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - 40000))
                    log_snippets[name] = redact_secrets(f.read())
            except Exception:
                pass

    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('support_report.json', json.dumps(payload, indent=2, default=str))
            zf.writestr('ai_summary.txt', redact_secrets(ai_summary or 'N/A'))
            for name, text in log_snippets.items():
                zf.writestr(f'logs/{name}', text)
        return {'ok': True, 'path': zip_path, 'summary': ai_summary[:500]}
    except Exception as e:
        log.warning('support zip failed: %s', e)
        # Fallback JSON only
        json_path = zip_path.replace('.zip', '.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, default=str)
        return {'ok': True, 'path': json_path, 'summary': ai_summary[:500], 'note': str(e)}
