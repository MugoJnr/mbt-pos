"""AI online/offline detection with auto-reconnect polling."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, List, Optional

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
        self._listeners: List[Callable[[bool], None]] = []
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
        self._listeners.append(cb)

    def _emit(self, online: bool):
        for cb in list(self._listeners):
            try:
                cb(online)
            except Exception:
                pass

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
