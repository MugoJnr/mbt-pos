"""
Analyze errors with AI — root cause, severity, fix, confidence.
Role-based explanation depth. All calls via AiService.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from desktop.utils.ai.security import sanitize_user_input, redact_secrets, scrub_context
from desktop.utils.ai.service import get_ai_service
from desktop.utils.ai.connectivity import get_connectivity, OFFLINE_BANNER

log = logging.getLogger('ai.ops.analyze')


def _depth_for_role(role: str) -> str:
    r = (role or 'cashier').lower()
    if r == 'superadmin':
        return (
            'Explain at developer depth: likely module, stack interpretation, '
            'exact fix steps, and a Cursor-ready markdown prompt if useful.'
        )
    if r in ('admin', 'manager'):
        return (
            'Explain for a shop admin: clear root cause, business impact, '
            'step-by-step fix, and whether to call MugoByte support.'
        )
    return (
        'Explain simply for a cashier: what happened in plain language, '
        'what to try now, and when to call a manager. Avoid technical jargon.'
    )


def analyze_error(
    error_text: str,
    *,
    api,
    user: dict,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Returns structured analysis dict. Offline → local heuristic.
    """
    text = redact_secrets(sanitize_user_input(error_text, 6000))
    if not text:
        return {
            'root_cause': 'No error text provided',
            'severity': 'low',
            'fix': 'Paste an error message or log snippet.',
            'confidence': 0.0,
            'offline': True,
        }

    u = user.get('user') or user
    role = str(u.get('role') or 'cashier')
    conn = get_connectivity()
    conn.refresh_configured()

    if not conn.configured or not conn.online:
        return _local_analyze(text, role)

    prompt = (
        'Analyze this MBT POS error. Reply with JSON ONLY:\n'
        '{"root_cause":"...","severity":"low|medium|high|critical",'
        '"fix":"...","confidence":0.0,"steps":["..."],'
        '"developer_prompt":"...optional markdown for Cursor..."}\n'
        f'Role guidance: {_depth_for_role(role)}\n'
        f'Error:\n{text}\n'
        f'Extra context:\n{json.dumps(scrub_context(context or {}), default=str)[:3000]}'
    )
    try:
        out = get_ai_service().chat(
            user_message=prompt,
            api=api,
            user=user,
            module='diagnostics',
            history=[],
            use_stream=False,
        )
        raw = out.get('text') or ''
        m = re.search(r'\{.*\}', raw, re.S)
        data = json.loads(m.group(0)) if m else {}
        return {
            'root_cause': str(data.get('root_cause') or raw[:400]),
            'severity': str(data.get('severity') or 'medium'),
            'fix': str(data.get('fix') or ''),
            'confidence': float(data.get('confidence') or 0.6),
            'steps': list(data.get('steps') or [])[:8],
            'developer_prompt': str(data.get('developer_prompt') or '') if role == 'superadmin' else '',
            'offline': False,
            'raw': raw if not m else '',
        }
    except Exception as e:
        log.info('analyze fallback: %s', e)
        result = _local_analyze(text, role)
        result['note'] = 'AI analyze unavailable — local heuristic used.'
        return result


def _local_analyze(text: str, role: str) -> Dict[str, Any]:
    lower = text.lower()
    severity = 'medium'
    cause = 'Unrecognized error — review recent logs.'
    fix = 'Restart MBT POS, retry the action, and contact admin if it persists.'
    confidence = 0.35

    if 'permission' in lower or 'access denied' in lower:
        cause = 'Permission or role restriction blocked the action.'
        fix = 'Ask a manager/admin with the required permission, or adjust user roles.'
        severity = 'low'
        confidence = 0.7
    elif 'database' in lower or 'sqlite' in lower or 'locked' in lower:
        cause = 'Database lock or SQLite access issue.'
        fix = 'Close extra MBT POS instances, wait a few seconds, retry. Avoid killing mid-sale.'
        severity = 'high'
        confidence = 0.65
    elif 'printer' in lower:
        cause = 'Printer connectivity or driver issue.'
        fix = 'Check USB/network printer, reselect printer in Settings, print a test page.'
        severity = 'medium'
        confidence = 0.6
    elif 'license' in lower:
        cause = 'License validation problem.'
        fix = 'Open License tab; verify subscription. Contact MugoByte if still failing.'
        severity = 'high'
        confidence = 0.55
    elif 'timeout' in lower or 'connection' in lower or 'offline' in lower:
        cause = 'Network/connectivity timeout.'
        fix = 'POS works offline. Retry when internet returns; AI features need connectivity.'
        severity = 'medium'
        confidence = 0.6
    elif 'integrity' in lower or 'foreign key' in lower:
        cause = 'Data integrity / referential constraint failure.'
        fix = 'Run Business Integrity scan in AI Operations; do not delete rows manually.'
        severity = 'high'
        confidence = 0.5

    if role == 'cashier':
        fix = 'Tell your manager. Meanwhile: ' + fix

    return {
        'root_cause': cause,
        'severity': severity,
        'fix': fix,
        'confidence': confidence,
        'steps': [fix],
        'developer_prompt': '',
        'offline': True,
        'banner': OFFLINE_BANNER if not get_connectivity().online else None,
    }
