"""
Fail-fast network probe for cloud calls.

Windows DNS to a hostname can stall far longer than a requests timeout when
the shop is offline, and that stall can freeze the till. Probe raw IPs first
so no thread opens a hostname connection while there is no route.
"""
from __future__ import annotations

import socket
import threading
import time

_LOCK = threading.Lock()
_NEG_UNTIL = 0.0
_NEG_TTL_SEC = 8.0
_PROBE_HOSTS = (('1.1.1.1', 53), ('8.8.8.8', 53))


def network_up(timeout: float = 1.0, *, force: bool = False) -> bool:
    """True when a quick IP connect succeeds. Never resolves hostnames."""
    global _NEG_UNTIL
    now = time.monotonic()
    if not force:
        with _LOCK:
            if now < _NEG_UNTIL:
                return False
    for host in _PROBE_HOSTS:
        try:
            s = socket.create_connection(host, timeout=timeout)
            s.close()
            with _LOCK:
                _NEG_UNTIL = 0.0
            return True
        except OSError:
            continue
    with _LOCK:
        _NEG_UNTIL = time.monotonic() + _NEG_TTL_SEC
    return False


def mark_network_down(ttl_sec: float = _NEG_TTL_SEC) -> None:
    """Remember a cloud failure so the next few seconds skip DNS."""
    global _NEG_UNTIL
    with _LOCK:
        _NEG_UNTIL = time.monotonic() + max(1.0, float(ttl_sec))


def bounded_timeout(timeout, *, ceiling: float = 20.0) -> float:
    """A cloud call may not wait longer than this, even if a caller asked for minutes."""
    if isinstance(timeout, (tuple, list)):
        timeout = sum(float(part) for part in timeout)
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        timeout = 8.0
    return max(2.0, min(timeout, ceiling))


def call_with_deadline(fn, timeout: float, *, label: str = 'cloud'):
    """
    Run fn and stop waiting when the deadline passes.

    Windows DNS can ignore a requests timeout. The caller returns on time.
    The abandoned call is left on a daemon thread and must not be reused.
    """
    timeout = bounded_timeout(timeout)
    box = {}

    def _run():
        try:
            box['value'] = fn()
        except BaseException as exc:
            box['error'] = exc

    worker = threading.Thread(target=_run, name=f'MBT-{label}', daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        mark_network_down(20)
        raise TimeoutError(f'{label} did not answer within {int(timeout)}s')
    if 'error' in box:
        raise box['error']
    return box.get('value')
