"""
MBT POS — AI Copilot preferences (layout memory).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

log = logging.getLogger('ai.copilot_prefs')

_DEFAULTS = {
    'width': 380,
    'mode': 'minimized',  # minimized | docked | floating | full
    'last_tab': 'home',
}


def _path() -> str:
    try:
        from mbt_paths import get_appdata_dir
        d = os.path.join(get_appdata_dir(), 'config')
    except Exception:
        d = os.path.join(os.environ.get('LOCALAPPDATA', '.'), 'MugoByte', 'MBT POS', 'config')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'ai_copilot_prefs.json')


def load_copilot_prefs() -> Dict[str, Any]:
    p = _path()
    data = dict(_DEFAULTS)
    try:
        if os.path.isfile(p):
            with open(p, 'r', encoding='utf-8') as f:
                data.update(json.load(f) or {})
    except Exception as e:
        log.debug('load prefs: %s', e)
    w = int(data.get('width') or 380)
    data['width'] = max(340, min(640, w))
    if data.get('mode') not in ('minimized', 'docked', 'floating', 'full'):
        data['mode'] = 'minimized'
    if data.get('last_tab') not in ('home', 'chat', 'workspace'):
        data['last_tab'] = 'home'
    return data


def save_copilot_prefs(**kwargs) -> None:
    data = load_copilot_prefs()
    data.update(kwargs)
    try:
        with open(_path(), 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.debug('save prefs: %s', e)
