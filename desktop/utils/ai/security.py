"""
AI payload security — redact secrets, sanitize I/O.

Adapted from Exam Hub `ai/security.ts` for POS (passwords, tokens, PINs, keys).
Never reveal prompts or API keys in user-facing responses.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Union

_SECRET_PATTERNS = [
    (re.compile(r'(?i)(api[_-]?key|apikey|secret|token|password|passwd|pwd|pin|bearer)\s*[:=]\s*[\'"]?[^\s\'"]+',
                re.I), r'\1=[REDACTED]'),
    (re.compile(r'(?i)sk-[a-zA-Z0-9_-]{10,}'), '[REDACTED_KEY]'),
    (re.compile(r'(?i)or-v1-[a-zA-Z0-9_-]{10,}'), '[REDACTED_KEY]'),
    (re.compile(r'(?i)Bearer\s+[A-Za-z0-9._\-+/=]+'), 'Bearer [REDACTED]'),
    (re.compile(r'(?i)eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'), '[REDACTED_JWT]'),
]

_INJECTION_PATTERNS = [
    re.compile(r'ignore\s+(all\s+)?(previous|prior|above)\s+instructions', re.I),
    re.compile(r'system\s*prompt', re.I),
    re.compile(r'you\s+are\s+now\s+', re.I),
    re.compile(r'<\s*script', re.I),
    re.compile(r'jailbreak', re.I),
]

# Keys stripped from context dicts before they reach the model
_FORBIDDEN_CONTEXT_KEYS = {
    'password', 'password_hash', 'pin', 'pin_hash', 'superadmin_pin_hash',
    'api_key', 'apikey', 'token', 'access_token', 'refresh_token', 'secret',
    'license_key', 'jwt', 'authorization', 'cloudflare_token', 'telegram_token',
    'bot_token', 'openrouter_api_key', 'openai_api_key',
}


def sanitize_user_input(text: str, max_len: int = 4000) -> str:
    s = str(text or '').strip()
    if len(s) > max_len:
        s = s[:max_len]
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
    return s


def detect_prompt_injection(text: str) -> bool:
    return any(p.search(text or '') for p in _INJECTION_PATTERNS)


def redact_secrets(text: str) -> str:
    out = str(text or '')
    for pat, repl in _SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


def sanitize_model_output(text: str, max_len: int = 20000) -> str:
    out = redact_secrets(str(text or '').strip())
    out = re.sub(r'<script[\s\S]*?>[\s\S]*?</script>', '', out, flags=re.I)
    # Never echo raw key material if model leaks it
    out = re.sub(r'(?i)openrouter[^\n]{0,40}key[^\n]{0,80}', '[redacted]', out)
    if len(out) > max_len:
        out = out[:max_len] + '\n…'
    return out


def scrub_context(obj: Any, depth: int = 0) -> Any:
    """Recursively drop forbidden keys and redact string values."""
    if depth > 8:
        return None
    if isinstance(obj, dict):
        clean: Dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in _FORBIDDEN_CONTEXT_KEYS or any(
                    x in lk for x in ('password', 'secret', 'token', 'api_key', 'pin_hash')):
                continue
            clean[k] = scrub_context(v, depth + 1)
        return clean
    if isinstance(obj, list):
        return [scrub_context(x, depth + 1) for x in obj[:50]]
    if isinstance(obj, str):
        return redact_secrets(obj)[:2000]
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    return str(obj)[:500]


def safe_error_message(exc: BaseException) -> str:
    """User-facing error — never include keys or raw provider payloads."""
    msg = redact_secrets(str(exc) or 'AI request failed')
    # Truncate long HTTP bodies
    if len(msg) > 180:
        msg = msg[:180] + '…'
    lower = msg.lower()
    if 'api key' in lower or 'unauthorized' in lower or '401' in lower:
        return 'AI service is not configured. Contact your MugoByte administrator.'
    if 'timeout' in lower or 'timed out' in lower:
        return 'AI request timed out. Try again shortly.'
    if 'connection' in lower or 'network' in lower or 'offline' in lower:
        return 'AI features temporarily unavailable (offline).'
    return msg
