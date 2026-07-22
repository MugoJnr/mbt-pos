"""Dashboard AI insights — cached summary / alerts / recommendations."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from desktop.utils.ai.connectivity import get_connectivity, OFFLINE_BANNER
from desktop.utils.ai.service import get_ai_service

log = logging.getLogger('ai.insights')

_CACHE: Dict[str, Any] = {'ts': 0.0, 'data': None, 'user': ''}
_TTL = 5 * 60  # 5 minutes


def _heuristic_insights(api, user) -> Dict[str, Any]:
    """Offline / unconfigured fallback — still useful, no network."""
    alerts: List[str] = []
    recs: List[str] = []
    summary = 'Local snapshot (AI offline or not configured).'
    try:
        from datetime import date
        today = str(date.today())
        sales = api.get_sales(start=today, end=today) if hasattr(api, 'get_sales') else []
        total = sum(float(s.get('total') or s.get('final_total') or 0) for s in (sales or []))
        summary = f"Today: {len(sales or [])} sales | approx revenue {total:,.2f}."
        products = api.get_products() if hasattr(api, 'get_products') else []
        low = 0
        for p in products or []:
            try:
                qty = float(p.get('quantity') or p.get('stock') or 0)
                reorder = float(p.get('reorder_level') or p.get('min_stock') or 0)
                if reorder > 0 and qty <= reorder:
                    low += 1
            except Exception:
                pass
        if low:
            alerts.append(f'{low} product(s) at or below reorder level.')
            recs.append('Open Inventory and review low-stock items.')
        if hasattr(api, 'get_debt_summary'):
            ds = api.get_debt_summary() or {}
            overdue = ds.get('overdue_count') or ds.get('overdue') or 0
            try:
                overdue = int(overdue)
            except Exception:
                overdue = 0
            if overdue:
                alerts.append(f'{overdue} overdue credit account(s).')
                recs.append('Review Debt Management for collections.')
        if not alerts:
            alerts.append('No urgent local alerts detected.')
        if not recs:
            recs.append('Keep recording sales; refresh AI when online for deeper insights.')
    except Exception as e:
        log.debug('heuristic insights: %s', e)
        summary = 'Could not build local insights.'
    return {
        'summary': summary,
        'alerts': alerts[:5],
        'recommendations': recs[:5],
        'source': 'local',
        'offline': True,
    }


def get_dashboard_insights(api, user, *, force: bool = False) -> Dict[str, Any]:
    uid = str((user.get('user') or user).get('id') or '')
    now = time.time()
    if (
        not force
        and _CACHE.get('data')
        and _CACHE.get('user') == uid
        and (now - float(_CACHE.get('ts') or 0)) < _TTL
    ):
        return dict(_CACHE['data'])

    conn = get_connectivity()
    if not conn.configured or not conn.online:
        data = _heuristic_insights(api, user)
        if not conn.configured:
            data['banner'] = 'AI not configured - showing local insights.'
        else:
            data['banner'] = OFFLINE_BANNER
        _CACHE.update({'ts': now, 'data': data, 'user': uid})
        return data

    svc = get_ai_service()
    prompt = (
        'Based on the provided POS context, reply with a short JSON object ONLY:\n'
        '{"summary":"...","alerts":["..."],"recommendations":["..."]}\n'
        'Max 2 sentences in summary. Max 4 alerts and 4 recommendations. '
        'Use context numbers only — never invent revenue, stock, or debt figures.'
    )
    try:
        result = svc.chat(
            user_message=prompt,
            api=api,
            user=user,
            module='dashboard',
            history=[],
            stream_callback=None,
            use_stream=False,
        )
        text = (result.get('text') or '').strip()
        import json, re
        m = re.search(r'\{.*\}', text, re.S)
        parsed = json.loads(m.group(0)) if m else {}
        data = {
            'summary': str(parsed.get('summary') or text[:400]),
            'alerts': list(parsed.get('alerts') or [])[:5],
            'recommendations': list(parsed.get('recommendations') or [])[:5],
            'source': 'ai',
            'offline': False,
        }
        if not data['alerts']:
            data['alerts'] = ['No critical alerts from AI.']
        if not data['recommendations']:
            data['recommendations'] = ['Continue monitoring sales and stock.']
    except Exception as e:
        log.info('AI insights fallback: %s', e)
        data = _heuristic_insights(api, user)
        data['banner'] = 'AI insights unavailable — local snapshot shown.'

    _CACHE.update({'ts': now, 'data': data, 'user': uid})
    return data
