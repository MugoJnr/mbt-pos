"""
MBT POS — Unified Telegram update hub
MugoByte Technologies | mugobyte.com

Telegram allows only ONE active getUpdates consumer per bot token.
This module is the single poller for the whole app (admin commands,
license push packets, and short-lived "connect" capture windows).
"""
import json
import logging
import os
import threading
import time
from typing import Callable, Optional

import requests

logger = logging.getLogger('telegram_hub')

POLL_TIMEOUT = 20
RETRY_DELAY = 5

_hub_lock = threading.Lock()
_hub_instance: Optional['TelegramHub'] = None


def _offset_path() -> str:
    base = os.path.join(os.environ.get('APPDATA', ''), 'MugoByte', '.mbt_lic')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'tg_offset.json')


def resolve_bot_token(cfg: dict | None = None) -> str:
    """Bot token from settings, then build-time deploy defaults."""
    cfg = cfg or {}
    tok = (cfg.get('telegram_bot_token') or '').strip()
    if tok:
        return tok
    try:
        from config.deploy import load_deploy_config
        return (load_deploy_config().get('telegram_bot_token') or '').strip()
    except Exception:
        pass
    # Last resort when config.deploy is missing from a bad installer build
    try:
        from config.deploy import _DEFAULT_BOT  # type: ignore[attr-defined]
        return (_DEFAULT_BOT or '').strip()
    except Exception:
        return ''


def resolve_bot_username(cfg: dict | None = None) -> str:
    cfg = cfg or {}
    try:
        from config.deploy import load_deploy_config
        d = load_deploy_config()
        return (d.get('telegram_bot_username') or 'mbt_admin1_bot').lstrip('@')
    except Exception:
        return 'mbt_admin1_bot'


def get_hub() -> Optional['TelegramHub']:
    with _hub_lock:
        return _hub_instance


def start_hub(config_getter: Callable) -> 'TelegramHub':
    global _hub_instance
    with _hub_lock:
        if _hub_instance is None:
            _hub_instance = TelegramHub(config_getter)
            _hub_instance.start()
        else:
            _hub_instance.config_getter = config_getter
        return _hub_instance


def stop_hub():
    global _hub_instance
    with _hub_lock:
        if _hub_instance:
            _hub_instance.stop()
            _hub_instance = None


