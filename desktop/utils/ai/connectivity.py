"""AI online/offline detection with auto-reconnect polling."""
from __future__ import annotations

import inspect
import logging
import threading
import time
import weakref
from typing import Any, Callable, List, Optional

import requests

from desktop.utils.ai.config import get_ai_config, is_ai_configured

log = logging.getLogger('ai.connectivity')

OFFLINE_BANNER = 'AI features temporarily unavailable'


class AiConnectivity:
    """
    Tracks whether AI can reach the network.
    POS continues normally when offline — AI degrades gracefully.
    """

    def __init__(self):
        self._online = True
        self._configured = is_ai_configured()
        self._lock = threading.Lock()
        self._listeners: List[Any] = []
        self._listeners_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_check = 0.0

    @property
    def online(self) -> bool:
        with self._lock:
            return self._online and self._configured

    @property
    def configured(self) -> bool:
        with self._lock:
            return self._configured

    def refresh_configured(self):
        with self._lock:
            self._configured = is_ai_configured()

    def subscribe(self, cb: Callable[[bool], None]):
        """Register a connectivity listener.

        Bound methods are held weakly. This object is a process-wide singleton
        with a polling thread behind it, so a strong reference would keep a
        subscribed widget alive past its window and then call back into it
        after Qt destroyed the underlying C++ object.
        """
        ref: Any = weakref.WeakMethod(cb) if inspect.ismethod(cb) else cb
        with self._listeners_lock:
            self._listeners.append(ref)

    def unsubscribe(self, cb: Callable[[bool], None]):
        """Drop a listener registered through :meth:`subscribe`."""
        with self._listeners_lock:
            self._listeners = [
                ref for ref in self._listeners
                if self._deref(ref) not in (None, cb)
            ]

    @staticmethod
    def _deref(ref: Any) -> Optional[Callable[[bool], None]]:
        return ref() if isinstance(ref, weakref.ref) else ref

    def _live_listeners(self) -> List[Callable[[bool], None]]:
        live: List[Callable[[bool], None]] = []
        with self._listeners_lock:
            kept: List[Any] = []
            for ref in self._listeners:
                cb = self._deref(ref)
                if cb is None:
                    continue
                kept.append(ref)
                live.append(cb)
            self._listeners = kept
        return live

    def _emit(self, online: bool):
        for cb in self._live_listeners():
            try:
                cb(online)
            except Exception:
                log.debug('connectivity listener failed', exc_info=True)

    def check_now(self) -> bool:
        self.refresh_configured()
        if not self._configured:
            with self._lock:
                prev = self._online
                self._online = False
            if prev:
                self._emit(False)
            return False
        cfg = get_ai_config()
        ok = False
        try:
            # Lightweight reachability — HEAD/GET openrouter root or models
            url = f'{cfg.base_url}/models'
            r = requests.get(
                url,
                headers={'Authorization': f'Bearer {cfg.api_key}'},
                timeout=6,
            )
            ok = r.status_code < 500
        except Exception:
            ok = False
        with self._lock:
            prev = self._online
            self._online = ok
            self._last_check = time.time()
        if prev != ok:
            log.info('AI connectivity -> %s', 'online' if ok else 'offline')
            self._emit(ok)
        return ok

    def start_watch(self, interval_sec: float = 45.0):
        if self._thread and self._thread.is_alive():
            return

        def _loop():
            while not self._stop.wait(interval_sec):
                try:
                    self.check_now()
                except Exception as e:
                    log.debug('ai watch: %s', e)

        self._stop.clear()
        self._thread = threading.Thread(target=_loop, name='mbt-ai-watch', daemon=True)
        self._thread.start()
        # Immediate check in background
        threading.Thread(target=self.check_now, name='mbt-ai-check', daemon=True).start()

    def stop_watch(self):
        self._stop.set()


_CONN: Optional[AiConnectivity] = None


def get_connectivity() -> AiConnectivity:
    global _CONN
    if _CONN is None:
        _CONN = AiConnectivity()
    return _CONN
