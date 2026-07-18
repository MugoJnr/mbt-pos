"""
Vendor-managed AI configuration.

Key resolution order (never exposed in Settings UI for cashiers):
  1. OPENROUTER_API_KEY / MBT_OPENROUTER_API_KEY environment variable
  2. DPAPI-protected file: %LOCALAPPDATA%\\MugoByte\\MBT POS\\config\\vendor_ai.bin
  3. Plain JSON fallback for local-dev only: ...\\config\\vendor_ai.local.json
     (admin-only; gitignored pattern — see docs/AI_VENDOR_CONFIG.md)

Pattern adapted from Exam Hub `getAiConfig()` — models via env, single provider entry.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from mbt_paths import get_project_root, ensure_data_dirs

log = logging.getLogger('ai.config')

OPENROUTER_BASE = 'https://openrouter.ai/api/v1'

# Domain → default OpenRouter model (override via MBT_AI_MODEL / MBT_AI_MODEL_<DOMAIN>)
_DEFAULT_MODELS = {
    'general': 'google/gemini-2.5-flash',
    'inventory': 'google/gemini-2.5-flash',
    'sales': 'google/gemini-2.5-flash',
    'customers': 'google/gemini-2.5-flash',
    'accounting': 'google/gemini-2.5-flash',
    'reports': 'google/gemini-2.5-flash',
    'purchasing': 'google/gemini-2.5-flash',
    'forecasting': 'google/gemini-2.5-flash',
    'insights': 'google/gemini-2.5-flash',
    'actions': 'google/gemini-2.5-flash',
}


@dataclass(frozen=True)
class AiConfig:
    api_key: str
    base_url: str
    default_model: str
    site_url: str
    site_name: str
    timeout_sec: float
    max_context_chars: int
    max_tokens: int
    temperature: float
    configured: bool


def _vendor_config_dir() -> str:
    root = ensure_data_dirs(get_project_root())
    path = os.path.join(root, 'config')
    os.makedirs(path, exist_ok=True)
    return path


def vendor_ai_bin_path() -> str:
    return os.path.join(_vendor_config_dir(), 'vendor_ai.bin')


def vendor_ai_local_json_path() -> str:
    return os.path.join(_vendor_config_dir(), 'vendor_ai.local.json')


def _dpapi_protect(data: bytes) -> bytes:
    """Windows DPAPI encrypt (current user)."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    in_buf = ctypes.create_string_buffer(data)
    blob_in = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError('CryptProtectData failed')
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    in_buf = ctypes.create_string_buffer(data)
    blob_in = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError('CryptUnprotectData failed')
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def save_vendor_api_key(api_key: str) -> str:
    """
    Admin/vendor helper: store key in DPAPI-protected AppData file.
    Returns path written. Not called from cashier Settings UI.
    """
    key = (api_key or '').strip()
    if not key:
        raise ValueError('API key required')
    payload = json.dumps({'provider': 'openrouter', 'api_key': key}).encode('utf-8')
    path = vendor_ai_bin_path()
    try:
        protected = _dpapi_protect(payload)
        with open(path, 'wb') as f:
            f.write(protected)
        log.info('Vendor AI key saved (DPAPI) to config/vendor_ai.bin')
        return path
    except Exception as e:
        # Dev fallback: local JSON (still not shown in UI)
        path = vendor_ai_local_json_path()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'provider': 'openrouter', 'api_key': key}, f, indent=2)
        log.warning('DPAPI unavailable (%s); wrote vendor_ai.local.json', e)
        return path


def _read_key_from_bin() -> str:
    path = vendor_ai_bin_path()
    if not os.path.isfile(path):
        return ''
    try:
        with open(path, 'rb') as f:
            raw = f.read()
        data = json.loads(_dpapi_unprotect(raw).decode('utf-8'))
        return str(data.get('api_key') or '').strip()
    except Exception as e:
        log.warning('Could not read vendor_ai.bin: %s', e)
        return ''


def _read_key_from_local_json() -> str:
    path = vendor_ai_local_json_path()
    if not os.path.isfile(path):
        return ''
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return str(data.get('api_key') or '').strip()
    except Exception as e:
        log.warning('Could not read vendor_ai.local.json: %s', e)
        return ''


def resolve_api_key() -> str:
    for env_name in (
        'MBT_OPENROUTER_API_KEY',
        'OPENROUTER_API_KEY',
        'OPENAI_API_KEY',  # OpenRouter-compatible alias (Exam Hub pattern)
    ):
        v = (os.environ.get(env_name) or '').strip()
        if v:
            return v
    key = _read_key_from_bin()
    if key:
        return key
    return _read_key_from_local_json()


def model_for_domain(domain: str) -> str:
    d = (domain or 'general').strip().lower()
    env_specific = os.environ.get(f'MBT_AI_MODEL_{d.upper()}', '').strip()
    if env_specific:
        return env_specific
    preferred = (
        os.environ.get('MBT_AI_MODEL')
        or os.environ.get('OPENAI_MODEL')
        or os.environ.get('DEFAULT_MODEL')
        or ''
    ).strip()
    if preferred:
        return preferred
    return _DEFAULT_MODELS.get(d, _DEFAULT_MODELS['general'])


def get_ai_config() -> AiConfig:
    key = resolve_api_key()
    base = (
        os.environ.get('OPENROUTER_BASE_URL')
        or os.environ.get('OPENAI_BASE_URL')
        or OPENROUTER_BASE
    ).rstrip('/')
    return AiConfig(
        api_key=key,
        base_url=base,
        default_model=model_for_domain('general'),
        site_url=os.environ.get('MBT_SITE_URL', 'https://mugobyte.com'),
        site_name=os.environ.get('MBT_SITE_NAME', 'MBT POS'),
        timeout_sec=float(os.environ.get('MBT_AI_TIMEOUT_SEC', '45') or 45),
        max_context_chars=int(os.environ.get('MBT_AI_MAX_CONTEXT_CHARS', '10000') or 10000),
        max_tokens=int(os.environ.get('MBT_AI_MAX_TOKENS', '1600') or 1600),
        temperature=float(os.environ.get('MBT_AI_TEMPERATURE', '0.3') or 0.3),
        configured=bool(key),
    )


def is_ai_configured() -> bool:
    return bool(resolve_api_key())
