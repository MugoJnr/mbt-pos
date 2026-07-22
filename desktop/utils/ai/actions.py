"""
AI Actions — propose mutations; NEVER auto-apply without confirmation + permission.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from desktop.utils.security import has_permission

log = logging.getLogger('ai.actions')

# action name → required permission
_ACTION_PERMS = {
    'create_purchase_order': 'inventory.create',  # propose-only; PO UI not shipped (V05)
    'propose_restock': 'inventory.view',
    'draft_debt_reminder': 'debt.view',
    'open_report': 'reports.view_basic',
    'navigate': None,  # UI only
}

# Actions that must never imply a working module exists
_UNIMPLEMENTED_ACTIONS = frozenset({
    'create_purchase_order',
})


@dataclass
class ProposedAction:
    action: str
    payload: Dict[str, Any] = field(default_factory=dict)
    summary: str = ''
    raw: Dict[str, Any] = field(default_factory=dict)

    def permission_ok(self, user: dict) -> bool:
        need = _ACTION_PERMS.get(self.action)
        if need is None and self.action in _ACTION_PERMS:
            return True
        if need is None:
            # Unknown actions require manager+
            return has_permission(user, 'inventory.create') or has_permission(user, 'settings.edit')
        return has_permission(user, need)


def extract_proposed_actions(assistant_text: str) -> Tuple[str, List[ProposedAction]]:
    """
    Pull fenced ```json propose_action blocks from model output.
    Returns (display_text_without_blocks, actions).
    """
    text = assistant_text or ''
    actions: List[ProposedAction] = []
    pattern = re.compile(r'```json\s*(\{.*?\})\s*```', re.S | re.I)

    def _repl(m):
        try:
            data = json.loads(m.group(1))
        except Exception:
            return m.group(0)
        if not isinstance(data, dict):
            return m.group(0)
        if data.get('type') != 'propose_action':
            return m.group(0)
        actions.append(ProposedAction(
            action=str(data.get('action') or 'unknown'),
            payload=dict(data.get('payload') or {}),
            summary=str(data.get('summary') or data.get('action') or 'Proposed action'),
            raw=data,
        ))
        return ''

    cleaned = pattern.sub(_repl, text).strip()
    # Also try bare JSON line
    if not actions:
        bare = re.search(
            r'\{[^{}]*"type"\s*:\s*"propose_action"[^{}]*\}', text, re.S)
        if bare:
            try:
                data = json.loads(bare.group(0))
                actions.append(ProposedAction(
                    action=str(data.get('action') or 'unknown'),
                    payload=dict(data.get('payload') or {}),
                    summary=str(data.get('summary') or 'Proposed action'),
                    raw=data,
                ))
                cleaned = text.replace(bare.group(0), '').strip()
            except Exception:
                pass
    return cleaned, actions


def format_action_preview(action: ProposedAction) -> str:
    lines = [f"Action: {action.action}", f"Summary: {action.summary}"]
    if action.action in _UNIMPLEMENTED_ACTIONS:
        lines.append(
            'NOTE: Purchase Orders / receiving UI is not available yet (V05). '
            'Treat this as a restock suggestion only — do not expect a PO to be created.')
    if action.payload:
        lines.append('Details:')
        for k, v in list(action.payload.items())[:12]:
            lines.append(f'  • {k}: {v}')
    return '\n'.join(lines)


def is_unimplemented_action(action: ProposedAction | str) -> bool:
    name = action.action if isinstance(action, ProposedAction) else str(action or '')
    return name in _UNIMPLEMENTED_ACTIONS
