"""
AI Operations — health scoring (0–100).

Uses real metrics where possible (DB, disk, memory via psutil if available),
stubs for hardware that cannot be probed (printer/backup/license/AI).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from mbt_paths import get_db_path, get_data_dir, get_project_root
from desktop.utils.ai.config import is_ai_configured
from desktop.utils.ai.connectivity import get_connectivity

log = logging.getLogger('ai.ops.health')


def _try_psutil():
    try:
        import psutil
        return psutil
    except Exception:
        return None


def _check_database(db_path: str) -> Dict[str, Any]:
    t0 = time.time()
    try:
        if not os.path.isfile(db_path):
            return {'ok': False, 'score': 0, 'detail': 'Database file missing', 'ms': 0}
        size = os.path.getsize(db_path)
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            conn.execute('PRAGMA quick_check').fetchone()
            tables = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        finally:
            conn.close()
        ms = int((time.time() - t0) * 1000)
        score = 100
        if ms > 500:
            score = 70
        if ms > 2000:
            score = 40
        return {
            'ok': True, 'score': score,
            'detail': f'{tables} tables · {size/1024/1024:.1f} MB · {ms} ms',
            'ms': ms, 'size_bytes': size, 'tables': tables,
        }
    except Exception as e:
        return {'ok': False, 'score': 0, 'detail': str(e)[:120], 'ms': 0}


def _check_disk() -> Dict[str, Any]:
    root = get_project_root()
    try:
        import shutil
        usage = shutil.disk_usage(root)
        free_gb = usage.free / (1024 ** 3)
        pct_free = (usage.free / usage.total) * 100 if usage.total else 0
        score = 100
        if pct_free < 15:
            score = 55
        if pct_free < 5:
            score = 20
        return {
            'ok': pct_free >= 5, 'score': score,
            'detail': f'{free_gb:.1f} GB free ({pct_free:.0f}%)',
            'free_gb': round(free_gb, 2), 'pct_free': round(pct_free, 1),
        }
    except Exception as e:
        return {'ok': True, 'score': 80, 'detail': f'Disk check skipped: {e}', 'stub': True}


def _check_memory() -> Dict[str, Any]:
    psutil = _try_psutil()
    if not psutil:
        return {
            'ok': True, 'score': 85, 'stub': True,
            'detail': 'Memory metrics unavailable (install psutil for live stats)',
        }
    try:
        mem = psutil.virtual_memory()
        score = 100
        if mem.percent > 85:
            score = 50
        if mem.percent > 95:
            score = 25
        return {
            'ok': mem.percent < 95, 'score': score,
            'detail': f'{mem.percent:.0f}% used · {mem.available/1024/1024:.0f} MB free',
            'percent': mem.percent,
        }
    except Exception as e:
        return {'ok': True, 'score': 80, 'detail': str(e)[:100], 'stub': True}


def _check_ai() -> Dict[str, Any]:
    configured = is_ai_configured()
    if not configured:
        return {
            'ok': True, 'score': 70, 'stub': False,
            'detail': 'AI not configured (POS works offline without AI)',
            'configured': False, 'online': False,
        }
    conn = get_connectivity()
    online = bool(conn.online)
    if not online:
        # Soft recheck once
        try:
            online = conn.check_now()
        except Exception:
            online = False
    return {
        'ok': True, 'score': 100 if online else 60,
        'detail': 'AI online' if online else 'AI configured but offline',
        'configured': True, 'online': online,
    }


def _check_printer_stub(api) -> Dict[str, Any]:
    try:
        cfg = api.get_settings() if api and hasattr(api, 'get_settings') else {}
        name = (cfg or {}).get('printer_name') or (cfg or {}).get('receipt_printer') or ''
        if name:
            return {
                'ok': True, 'score': 85, 'stub': True,
                'detail': f'Configured: {name} (hardware probe not available)',
            }
        return {
            'ok': True, 'score': 75, 'stub': True,
            'detail': 'No printer name in settings (stub — cannot probe hardware)',
        }
    except Exception:
        return {'ok': True, 'score': 75, 'stub': True, 'detail': 'Printer status unknown (stub)'}


def _check_backup_stub(api) -> Dict[str, Any]:
    try:
        data = get_data_dir()
        backups = []
        for name in ('backups', 'backup'):
            p = os.path.join(data, name)
            if os.path.isdir(p):
                backups = [f for f in os.listdir(p) if f.endswith(('.db', '.zip', '.bak'))]
                break
        if backups:
            return {
                'ok': True, 'score': 90, 'stub': True,
                'detail': f'{len(backups)} backup file(s) found locally',
            }
        return {
            'ok': True, 'score': 65, 'stub': True,
            'detail': 'No local backup folder found — verify backup schedule',
        }
    except Exception as e:
        return {'ok': True, 'score': 70, 'stub': True, 'detail': str(e)[:100]}


def _check_license_stub(api) -> Dict[str, Any]:
    try:
        cfg = api.get_settings() if api and hasattr(api, 'get_settings') else {}
        # Never expose key material
        has = bool((cfg or {}).get('license_status') or (cfg or {}).get('license_valid'))
        status = str((cfg or {}).get('license_status') or 'unknown')
        return {
            'ok': True, 'score': 90 if has or status == 'active' else 80,
            'stub': True,
            'detail': f'License status: {status} (detailed probe via License tab)',
        }
    except Exception:
        return {'ok': True, 'score': 80, 'stub': True, 'detail': 'License check stub'}


def _recent_exceptions() -> Dict[str, Any]:
    """Scan recent log files for ERROR / Traceback density."""
    try:
        log_dir = os.path.join(get_project_root(), 'logs')
        if not os.path.isdir(log_dir):
            return {'ok': True, 'score': 95, 'detail': 'No logs directory', 'errors': 0}
        errors = 0
        samples: List[str] = []
        files = sorted(
            [os.path.join(log_dir, f) for f in os.listdir(log_dir)
             if f.endswith('.log') or f.endswith('.txt')],
            key=lambda p: os.path.getmtime(p), reverse=True,
        )[:3]
        for path in files:
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    # Tail ~80KB
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - 80000))
                    text = f.read()
                for line in text.splitlines():
                    if 'ERROR' in line or 'Traceback' in line:
                        errors += 1
                        if len(samples) < 5:
                            samples.append(line[:160])
            except Exception:
                continue
        score = 100
        if errors > 5:
            score = 70
        if errors > 25:
            score = 40
        if errors > 80:
            score = 20
        return {
            'ok': errors < 80, 'score': score,
            'detail': f'{errors} recent error/traceback lines',
            'errors': errors, 'samples': samples,
        }
    except Exception as e:
        return {'ok': True, 'score': 85, 'detail': str(e)[:100], 'errors': 0}


def compute_health(api=None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns overall score 0–100 plus per-check details.
    """
    db_path = db_path or get_db_path()
    checks = {
        'database': _check_database(db_path),
        'disk': _check_disk(),
        'memory': _check_memory(),
        'exceptions': _recent_exceptions(),
        'ai': _check_ai(),
        'printer': _check_printer_stub(api),
        'backup': _check_backup_stub(api),
        'license': _check_license_stub(api),
    }
    # Weighted average — DB and exceptions weigh more
    weights = {
        'database': 25,
        'exceptions': 20,
        'disk': 15,
        'memory': 10,
        'ai': 10,
        'printer': 5,
        'backup': 8,
        'license': 7,
    }
    total_w = sum(weights.values())
    score = 0.0
    for k, w in weights.items():
        score += float(checks[k].get('score', 0)) * w
    overall = int(round(score / total_w))
    alerts = []
    for name, c in checks.items():
        if not c.get('ok', True) or int(c.get('score', 100)) < 50:
            alerts.append(f"{name}: {c.get('detail', 'issue')}")
    return {
        'score': overall,
        'grade': (
            'Excellent' if overall >= 90 else
            'Good' if overall >= 75 else
            'Fair' if overall >= 55 else
            'Poor'
        ),
        'checks': checks,
        'alerts': alerts,
        'ts': time.time(),
    }
