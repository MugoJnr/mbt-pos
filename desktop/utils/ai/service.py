"""
Central AI gateway — the only entry point application code should use.

Adapted from Exam Hub `ai/service.ts`: config → provider → sanitize → usage log.
Retries transient failures. Never exposes API keys.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from desktop.utils.ai.actions import extract_proposed_actions
from desktop.utils.ai.config import get_ai_config, model_for_domain, is_ai_configured
from desktop.utils.ai.connectivity import get_connectivity, OFFLINE_BANNER
from desktop.utils.ai.context import build_context
from desktop.utils.ai.conversations import get_conversation_store
from desktop.utils.ai.prompts import build_system_prompt, domain_for_module, suggested_prompts
from desktop.utils.ai.provider_openrouter import openrouter_chat, OpenRouterError, CompletionResult
from desktop.utils.ai.security import (
    sanitize_user_input, sanitize_model_output, detect_prompt_injection,
    safe_error_message, scrub_context,
)
from desktop.utils.ai.usage import log_usage

log = logging.getLogger('ai.service')

_MAX_RETRIES = 2


class AiService:
    def __init__(self):
        self.store = get_conversation_store()

    def status(self) -> Dict[str, Any]:
        conn = get_connectivity()
        cfg = get_ai_config()
        return {
            'configured': cfg.configured,
            'online': conn.online,
            'banner': None if conn.online else (
                'AI not configured — contact administrator.' if not cfg.configured
                else OFFLINE_BANNER
            ),
            'model': cfg.default_model if cfg.configured else '',
        }

    def suggestions(self, module: str) -> List[str]:
        return suggested_prompts(module)

    def chat(
        self,
        *,
        user_message: str,
        api,
        user: dict,
        module: str = 'dashboard',
        history: Optional[List[Dict[str, str]]] = None,
        conversation_id: Optional[str] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        use_stream: bool = True,
    ) -> Dict[str, Any]:
        """
        Returns dict:
          text, actions, conversation_id, request_id, offline, error, usage...
        """
        u = user.get('user') or user
        user_id = str(u.get('id') or u.get('username') or 'anon')
        username = str(u.get('username') or '')
        role = str(u.get('role') or 'cashier')
        module = (module or 'dashboard').lower()
        domain = domain_for_module(module)

        text_in = sanitize_user_input(user_message)
        if not text_in:
            return {'text': 'Please enter a question.', 'actions': [], 'error': 'empty'}

        if detect_prompt_injection(text_in):
            return {
                'text': 'That request looks unsafe. Please rephrase your question about the shop.',
                'actions': [],
                'error': 'injection',
            }

        # Ensure conversation
        cid = conversation_id
        if not cid:
            cid = self.store.create(user_id, module=module)
        self.store.add_message(cid, 'user', text_in)

        conn = get_connectivity()
        conn.refresh_configured()
        if not is_ai_configured():
            msg = (
                'AI is not configured on this installation. '
                'Ask your MugoByte administrator to set the vendor key '
                '(see docs/AI_VENDOR_CONFIG.md). POS works normally without AI.'
            )
            self.store.add_message(cid, 'assistant', msg)
            return {
                'text': msg, 'actions': [], 'conversation_id': cid,
                'offline': True, 'error': 'not_configured',
            }

        # Soft online check — if recently offline, try once
        if not conn.online:
            conn.check_now()
        if not conn.online:
            msg = OFFLINE_BANNER + '. Your question was saved; try again when online.'
            self.store.add_message(cid, 'assistant', msg)
            return {
                'text': msg, 'actions': [], 'conversation_id': cid,
                'offline': True, 'error': 'offline',
            }

        cfg = get_ai_config()
        ctx = build_context(api, user, module, max_chars=cfg.max_context_chars)
        system = build_system_prompt(module, role)
        messages: List[Dict[str, str]] = [
            {'role': 'system', 'content': system},
            {
                'role': 'system',
                'content': 'POS context (permission-filtered JSON):\n'
                           + json.dumps(scrub_context(ctx), default=str)[:cfg.max_context_chars],
            },
        ]
        for h in (history or [])[-12:]:
            role_h = h.get('role')
            content_h = sanitize_user_input(h.get('content') or '', 2000)
            if role_h in ('user', 'assistant') and content_h:
                messages.append({'role': role_h, 'content': content_h})
        messages.append({'role': 'user', 'content': text_in})

        model = model_for_domain(domain)
        last_err: Optional[BaseException] = None
        result: Optional[CompletionResult] = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                result = openrouter_chat(
                    messages,
                    model=model,
                    cfg=cfg,
                    stream_callback=stream_callback if use_stream else None,
                )
                break
            except OpenRouterError as e:
                last_err = e
                if e.status in (503, 504, 429) and attempt < _MAX_RETRIES:
                    time.sleep(0.6 * (attempt + 1))
                    continue
                break
            except Exception as e:
                last_err = e
                break

        if result is None:
            err = safe_error_message(last_err or Exception('AI failed'))
            if last_err and 'connection' in str(last_err).lower():
                get_connectivity().check_now()
            log_usage(
                user_id=user_id, username=username, module=module, domain=domain,
                model=model, success=False, error=str(last_err)[:300],
            )
            self.store.add_message(cid, 'assistant', err)
            return {
                'text': err, 'actions': [], 'conversation_id': cid,
                'offline': True, 'error': 'provider',
            }

        raw_text = sanitize_model_output(result.text)
        display, actions = extract_proposed_actions(raw_text)
        if not display:
            display = raw_text or 'No response.'

        self.store.add_message(
            cid, 'assistant', display,
            meta={'actions': [a.raw for a in actions], 'request_id': result.request_id},
        )
        log_usage(
            request_id=result.request_id,
            user_id=user_id,
            username=username,
            module=module,
            domain=domain,
            model=result.model,
            provider=result.provider,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            latency_ms=result.latency_ms,
            estimated_cost_usd=result.estimated_cost_usd,
            success=True,
        )
        return {
            'text': display,
            'actions': actions,
            'conversation_id': cid,
            'request_id': result.request_id,
            'model': result.model,
            'usage': {
                'prompt_tokens': result.prompt_tokens,
                'completion_tokens': result.completion_tokens,
                'total_tokens': result.total_tokens,
                'latency_ms': result.latency_ms,
            },
            'offline': False,
            'error': '',
        }

    def summarize_report(self, api, user, report_blob: Dict[str, Any]) -> str:
        """Optional AI summary for Reports tab."""
        status = self.status()
        if not status['online']:
            return status['banner'] or OFFLINE_BANNER
        prompt = (
            'Summarize this POS report for a shop manager in 5 short bullets. '
            'Use only provided figures.\n'
            + json.dumps(scrub_context(report_blob), default=str)[:8000]
        )
        out = self.chat(
            user_message=prompt, api=api, user=user, module='reports',
            history=[], use_stream=False,
        )
        return out.get('text') or 'No summary.'


_SVC: Optional[AiService] = None


def get_ai_service() -> AiService:
    global _SVC
    if _SVC is None:
        _SVC = AiService()
    return _SVC
