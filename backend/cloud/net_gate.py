"""
Fail-fast network probe for cloud/Supabase calls.

Windows DNS to *.supabase.co can stall 30s+ when offline — longer than
requests timeouts and sometimes process-wide. Probe raw IPs first so startup
threads never open a hostname connection while the shop has no route.
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
    """Remember a cloud failure so the next few seconds skip DNS/TLS."""
    global _NEG_UNTIL
    with _LOCK:
        _NEG_UNTIL = time.monotonic() + max(1.0, float(ttl_sec))
