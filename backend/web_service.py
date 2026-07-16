"""
MBT POS — Embedded Web Dashboard Service
MugoByte Technologies | mugobyte.com

Starts the Flask web dashboard in-process when the desktop app launches.
No separate CMD window or Python subprocess — runs as a daemon thread.
"""
import json
import logging
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger('web_service')

_DEFAULT_PORT = 5050
_DEFAULT_HOST = '0.0.0.0'


def _load_web_config():
    try:
        from backend.cloudflare_setup import load_web_config
        return load_web_config()
    except Exception:
        pass
    return {}


def _is_alive(port: int) -> bool:
    try:
        r = urllib.request.urlopen(
            f'http://127.0.0.1:{port}/api/health', timeout=2)
        return r.status == 200
    except Exception:
        return False


class WebDashboardService:
    """Runs Flask HTTP server in a background thread (same process as desktop)."""

    def __init__(self, host: str = _DEFAULT_HOST, port: int | None = None):
        cfg = _load_web_config()
        self.host = cfg.get('flask_host', host)
        self.port = port or int(cfg.get('flask_port', _DEFAULT_PORT))
        self._server = None
        self._thread = None
        self._tunnel = None
        self._lock = threading.Lock()
        self.running = False

    @property
    def url(self) -> str:
        return f'http://127.0.0.1:{self.port}'

    def start(self) -> bool:
        with self._lock:
            if self.running:
                return True
            if _is_alive(self.port):
                log.info('Web dashboard already running on port %s', self.port)
                self.running = True
                self._start_tunnel_if_configured()
                return True
            try:
                from backend.app import app, init_db
                init_db()
                from werkzeug.serving import make_server

                self._server = make_server(
                    self.host, self.port, app, threaded=True)
                self._thread = threading.Thread(
                    target=self._server.serve_forever,
                    name='MBT-WebDashboard',
                    daemon=True,
                )
                self._thread.start()

                for _ in range(24):
                    time.sleep(0.25)
                    if _is_alive(self.port):
                        log.info('Web dashboard live at %s', self.url)
                        self.running = True
                        self._start_tunnel_if_configured()
                        return True

                log.warning(
                    'Web dashboard thread started but health check timed out')
                self.running = True
                self._start_tunnel_if_configured()
                return True
            except OSError as e:
                if _is_alive(self.port):
                    log.info('Port %s in use — reusing existing dashboard',
                             self.port)
                    self.running = True
                    return True
                log.error('Failed to bind web dashboard port %s: %s',
                          self.port, e)
                return False
            except Exception as e:
                log.error('Failed to start web dashboard: %s', e, exc_info=True)
                return False

    def _start_tunnel_if_configured(self):
        try:
            from backend.cloudflare_setup import (
                CloudflareTunnelService, _http_check, load_web_config,
            )
            self._tunnel = CloudflareTunnelService()
            cfg = load_web_config()
            if not cfg.get('remote_enabled'):
                return
            started = self._tunnel.start()
            port = int(cfg.get('flask_port', _DEFAULT_PORT))
            local_ok, local_detail = _http_check(
                f'http://127.0.0.1:{port}/api/health')
            if local_ok:
                log.info('Local web dashboard healthy at %s', self.url)
            else:
                log.warning('Local web health check failed: %s', local_detail)
            if started:
                domain = cfg.get('tunnel_domain', '')
                if domain:
                    remote_ok, remote_detail = _http_check(
                        f'https://{domain}/api/health', timeout=12)
                    if remote_ok:
                        log.info('Remote dashboard live: https://%s', domain)
                    else:
                        log.warning(
                            'Tunnel process started but remote check failed '
                            '(%s) — DNS may still be propagating',
                            remote_detail)
                else:
                    log.warning('Remote enabled but tunnel_domain is not set')
            else:
                log.warning('Cloudflare tunnel did not start — check logs/cloudflared.log')
                try:
                    from backend.cloudflare_setup import (
                        _get_cloudflare_api_token, start_auto_cloudflare,
                    )
                    if _get_cloudflare_api_token():
                        start_auto_cloudflare()
                except Exception:
                    pass
        except Exception as e:
            log.warning('Cloudflare tunnel: %s', e)

    def stop(self):
        with self._lock:
            if self._tunnel:
                try:
                    self._tunnel.stop()
                except Exception:
                    pass
                self._tunnel = None
            if not self._server:
                self.running = False
                return
            try:
                self._server.shutdown()
            except Exception:
                pass
            self._server = None
            self._thread = None
            self.running = False
            log.info('Web dashboard stopped')
