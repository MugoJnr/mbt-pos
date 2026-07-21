"""
MBT POS — Background License Service
MugoByte Technologies | mugobyte.com

Orchestrates: offline validation, remote sync, tamper detection,
cloud device registration, expiry enforcement.
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

logger = logging.getLogger('license_service')

SYNC_INTERVAL     = 6 * 3600    # cloud validate every 6 hours when online
VALIDATE_INTERVAL = 300          # re-validate every 5 minutes offline
OFFLINE_GRACE_DAYS = 7           # must phone home within this window
FORCE_ONLINE_CHECK_HOURS = 24    # attempt cloud validate at least daily when online


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
        self._last_sync = 0
        self._last_state= None
        self._connected = False
        self._tamper_alerted = False

    def stop(self):
        self._stop.set()

    def run(self):
        logger.info("License service started")

        # Brief delay then register device with cloud
        self._stop.wait(8)
        if not self._stop.is_set():
            self._register_device_with_cloud()

        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error(f"License service tick error: {e}")
            self._stop.wait(60)   # check every 60 s

        logger.info("License service stopped")

    def _grace_days(self) -> int:
        cfg = self.config_getter() or {}
        try:
            return max(1, int(cfg.get('license_offline_grace_days') or OFFLINE_GRACE_DAYS))
        except Exception:
            return OFFLINE_GRACE_DAYS

    def _tick(self):
        # 1. Re-validate locally (tamper / expiry / device bind)
        prev = self._last_state
        self.engine.revalidate()
        new_state = self.engine.state

        # 2. Offline grace — require internet confirmation after N days
        allowed, grace_msg = self.engine.enforce_offline_grace(self._grace_days())
        if not allowed:
            new_state = self.engine.state
            logger.warning(grace_msg)

        # 3. Fire callback if state changed
        if new_state != self._last_state:
            self._last_state = new_state
            if new_state == STATE_TAMPERED and not self._tamper_alerted:
                self._tamper_alerted = True
                self.send_tamper_alert()
            if self.on_state_change:
                try:
                    status = self.engine.get_status_dict()
                    status['grace_message'] = grace_msg
                    self.on_state_change(new_state, status)
                except Exception:
                    pass

        # 4. Cloud validate when online
        now = int(time.time())
        check_interval = min(SYNC_INTERVAL, FORCE_ONLINE_CHECK_HOURS * 3600)
        if now - self._last_sync > check_interval:
            if self._check_internet():
                self._do_remote_sync()
                self._last_sync = now
            else:
                # Still enforce grace even when offline
                self.engine.enforce_offline_grace(self._grace_days())

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
        """Phone home: validate license with MugoByte Platform and sync expiry/status."""
        try:
            now = int(time.time())

            pushed_cfg = self.engine.store.get('remote_config_push')
            if pushed_cfg:
                self._apply_remote_config(pushed_cfg)
                self.engine.store.set('remote_config_push', None)

            # Cloud license validation (revoked / suspended / expiry sync)
            self._cloud_validate_license()

            self.engine.store.set('last_sync_ts', now)
            self.engine.store.log('SYNC', f'Remote sync OK at {datetime.now().strftime("%H:%M")}')
            logger.info("License sync complete")
            self._register_device_with_cloud()

        except Exception as e:
            logger.warning(f"Remote sync error: {e}")

    def _cloud_validate_license(self):
        """Confirm this device's license is still valid in Supabase."""
        try:
            from backend.cloud_backup.paths import is_cloud_configured
            if not is_cloud_configured():
                # No cloud — treat local-only installs as OK for grace clock
                self.engine.store.set('last_cloud_ok_ts', int(time.time()))
                return
            key = self.engine.store.get('cloud_license_key') or (self.engine._license_data or {}).get('license_key')
            if not key:
                # Local signed key only — stamp OK so offline grace doesn't false-lock
                self.engine.store.set('last_cloud_ok_ts', int(time.time()))
                self.engine.store.set('last_cloud_check_ts', int(time.time()))
                return
            from backend.cloud.license_server import get_license_server
            from backend.cloud_backup.device_manager import get_or_create_device_id
            device_id = get_or_create_device_id() or self.engine.device_id
            ok, msg, data = get_license_server().validate(key, device_id)
            self.engine.apply_cloud_validation(ok, data, msg)
            if not ok:
                logger.warning('Cloud license invalid: %s', msg)
                self._on_remote_state_change()
            else:
                logger.info('Cloud license validated: %s', msg)
        except Exception as e:
            logger.debug('Cloud validate skipped: %s', e)

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

    def _register_device_with_cloud(self):
        """Register device with MugoByte Platform (Portal device roster)."""
        try:
            if not self._check_internet():
                return
            from backend.cloud.device_service import get_device_service
            svc = get_device_service(self.config_getter)
            ok, msg = svc.register()
            if ok:
                logger.info('Device registered with cloud: %s', msg)
            else:
                logger.debug('Cloud device registration skipped: %s', msg)
        except Exception as e:
            logger.debug('Cloud device registration error: %s', e)

    # ── Public API ─────────────────────────────────────────────────────────────

    def _on_remote_state_change(self):
        """Called after remote license state change. Triggers revalidation."""
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

    def send_tamper_alert(self):
        """Send tamper alert via notification engine."""
        try:
            from backend.cloud.notification_engine import get_notification_engine
            cfg = self.config_getter() or {}
            shop = cfg.get('shop_name', 'MBT POS')
            engine = get_notification_engine(config_getter=self.config_getter)
            engine.publish(
                'tamper',
                f'TAMPER ALERT — {shop}',
                f'Device: {self.engine.masked_device_id} · License tamper detected — system locked',
                'error',
            )
        except Exception:
            pass

    @property
    def masked_device_id(self) -> str:
        return self.engine.masked_device_id
