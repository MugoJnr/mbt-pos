"""
MBT POS — Background License Service
MugoByte Technologies | mugobyte.com

Orchestrates: offline validation, remote sync, tamper detection,
Telegram admin listener, expiry enforcement.
Runs silently — zero UI interference.
"""
import os
import time
import json
import logging
import threading
import requests
from datetime import datetime
from typing import Optional, Callable

from licensing.license_engine import (
    LicenseEngine, LicenseStore,
    STATE_ACTIVE, STATE_EXPIRING, STATE_WARNING,
    STATE_CRITICAL, STATE_EXPIRED, STATE_TAMPERED,
    STATE_UNACTIVATED, STATE_INACTIVE,
    _MASTER_SECRET, _verify_sig,
)
from licensing.telegram_admin import TelegramAdminListener
from backend.telegram_hub import start_hub, stop_hub, resolve_bot_token

logger = logging.getLogger('license_service')

SYNC_INTERVAL     = 6 * 3600    # sync every 6 hours when online
VALIDATE_INTERVAL = 300          # re-validate every 5 minutes offline
class LicenseService(threading.Thread):
    """
    Master background service. One instance per app lifetime.
    Call start() once at app boot. Call stop() on shutdown.
    """

    def __init__(self, project_root: str, config_getter: Callable,
                 on_state_change: Optional[Callable] = None):
        super().__init__(daemon=True, name='LicenseService')
        self.project_root    = project_root
        self.config_getter   = config_getter
        self.on_state_change = on_state_change   # callback(state: str, data: dict)

        self.engine    = LicenseEngine(project_root)
        self._stop     = threading.Event()
        self._tg_admin : Optional[TelegramAdminListener] = None
        self._last_sync = 0
        self._last_state= None
        self._connected = False

    def stop(self):
        self._stop.set()
        if self._tg_admin:
            self._tg_admin.stop()
        stop_hub()

    def run(self):
        logger.info("License service started")
        self._start_telegram_admin()

        # Brief delay then send device registration to developer
        self._stop.wait(8)
        if not self._stop.is_set():
            self._send_device_registration()

        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error(f"License service tick error: {e}")
            self._stop.wait(60)   # check every 60 s

        logger.info("License service stopped")

    def _tick(self):
        # 1. Re-validate locally
        self.engine.revalidate()
        new_state = self.engine.state

        # 2. Fire callback if state changed
        if new_state != self._last_state:
            self._last_state = new_state
            if self.on_state_change:
                try:
                    self.on_state_change(new_state, self.engine.get_status_dict())
                except Exception:
                    pass

        # 3. Try remote sync if online and interval elapsed
        now = int(time.time())
        if now - self._last_sync > SYNC_INTERVAL:
            if self._check_internet():
                self._do_remote_sync()
                self._last_sync = now

    def _check_internet(self) -> bool:
        import socket
        for host in (('8.8.8.8', 53), ('1.1.1.1', 53)):
            try:
                s = socket.create_connection(host, timeout=3)
                s.close()
                self._connected = True
                return True
            except OSError:
                pass
        self._connected = False
        return False

    def _do_remote_sync(self):
        """Apply queued config pushes and log sync — inbound Telegram uses the hub."""
        try:
            now = int(time.time())

            pushed_cfg = self.engine.store.get('remote_config_push')
            if pushed_cfg:
                self._apply_remote_config(pushed_cfg)
                self.engine.store.set('remote_config_push', None)

            self.engine.store.set('last_sync_ts', now)
            self.engine.store.log('SYNC', f'Remote sync OK at {datetime.now().strftime("%H:%M")}')
            logger.info("License sync complete")

        except Exception as e:
            logger.warning(f"Remote sync error: {e}")

    def _handle_license_push(self, text: str):
        """Process __LICPUSH__ / __LICEXTEND__ / __LICREVOKE__ from the Telegram hub."""
        try:
            if text.startswith('__LICPUSH__'):
                payload = json.loads(text[11:])
                ok, _ = self.engine.activate_from_remote(payload)
                if ok:
                    logger.info("Remote license push applied")
                    self.engine.store.log('REMOTE_PUSH', 'License updated via sync')
                    self._on_remote_state_change()
            elif text.startswith('__LICPUSH_CONFIG__'):
                cfg_update = json.loads(text[18:])
                self._apply_remote_config(cfg_update)
                logger.info(f"Config push applied: {list(cfg_update.keys())}")
                self.engine.store.log('CONFIG_PUSH', str(list(cfg_update.keys())))
                if 'developer_chat_id' in cfg_update:
                    self._stop.wait(2)
                    self._send_device_registration()
            elif text.startswith('__LICEXTEND__'):
                payload = json.loads(text[13:])
                extra_days = payload.get('extra_days', 0)
                sig = payload.get('sig', '')
                ok, _ = self.engine.extend(extra_days, sig)
                if ok:
                    logger.info(f"Remote extension: +{extra_days} days")
                    self.engine.store.log('REMOTE_EXTEND', f'+{extra_days} days')
                    self._on_remote_state_change()
            elif text.startswith('__LICREVOKE__'):
                payload = json.loads(text[13:])
                sig = payload.get('sig', '')
                ok, _ = self.engine.revoke(sig)
                if ok:
                    logger.info('Remote revocation applied')
                    self.engine.store.log('REMOTE_REVOKE', 'Revoked by developer')
                    self._on_remote_state_change()
        except Exception as e:
            logger.warning(f"License push handler error: {e}")

    def _apply_remote_config(self, cfg: dict):
        """Apply developer-pushed config updates to app settings."""
        try:
            import sqlite3
            from mbt_paths import get_db_path
            db_path = get_db_path()
            if not os.path.exists(db_path):
                return
            db = sqlite3.connect(db_path)
            for k, v in cfg.items():
                db.execute(
                    "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?,?)",
                    (k, str(v))
                )
            db.commit()
            db.close()
            logger.info(f"Remote config applied: {list(cfg.keys())}")
        except Exception as e:
            logger.warning(f"Remote config apply error: {e}")

    def _start_telegram_admin(self):
        try:
            hub = start_hub(self.config_getter)
            hub.set_license_push_handler(self._handle_license_push)
            self._tg_admin = TelegramAdminListener(
                self.engine, self.config_getter,
                on_state_change=self._on_remote_state_change,
                hub=hub)
        except Exception as e:
            logger.warning(f"Telegram admin start error: {e}")

    # ── Public API ─────────────────────────────────────────────────────────────

    def _on_remote_state_change(self):
        """
        Called immediately by TelegramAdminListener after any state-altering
        remote command (activate / extend / revoke).  Triggers a full revalidate
        so the UI updates within seconds instead of waiting for the 5-min tick.
        """
        try:
            self.engine.revalidate()
            new_state = self.engine.state
            logger.info(f"Remote state change → {new_state}")
            if self.on_state_change:
                self.on_state_change(new_state, self.engine.get_status_dict())
        except Exception as e:
            logger.error(f"_on_remote_state_change error: {e}")

    def get_status(self) -> dict:
        return self.engine.get_status_dict()

    def activate_key(self, key: str):
        return self.engine.activate_with_key(key)

    def force_sync(self):
        if self._check_internet():
            self._do_remote_sync()
            self.engine.revalidate()

    @property
    def is_valid(self) -> bool:
        return self.engine.is_valid

    @property
    def state(self) -> str:
        return self.engine.state

    @property
    def days_remaining(self) -> int:
        return self.engine.days_remaining

    def _send_device_registration(self):
        """
        Automatically send device ID + shop info to the DEVELOPER's Telegram
        so they can activate the license without asking the customer for anything.
        Sends once on first boot, then once per day if still unactivated.
        """
        try:
            # Only send if we have internet
            if not self._check_internet():
                return

            cfg        = self.config_getter() or {}
            token      = resolve_bot_token(cfg)
            dev_chat   = cfg.get('developer_chat_id', '').strip()
            shop_name  = cfg.get('shop_name', 'Unnamed Shop')
            cust_chat  = cfg.get('telegram_chat_id', '').strip()

            # No developer chat ID — still log; developer can use /device_id via bot
            if not token:
                logger.info('Device registration skipped: no bot token configured')
                return
            if not dev_chat:
                logger.info('Device registration skipped: no developer_chat_id (set in deploy or Settings)')
                return

            store     = self.engine.store
            device_id = self.engine.device_id
            state     = self.engine.state
            last_sent = store.get('last_device_report_ts', 0)
            now       = int(time.time())

            # Send on first boot OR daily if not yet activated
            already_active = state in ('active', 'expiring', 'warning', 'critical')
            hours_since    = (now - last_sent) / 3600

            if last_sent and (already_active or hours_since < 23):
                return   # already sent recently and activated — skip

            status_icon = {
                'active':      '✅ ACTIVE',
                'expiring':    '⚠️ EXPIRING SOON',
                'warning':     '⚠️ WARNING',
                'critical':    '🚨 CRITICAL',
                'expired':     '❌ EXPIRED',
                'unactivated': '🔴 NOT ACTIVATED',
                'inactive':    '⚫ INACTIVE',
                'tampered':    '🚨 TAMPERED',
            }.get(state, state.upper())

            divider = "-" * 26
            not_set = "not set"
            ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cust_chat_display = cust_chat if cust_chat else not_set
            msg = (
                "&#x1F4F2; <b>MBT POS - Device Check-In</b>\n"
                + f"{divider}\n"
                + f"Shop:      <b>{shop_name}</b>\n"
                + f"Status:    {status_icon}\n"
                + f"Days left: {self.engine.days_remaining}\n"
                + f"{divider}\n"
                + "<b>Device ID (for license key):</b>\n"
                + f"<code>{device_id}</code>\n"
                + f"{divider}\n"
                + f"Customer Chat ID: <code>{cust_chat_display}</code>\n"
                + f"Time: {ts_str}\n"
                + f"{divider}\n"
                + "<i>Activate: /activate_license trial</i> (30d) "
                + "<i>or /activate_license basic</i> (365d)\n"
                + "<i>MugoByte Technologies</i>"
            )

            resp = requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': dev_chat, 'text': msg, 'parse_mode': 'HTML'},
                timeout=10,
            )

            if resp.ok:
                store.set('last_device_report_ts', now)
                store.log('DEVICE_REPORTED', f'Sent to developer chat {dev_chat[:6]}…')
                logger.info(f'Device registration sent to developer (shop={shop_name})')
            else:
                logger.warning(f'Device registration send failed: {resp.text[:100]}')

        except Exception as e:
            logger.warning(f'Device registration error: {e}')

    def send_tamper_alert(self):
        """Send Telegram alert if tamper is detected."""
        try:
            cfg      = self.config_getter() or {}
            token    = (cfg.get('telegram_bot_token') or '').strip()
            chat_id  = cfg.get('telegram_chat_id', '')
            shop     = cfg.get('shop_name', 'MBT POS')
            if not chat_id:
                return
            msg = (
                f"🚨 <b>TAMPER ALERT — {shop}</b>\n"
                f"Device: <code>{self.engine.masked_device_id}</code>\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Action: License tamper detected — system locked\n"
                f"<i>MugoByte Technologies</i>"
            )
            requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'},
                timeout=10,
            )
        except Exception:
            pass

    @property
    def masked_device_id(self) -> str:
        return self.engine.masked_device_id
