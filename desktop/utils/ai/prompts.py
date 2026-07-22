"""Prompt engine + domain library (JSON)."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

log = logging.getLogger('ai.prompts')

_LIBRARY: Optional[Dict[str, Any]] = None
_LIB_PATH = os.path.join(os.path.dirname(__file__), 'prompts', 'library.json')

_DOMAIN_BY_MODULE = {
    'dashboard': 'general',
    'sales': 'sales',
    'inventory': 'inventory',
    'consumption': 'inventory',
    'debt': 'customers',
    'accounting': 'accounting',
    'reports': 'reports',
    'notes': 'general',
    'settings': 'general',
    'admin': 'general',
    'security': 'general',
    'license': 'general',
    'diagnostics': 'general',
    'ai_ops': 'general',
}


def load_library(force: bool = False) -> Dict[str, Any]:
    global _LIBRARY
    if _LIBRARY is not None and not force:
        return _LIBRARY
    try:
        with open(_LIB_PATH, 'r', encoding='utf-8') as f:
            _LIBRARY = json.load(f)
    except Exception as e:
        log.warning('prompt library load failed: %s', e)
        _LIBRARY = {'domains': {'general': {
            'system': 'You are MBT AI for MBT POS. Be concise and accurate.',
            'suggestions': ['Summarize today'],
        }}}
    return _LIBRARY


def domain_for_module(module: str) -> str:
    return _DOMAIN_BY_MODULE.get((module or '').strip().lower(), 'general')


def get_domain_spec(domain: str) -> Dict[str, Any]:
    lib = load_library()
    domains = lib.get('domains') or {}
    return domains.get(domain) or domains.get('general') or {
        'system': 'You are MBT AI for MBT POS.',
        'suggestions': [],
    }


def suggested_prompts(module: str) -> List[str]:
    domain = domain_for_module(module)
    spec = get_domain_spec(domain)
    return list(spec.get('suggestions') or [])


def build_system_prompt(module: str, role: str, extra: str = '') -> str:
    domain = domain_for_module(module)
    spec = get_domain_spec(domain)
    base = str(spec.get('system') or '')
    role_line = f'Current user role: {role or "cashier"}. Honor role limits; refuse unauthorized data.'
    module_line = f'Current POS module/tab: {module or "dashboard"} (domain={domain}).'
    parts = [base, role_line, module_line]
    if extra:
        parts.append(extra)
    parts.append(
        'If you propose a mutating action (create PO, adjust stock, void sale), '
        'append a fenced JSON block: ```json\n{"type":"propose_action","action":"...","payload":{...},"summary":"..."}\n``` '
        'Do not claim the action was executed.'
    )
    parts.append(
        'Never invent, fabricate, or estimate money amounts, stock counts, '
        'receipt totals, or KPI figures that are not present in the POS context. '
        'If a number is missing, say it is unavailable — do not substitute placeholders.'
    )
    return '\n\n'.join(parts)
