"""Category tile preferences shared by the till and the dashboard.

The file is the same one the till already reads. This module does not import Qt.
"""
from __future__ import annotations

import json
import os

DEFAULTS = {
    'tile_size': 48,
    'corner_radius': 12,
    'image_fit': 'cover',
    'show_labels': True,
    'show_accent': True,
    'compact_mode': False,
    'default_placeholder': 'generic/_placeholder.svg',
}


def prefs_path() -> str:
    from mbt_paths import get_project_root
    folder = os.path.join(get_project_root(), 'config')
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, 'category_visual_prefs.json')


def load_prefs() -> dict:
    current = dict(DEFAULTS)
    path = prefs_path()
    try:
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                current.update(normalize(data, partial=True))
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return current


def save_prefs(incoming: dict) -> dict:
    current = load_prefs()
    current.update(normalize(incoming or {}, partial=False))
    path = prefs_path()
    temporary = path + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(current, handle, indent=2)
    os.replace(temporary, path)
    return current


def normalize(data: dict, *, partial: bool) -> dict:
    cleaned = {}
    if 'tile_size' in data or not partial:
        cleaned['tile_size'] = _int(data.get('tile_size', DEFAULTS['tile_size']), 'Tile size', 32, 128)
    if 'corner_radius' in data or not partial:
        cleaned['corner_radius'] = _int(
            data.get('corner_radius', DEFAULTS['corner_radius']), 'Corner radius', 0, 32)
    if 'image_fit' in data or not partial:
        fit = str(data.get('image_fit', DEFAULTS['image_fit']) or '').strip().lower()
        if fit not in ('cover', 'contain'):
            raise ValueError('Image fit must be cover or contain.')
        cleaned['image_fit'] = fit
    for key in ('show_labels', 'show_accent', 'compact_mode'):
        if key in data or not partial:
            cleaned[key] = _bool(data.get(key, DEFAULTS[key]))
    if 'default_placeholder' in data or not partial:
        cleaned['default_placeholder'] = _placeholder(
            data.get('default_placeholder', DEFAULTS['default_placeholder']))
    return cleaned


def _int(value, label: str, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be a whole number.')
    if number < low or number > high:
        raise ValueError(f'{label} must be from {low} to {high}.')
    return number


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _placeholder(value) -> str:
    text = str(value or '').strip().replace('\\', '/')
    if not text:
        return DEFAULTS['default_placeholder']
    if text.startswith('/') or '..' in text.split('/') or ':' in text:
        raise ValueError('The placeholder must be a built-in icon path.')
    if len(text) > 180:
        raise ValueError('The placeholder path is too long.')
    return text