class TelegramHub(threading.Thread):
    """Single long-poll thread for all Telegram inbound traffic."""

    def __init__(self, config_getter: Callable):
        super().__init__(daemon=True, name='TelegramHub')
        self.config_getter = config_getter
        self._stop = threading.Event()
        self._session = requests.Session()
        self._offset = 0
        self._offset_lock = threading.Lock()
        self._load_offset()

        self._admin_handler: Optional[Callable] = None
        self._license_push_handler: Optional[Callable] = None

        self._capture_lock = threading.Lock()
        self._capture_cb: Optional[Callable[[dict], bool]] = None
        self._capture_until = 0.0

    def set_admin_handler(self, handler: Callable):
        """handler(update: dict, reply_fn: Callable[[str], None]) -> None"""
        self._admin_handler = handler

    def set_license_push_handler(self, handler: Callable):
        """handler(text: str) -> None — for __LICPUSH__ / __LICEXTEND__ / __LICREVOKE__"""
        self._license_push_handler = handler

    def begin_capture(self, on_update: Callable[[dict], bool], timeout_sec: float = 180):
        """
        Temporarily capture inbound messages (connect flow, activation key wait).
        on_update returns True when capture is complete.
        """
        with self._capture_lock:
            self._capture_cb = on_update
            self._capture_until = time.time() + timeout_sec

    def end_capture(self):
        with self._capture_lock:
            self._capture_cb = None
            self._capture_until = 0.0

    def stop(self):
        self._stop.set()
        self.end_capture()

    def _load_offset(self):
        try:
            with open(_offset_path(), encoding='utf-8') as f:
                self._offset = int(json.load(f).get('offset', 0))
        except Exception:
            self._offset = 0

    def _save_offset(self):
        try:
            with open(_offset_path(), 'w', encoding='utf-8') as f:
                json.dump({'offset': self._offset}, f)
        except Exception as e:
            logger.warning(f'Could not save Telegram offset: {e}')

    def _advance_offset_past_backlog(self, token: str):
        """Skip old messages so connect/activation only sees NEW traffic."""
        api = f'https://api.telegram.org/bot{token}'
        try:
            r = self._session.get(
                f'{api}/getUpdates',
                params={'timeout': 1, 'limit': 100, 'offset': self._offset},
                timeout=8,
            )
            if r.ok:
                updates = r.json().get('result', [])
                if updates:
                    with self._offset_lock:
                        self._offset = updates[-1]['update_id'] + 1
                        self._save_offset()
        except Exception as e:
            logger.debug(f'Backlog skip: {e}')

    def run(self):
        logger.info('Telegram hub started')
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception as e:
                logger.warning(f'Telegram hub poll error: {e}')
                self._stop.wait(RETRY_DELAY)

    def _poll_once(self):
        cfg = self.config_getter() or {}
        token = resolve_bot_token(cfg)
        if not token:
            self._stop.wait(30)
            return

        api = f'https://api.telegram.org/bot{token}'
        with self._offset_lock:
            offset = self._offset

        try:
            r = self._session.get(
                f'{api}/getUpdates',
                params={
                    'timeout': POLL_TIMEOUT,
                    'offset': offset,
                    'allowed_updates': ['message'],
                },
                timeout=POLL_TIMEOUT + 10,
            )
        except requests.exceptions.Timeout:
            return
        except Exception as e:
            logger.warning(f'getUpdates error: {e}')
            self._stop.wait(RETRY_DELAY)
            return

        if not r.ok:
            self._stop.wait(RETRY_DELAY)
            return

        for upd in r.json().get('result', []):
            with self._offset_lock:
                self._offset = max(self._offset, upd.get('update_id', 0) + 1)
                self._save_offset()
            self._dispatch(upd, api)

    def _dispatch(self, upd: dict, api: str):
        msg = upd.get('message', {})
        chat_id = msg.get('chat', {}).get('id')
        text = (msg.get('text') or '').strip()
        if not chat_id:
            return

        def reply_fn(body: str):
            if not body:
                return
            try:
                self._session.post(
                    f'{api}/sendMessage',
                    json={'chat_id': chat_id, 'text': body, 'parse_mode': 'HTML'},
                    timeout=10,
                )
            except Exception as e:
                logger.warning(f'Telegram reply error: {e}')

        # 1. Short-lived capture (connect / wait-for-key)
        with self._capture_lock:
            cb = self._capture_cb
            active = cb and time.time() < self._capture_until
        if active and cb:
            try:
                if cb(upd):
                    self.end_capture()
                    return
            except Exception as e:
                logger.warning(f'Capture handler error: {e}')

        if not text:
            return

        # 2. Silent license push packets
        if text.startswith(('__LICPUSH__', '__LICPUSH_CONFIG__',
                            '__LICEXTEND__', '__LICREVOKE__')):
            if self._license_push_handler:
                try:
                    self._license_push_handler(text)
                except Exception as e:
                    logger.warning(f'License push handler error: {e}')
            return

        # 3. Admin slash commands
        if text.startswith('/') and self._admin_handler:
            try:
                self._admin_handler(upd, reply_fn)
            except Exception as e:
                logger.warning(f'Admin handler error: {e}')


def wait_for_chat_message(
    config_getter: Callable,
    on_chat_id: Callable[[str, dict], None],
    on_timeout: Callable[[], None],
    on_error: Callable[[str], None],
    timeout_sec: float = 180,
    welcome_text: Optional[str] = None,
):
    """
    Run in a background thread: capture the next Telegram message and
    return the sender's chat_id. Uses the shared hub (starts it if needed).
    """
    hub = get_hub()
    if not hub:
        hub = start_hub(config_getter)

    cfg = config_getter() or {}
    token = resolve_bot_token(cfg)
    if not token:
        on_error('Telegram is not ready in this install. Finish setup, restart MBT POS, then try Connect again in Settings.')
        return

    api = f'https://api.telegram.org/bot{token}'
    done = threading.Event()

    def _finish(err: str = ''):
        if done.is_set():
            return
        done.set()
        hub.end_capture()
        if err:
            on_error(err)
        else:
            on_timeout()

    def on_update(upd: dict) -> bool:
        if done.is_set():
            return True
        msg = upd.get('message', {})
        cid = msg.get('chat', {}).get('id')
        if not cid:
            return False
        chat_id = str(cid)
        if welcome_text:
            try:
                name = msg.get('from', {}).get('first_name', 'there')
                requests.post(
                    f'{api}/sendMessage',
                    json={
                        'chat_id': cid,
                        'text': welcome_text.format(name=name),
                        'parse_mode': 'HTML',
                    },
                    timeout=8,
                )
            except Exception:
                pass
        done.set()
        hub.end_capture()
        on_chat_id(chat_id, msg)
        return True

    hub._advance_offset_past_backlog(token)
    hub.begin_capture(on_update, timeout_sec)

    def _timer():
        if not done.wait(timeout_sec):
            _finish()

    threading.Thread(target=_timer, daemon=True).start()
