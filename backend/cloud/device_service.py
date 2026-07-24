"""
MBT Cloud — Device Registration Service.
Desktop POS sends device info to cloud on boot and periodically.
"""
from __future__ import annotations

import logging
import platform
import socket
import threading
from datetime import datetime
from typing import Any, Callable
from urllib.parse import quote

logger = logging.getLogger('cloud.devices')


def _quick_online(timeout: float = 1.0) -> bool:
    """Fail-open connectivity probe — never hang shop UI/threads."""
    import socket
    for host in (('1.1.1.1', 53), ('8.8.8.8', 53)):
        try:
            s = socket.create_connection(host, timeout=timeout)
            s.close()
            return True
        except OSError:
            pass
    return False


def _resolve_cloud_ids() -> tuple[str, str]:
    """Return (business_id, org_id) for device registration."""
    from backend.cloud_backup.paths import load_identity
    from backend.cloud.platform_service import service_select

    ident = load_identity()
    business_id = ident.get('business_id') or ''
    org_id = ident.get('org_id') or ''

    # Skip Portal lookups when offline — identity alone is enough for later retry.
    if not _quick_online(1.0):
        return business_id, org_id

    if business_id and not org_id:
        try:
            rows = service_select(
                'businesses',
                f'id=eq.{quote(business_id, safe="")}&select=org_id,id&limit=1',
                timeout=5,
            )
            if rows and rows[0].get('org_id'):
                org_id = rows[0]['org_id']
        except Exception:
            pass

    if org_id and not business_id:
        try:
            rows = service_select(
                'businesses',
                f'org_id=eq.{quote(org_id, safe="")}&select=id&limit=1',
                timeout=5,
            )
            if rows:
                business_id = rows[0]['id']
        except Exception:
            pass

    return business_id, org_id


class DeviceService:
    """Manages device registration and heartbeat with MBT Cloud."""

    HEARTBEAT_INTERVAL = 300  # 5 minutes

    def __init__(self, config_getter: Callable[[], dict] | None = None):
        self.config_getter = config_getter or (lambda: {})
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def get_device_info(self) -> dict:
        from backend.cloud_backup.device_manager import get_or_create_device_id
        from licensing.license_engine import LicenseEngine

        device_id = get_or_create_device_id()
        try:
            eng = LicenseEngine()
            fingerprint = eng.device_id
        except Exception:
            fingerprint = device_id

        cfg = self.config_getter() or {}
        try:
            from backend.app import APP_VERSION
            version = APP_VERSION
        except Exception:
            version = 'unknown'

        return {
            'device_id': device_id,
            'computer_name': socket.gethostname(),
            'hardware_fingerprint': fingerprint,
            'operating_system': f'{platform.system()} {platform.release()}',
            'platform': platform.system(),
            'mbt_version': version,
            'branch': cfg.get('branch_name', ''),
            'shop_name': cfg.get('shop_name', ''),
        }

    def register(self) -> tuple[bool, str]:
        """Register or update this device in MBT Cloud."""
        if not _quick_online(1.0):
            return False, 'Offline — will retry when online'
        info = self.get_device_info()
        try:
            from backend.cloud_backup.paths import is_cloud_configured
            if not is_cloud_configured():
                return False, 'Cloud not configured'

            business_id, org_id = _resolve_cloud_ids()
            if not business_id and not org_id:
                return False, 'Not logged in to cloud'

            from backend.cloud.platform_service import register_or_refresh_device

            if not org_id and business_id:
                from backend.cloud.platform_service import service_select
                rows = service_select(
                    'businesses',
                    f'id=eq.{quote(business_id, safe="")}&select=org_id&limit=1',
                    timeout=5,
                ) or []
                if rows:
                    org_id = rows[0].get('org_id') or ''

            if not org_id:
                return False, 'Organization not linked — complete Portal business setup'

            row = register_or_refresh_device(
                org_id,
                device_id=info['device_id'],
                business_id=business_id or None,
                computer_name=info['computer_name'],
                hostname=info['computer_name'],
                platform_str=info['platform'],
                mbt_version=info['mbt_version'],
                os_info=info['operating_system'],
                hardware_fingerprint=info['hardware_fingerprint'],
                branch=info.get('branch') or '',
            )
            status = (row or {}).get('approval_status') or 'pending'
            logger.info('Device registered: %s (%s)', info['device_id'], status)
            return True, f'Device registered ({status})'
        except Exception as e:
            logger.warning('Device registration failed: %s', e)
            return False, str(e)

    def heartbeat(self):
        """Update last_seen_at in cloud."""
        try:
            if not _quick_online(1.0):
                return
            from backend.cloud_backup.paths import is_cloud_configured
            if not is_cloud_configured():
                return
            business_id, org_id = _resolve_cloud_ids()
            if not business_id and not org_id:
                return
            info = self.get_device_info()
            from backend.cloud.platform_service import service_update
            patch = {
                'last_seen_at': datetime.now().isoformat(),
                'mbt_version': info['mbt_version'],
            }
            if business_id:
                service_update(
                    'devices',
                    f'business_id=eq.{quote(business_id, safe="")}&device_id=eq.{quote(info["device_id"], safe="")}',
                    patch,
                )
            elif org_id:
                service_update(
                    'devices',
                    f'org_id=eq.{quote(org_id, safe="")}&device_id=eq.{quote(info["device_id"], safe="")}',
                    patch,
                )
        except Exception as e:
            logger.debug('Heartbeat skipped: %s', e)

    def start_heartbeat(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name='DeviceHeartbeat')
        self._thread.start()

    def stop_heartbeat(self):
        self._stop.set()

    def _heartbeat_loop(self):
        self.register()
        while not self._stop.is_set():
            self._stop.wait(self.HEARTBEAT_INTERVAL)
            if not self._stop.is_set():
                self.heartbeat()

    def list_devices(self) -> list[dict]:
        try:
            from backend.cloud_backup.paths import is_cloud_configured
            if not is_cloud_configured():
                return []
            business_id, org_id = _resolve_cloud_ids()
            from backend.cloud.platform_service import list_devices_for_org, service_select
            if org_id:
                return list_devices_for_org(org_id)
            if business_id:
                return service_select(
                    'devices',
                    f'business_id=eq.{quote(business_id, safe="")}&select=*&order=last_seen_at.desc',
                ) or []
            return []
        except Exception as e:
            logger.warning('list_devices failed: %s', e)
            return []


_device_service: DeviceService | None = None


def get_device_service(config_getter=None) -> DeviceService:
    global _device_service
    if _device_service is None:
        _device_service = DeviceService(config_getter)
    return _device_service
