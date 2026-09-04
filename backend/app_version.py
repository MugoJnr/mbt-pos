"""Resolve and stamp the installed MBT POS version.

Keeps LocalAppData ``installed_version.json`` aligned with the running binary
after install/update, and provides a single resolver for cloud heartbeats so
``devices.mbt_version`` is never left as ``unknown`` when a real version exists.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger('mbt.app_version')


def brand_data_root() -> str:
    base = (
        os.environ.get('LOCALAPPDATA')
        or os.environ.get('APPDATA')
        or os.path.expanduser('~')
    )
    return os.path.join(base, 'MugoByte', 'MBT POS')


def installed_version_path() -> str:
    return os.path.join(brand_data_root(), 'installed_version.json')


def _project_root() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_version_json() -> str:
    roots = [_project_root()]
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        roots.insert(0, meipass)
    for root in roots:
        path = os.path.join(root, 'version.json')
        try:
            with open(path, encoding='utf-8-sig') as f:
                ver = str(json.load(f).get('version') or '').strip()
            if ver:
                return ver.lstrip('v')
        except Exception:
            continue
    return ''


def resolve_app_version(fallback: str = '') -> str:
    """Best-effort version string for heartbeats and UI stamps."""
    candidates: list[str] = []
    try:
        from desktop.main import APP_VERSION
        candidates.append(str(APP_VERSION or '').strip())
    except Exception:
        pass
    try:
        from backend.app import APP_VERSION as BACKEND_VERSION
        candidates.append(str(BACKEND_VERSION or '').strip())
    except Exception:
        pass
    candidates.append(read_version_json())
    if fallback:
        candidates.append(str(fallback).strip())
    for raw in candidates:
        ver = (raw or '').lstrip('v').strip()
        if ver and ver.lower() not in ('unknown', '0', 'none'):
            return ver
    return (fallback or 'unknown').lstrip('v') or 'unknown'


def write_installed_version_stamp(
    version: str = '',
    *,
    exe_path: str = '',
    checksum_sha256: str = '',
    build: str = '',
    released: str = '',
) -> dict[str, Any]:
    """Write ``%LOCALAPPDATA%\\MugoByte\\MBT POS\\installed_version.json``."""
    ver = resolve_app_version(version)
    if not exe_path:
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = os.path.join(
                os.environ.get('ProgramFiles', r'C:\Program Files'),
                'MugoByte',
                'MBT POS',
                'MBT_POS.exe',
            )
    payload = {
        'version': ver,
        'build': build or ver,
        'released': released or datetime.now(timezone.utc).date().isoformat(),
        'path': exe_path,
        'checksum_sha256': checksum_sha256 or '',
        'stamped_at': datetime.now(timezone.utc).isoformat(),
    }
    path = installed_version_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
            f.write('\n')
        logger.info('Wrote installed_version.json v%s', ver)
    except Exception as e:
        logger.warning('Could not write installed_version.json: %s', e)
    return payload


def ensure_installed_version_stamp(running_version: str = '') -> dict[str, Any] | None:
    """Refresh the stamp when missing or stale vs the running binary."""
    ver = resolve_app_version(running_version)
    if not ver or ver.lower() == 'unknown':
        return None
    path = installed_version_path()
    current = ''
    try:
        with open(path, encoding='utf-8-sig') as f:
            current = str(json.load(f).get('version') or '').strip().lstrip('v')
    except Exception:
        current = ''
    if current == ver:
        return None
    return write_installed_version_stamp(ver)
