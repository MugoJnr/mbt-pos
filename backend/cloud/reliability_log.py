"""Bounded hang timings. Never store passwords, PINs, tokens, or customer rows."""
from __future__ import annotations

import os
import platform
import threading
from datetime import datetime

_LOCK = threading.Lock()
_MAX_BYTES = 512_000


def _log_dir() -> str:
    base = os.environ.get('MBT_DATA_ROOT') or os.path.join(
        os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'),
        'MugoByte', 'MBT POS',
    )
    folder = os.path.join(base, 'logs')
    os.makedirs(folder, exist_ok=True)
    return folder


def _scrub(text: str) -> str:
    kept = []
    for part in str(text or '').replace('\r', ' ').replace('\n', ' ').split():
        low = part.lower()
        if (
            'bearer' in low
            or part.startswith('eyJ')
            or 'apikey' in low
            or 'token=' in low
            or 'password' in low
            or 'pin=' in low
        ):
            kept.append('[redacted]')
            continue
        kept.append(part[:120])
    return ' '.join(kept)[:240]


def note(kind: str, op: str, duration_ms: float, status: str, detail: str = '') -> None:
    """Append one timing line. Failures here must not affect the till."""
    try:
        line = (
            f"{datetime.now().isoformat(timespec='seconds')} "
            f"kind={_scrub(kind)} op={_scrub(op)} ms={int(duration_ms)} "
            f"status={_scrub(status)} detail={_scrub(detail)}\n"
        )
        path = os.path.join(_log_dir(), 'reliability.log')
        with _LOCK:
            if os.path.isfile(path) and os.path.getsize(path) > _MAX_BYTES:
                bak = path + '.1'
                if os.path.isfile(bak):
                    os.remove(bak)
                os.replace(path, bak)
            with open(path, 'a', encoding='utf-8') as handle:
                handle.write(line)
    except Exception:
        return


def recent_lines(limit: int = 40) -> list[str]:
    path = os.path.join(_log_dir(), 'reliability.log')
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            lines = handle.readlines()
    except OSError:
        return []
    return [line.rstrip() for line in lines[-max(1, limit):]]


def _memory_note() -> str:
    try:
        import ctypes
        class _Mem(ctypes.Structure):
            _fields_ = [
                ('dwLength', ctypes.c_ulong),
                ('dwMemoryLoad', ctypes.c_ulong),
                ('ullTotalPhys', ctypes.c_ulonglong),
                ('ullAvailPhys', ctypes.c_ulonglong),
                ('ullTotalPageFile', ctypes.c_ulonglong),
                ('ullAvailPageFile', ctypes.c_ulonglong),
                ('ullTotalVirtual', ctypes.c_ulonglong),
                ('ullAvailVirtual', ctypes.c_ulonglong),
                ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
            ]
        stat = _Mem()
        stat.dwLength = ctypes.sizeof(stat)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return 'memory=unavailable'
        total = stat.ullTotalPhys / (1024 ** 3)
        avail = stat.ullAvailPhys / (1024 ** 3)
        return f"memory_load={stat.dwMemoryLoad}% total_gb={total:.1f} available_gb={avail:.1f}"
    except Exception:
        return 'memory=unavailable'


def write_support_report(dest: str | None = None) -> str:
    """Write a sanitized support file. Returns the text that was saved."""
    from backend.cloud.net_gate import network_up
    lines = [
        'MBT POS support report',
        'Save this file from Diagnostics → Export, or copy logs/support_report.txt.',
        'It does not contain passwords, PINs, or access tokens.',
        f"when={datetime.now().isoformat(timespec='seconds')}",
        f"os={platform.platform()}",
        f"python={platform.python_version()}",
        _memory_note(),
        f"network_probe={'up' if network_up(1.0) else 'down'}",
        '',
        'Recent cloud and database timings:',
    ]
    rows = recent_lines(40)
    lines.extend(rows or ['(no reliability lines yet)'])
    lines.append('')
    lines.append(
        'A hang is a software defect when a cloud call or a database lock '
        'holds the till past its timeout. A slow PC requires this report to '
        'show sustained memory pressure at the same time as the slow operation.'
    )
    text = '\n'.join(lines) + '\n'
    path = dest or os.path.join(_log_dir(), 'support_report.txt')
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
    except OSError:
        pass
    return text
