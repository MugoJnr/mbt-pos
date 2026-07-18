"""
OpenRouter HTTP provider — THE ONLY module that talks to OpenRouter.

Adapted from Exam Hub `providers/openrouter.ts`.
All other POS code must go through AiService.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import requests

from desktop.utils.ai.config import AiConfig, get_ai_config

log = logging.getLogger('ai.provider')

# Rough USD / 1M tokens for usage monitor only (Exam Hub pattern)
_COST_PER_M = {
    'default': (0.15, 0.60),
    'claude': (3.0, 15.0),
    'gpt': (2.5, 10.0),
    'gemini': (0.15, 0.60),
}


@dataclass
class CompletionResult:
    text: str
    model: str
    provider: str = 'openrouter'
    request_id: str = ''
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0
    cached: bool = False
    error: str = ''


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = _COST_PER_M['default']
    ml = (model or '').lower()
    for key, pair in _COST_PER_M.items():
        if key != 'default' and key in ml:
            rates = pair
            break
    return (prompt_tokens * rates[0] + completion_tokens * rates[1]) / 1_000_000


class OpenRouterError(Exception):
    def __init__(self, message: str, status: int = 502, request_id: str = ''):
        super().__init__(message)
        self.status = status
        self.request_id = request_id


def openrouter_chat(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    cfg: Optional[AiConfig] = None,
    stream_callback: Optional[Callable[[str], None]] = None,
) -> CompletionResult:
    """
    Chat completion via OpenRouter.
    If stream_callback is set, uses SSE streaming and invokes callback per delta.
    """
    cfg = cfg or get_ai_config()
    if not cfg.api_key:
        raise OpenRouterError('OPENROUTER_API_KEY is not configured', status=503)

    request_id = str(uuid.uuid4())
    use_model = model or cfg.default_model
    url = f'{cfg.base_url}/chat/completions'
    headers = {
        'Authorization': f'Bearer {cfg.api_key}',
        'Content-Type': 'application/json',
        'HTTP-Referer': cfg.site_url,
        'X-Title': cfg.site_name,
    }
    body: Dict[str, Any] = {
        'model': use_model,
        'messages': messages,
        'temperature': cfg.temperature if temperature is None else temperature,
        'max_tokens': cfg.max_tokens if max_tokens is None else max_tokens,
    }

    started = time.time()
    if stream_callback:
        body['stream'] = True
        return _chat_stream(url, headers, body, use_model, request_id, started,
                            stream_callback, cfg.timeout_sec)

    try:
        res = requests.post(url, headers=headers, json=body, timeout=cfg.timeout_sec)
    except requests.Timeout as e:
        raise OpenRouterError(f'timeout: {e}', status=504, request_id=request_id) from e
    except requests.RequestException as e:
        raise OpenRouterError(f'connection: {e}', status=503, request_id=request_id) from e

    latency = int((time.time() - started) * 1000)
    if res.status_code >= 400:
        # Never log raw body with potential key echoes at info level
        raise OpenRouterError(
            f'OpenRouter HTTP {res.status_code}',
            status=502, request_id=request_id)

    data = res.json()
    choice = (data.get('choices') or [{}])[0]
    text = ((choice.get('message') or {}).get('content') or '').strip()
    usage = data.get('usage') or {}
    pt = int(usage.get('prompt_tokens') or 0)
    ct = int(usage.get('completion_tokens') or 0)
    tt = int(usage.get('total_tokens') or (pt + ct))
    used_model = data.get('model') or use_model
    return CompletionResult(
        text=text,
        model=used_model,
        request_id=request_id,
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
        latency_ms=latency,
        estimated_cost_usd=_estimate_cost(used_model, pt, ct),
    )


def _chat_stream(
    url, headers, body, use_model, request_id, started, callback, timeout_sec
) -> CompletionResult:
    parts: List[str] = []
    try:
        with requests.post(url, headers=headers, json=body, timeout=timeout_sec,
                           stream=True) as res:
            if res.status_code >= 400:
                raise OpenRouterError(
                    f'OpenRouter HTTP {res.status_code}',
                    status=502, request_id=request_id)
            for raw in res.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                line = raw.strip()
                if not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if payload == '[DONE]':
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = ((chunk.get('choices') or [{}])[0].get('delta') or {})
                piece = delta.get('content') or ''
                if piece:
                    parts.append(piece)
                    try:
                        callback(piece)
                    except Exception:
                        pass
    except OpenRouterError:
        raise
    except requests.Timeout as e:
        raise OpenRouterError(f'timeout: {e}', status=504, request_id=request_id) from e
    except requests.RequestException as e:
        raise OpenRouterError(f'connection: {e}', status=503, request_id=request_id) from e

    text = ''.join(parts).strip()
    # Approximate tokens when stream usage missing
    approx = max(1, len(text) // 4)
    latency = int((time.time() - started) * 1000)
    return CompletionResult(
        text=text,
        model=use_model,
        request_id=request_id,
        prompt_tokens=0,
        completion_tokens=approx,
        total_tokens=approx,
        latency_ms=latency,
        estimated_cost_usd=_estimate_cost(use_model, 0, approx),
    )
