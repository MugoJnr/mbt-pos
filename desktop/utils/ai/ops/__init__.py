"""
AI Operations facade — single entry for the Ops Center UI.
All AI calls go through AiService; never OpenRouter from UI.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from desktop.utils.ai.ops.health import compute_health
from desktop.utils.ai.ops.integrity import run_integrity_scan
from desktop.utils.ai.ops.config_audit import audit_config
from desktop.utils.ai.ops.healing import run_safe_heal, list_safe_actions, HIGH_RISK_ACTIONS
from desktop.utils.ai.ops.analyze import analyze_error
from desktop.utils.ai.ops.support_report import build_support_report
from desktop.utils.ai.ops.update_verify import run_update_verification
from desktop.utils.ai.ops import knowledge as kb
from desktop.utils.ai.connectivity import get_connectivity, OFFLINE_BANNER
from desktop.utils.ai.service import get_ai_service


class AiOpsService:
    def health(self, api, db_path=None) -> Dict[str, Any]:
        return compute_health(api, db_path)

    def integrity(self, db_path=None) -> Dict[str, Any]:
        return run_integrity_scan(db_path)

    def config_audit(self, api, user=None) -> Dict[str, Any]:
        return audit_config(api, user)

    def analyze(self, error_text: str, api, user, context=None) -> Dict[str, Any]:
        return analyze_error(error_text, api=api, user=user, context=context)

    def heal(self, action: str, api=None, user=None, approved: bool = False) -> Dict[str, Any]:
        return run_safe_heal(action, api=api, user=user, approved=approved)

    def safe_actions(self):
        return list_safe_actions()

    def high_risk_actions(self):
        return sorted(HIGH_RISK_ACTIONS)

    def support_zip(self, api, user, include_ai_summary=True) -> Dict[str, Any]:
        return build_support_report(api, user, include_ai_summary=include_ai_summary)

    def verify_update(self, api=None, db_path=None) -> Dict[str, Any]:
        return run_update_verification(api, db_path)

    def kb_list(self, search=''):
        return kb.list_knowledge(search)

    def kb_add(self, title, symptoms, resolution, tags='', created_by=''):
        return kb.add_knowledge(title, symptoms, resolution, tags=tags, created_by=created_by)

    def kb_delete(self, kid: str) -> bool:
        return kb.delete_knowledge(kid)

    def events(self, limit=40):
        return kb.recent_events(limit)

    def ai_status(self) -> Dict[str, Any]:
        return get_ai_service().status()

    def performance_snapshot(self, api=None) -> Dict[str, Any]:
        """Lightweight performance analyzer (DB latency + health bits)."""
        h = compute_health(api)
        db = (h.get('checks') or {}).get('database') or {}
        mem = (h.get('checks') or {}).get('memory') or {}
        tips = []
        if int(db.get('ms') or 0) > 400:
            tips.append('Database responds slowly — run Refresh indexes (ANALYZE).')
        if mem.get('percent') and float(mem['percent']) > 85:
            tips.append('High memory use — close unused apps; clear cache.')
        if not tips:
            tips.append('No major performance issues detected.')
        return {
            'db_ms': db.get('ms'),
            'memory': mem.get('detail'),
            'tips': tips,
            'health_score': h.get('score'),
        }

    def developer_prompt(self, topic: str, api, user) -> str:
        """Superadmin-only helper — generates Cursor-ready markdown via AiService."""
        st = self.ai_status()
        if not st.get('online'):
            return (
                f'# MBT POS Developer Prompt\n\n'
                f'Topic: {topic}\n\n'
                f'{OFFLINE_BANNER}. Paste logs manually into Cursor.\n'
            )
        out = get_ai_service().chat(
            user_message=(
                'Generate a Cursor agent markdown prompt to fix this MBT POS issue. '
                'Include workspace path hint extracted/mbt_pos, constraints '
                '(no auto-void, preserve accounting 2.3.75+, offline-first), '
                f'and acceptance checks.\n\nTopic:\n{topic}'
            ),
            api=api, user=user, module='diagnostics',
            history=[], use_stream=False,
        )
        return out.get('text') or ''


_OPS: Optional[AiOpsService] = None


def get_ai_ops() -> AiOpsService:
    global _OPS
    if _OPS is None:
        _OPS = AiOpsService()
    return _OPS
