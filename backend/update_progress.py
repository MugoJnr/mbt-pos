"""Shared Main Till update progress. The dashboard reads this file. It does not install."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone

from mbt_paths import get_data_dir


def percent_for_bytes(written, expected, *, complete: bool = False):
    """Percent from bytes actually received.

    100 is returned only when the download is finished. A known size never
    shows 100 while bytes are still arriving. An unknown size returns None.
    """
    got = max(0, int(written or 0))
    total = max(0, int(expected or 0))
    if complete:
        return 100
    if total <= 0:
        return None
    if got <= 0:
        return 0
    return min(99, (got * 100) // total)


def progress_path() -> str:
    return os.path.join(get_data_dir(), 'update_progress.json')


def write_update_progress(*, state: str, version: str = '', percent=None,
                          written: int = 0, expected: int = 0, message: str = '') -> dict:
    """Replace the status file. A failure clears the percentage."""
    if state in ('failed', 'idle'):
        percent = None
    body = {
        'kind': 'till',
        'state': state,
        'version': str(version or ''),
        'percent': None if percent is None else int(percent),
        'written': max(0, int(written or 0)),
        'expected': max(0, int(expected or 0)),
        'message': str(message or '')[:240],
        'updated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    folder = get_data_dir()
    os.makedirs(folder, exist_ok=True)
    dest = progress_path()
    handle = tempfile.NamedTemporaryFile(
        'w', encoding='utf-8', dir=folder, delete=False, suffix='.tmp',
    )
    try:
        json.dump(body, handle)
        handle.close()
        os.replace(handle.name, dest)
    finally:
        if os.path.isfile(handle.name):
            try:
                os.remove(handle.name)
            except OSError:
                pass
    return body


def read_update_progress() -> dict:
    path = progress_path()
    if not os.path.isfile(path):
        return {'kind': 'till', 'state': 'idle', 'percent': None, 'version': '', 'message': ''}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {'kind': 'till', 'state': 'idle', 'percent': None, 'version': '', 'message': ''}
    if not isinstance(data, dict):
        return {'kind': 'till', 'state': 'idle', 'percent': None, 'version': '', 'message': ''}
    if data.get('state') in ('failed', 'idle'):
        data['percent'] = None
    return data
