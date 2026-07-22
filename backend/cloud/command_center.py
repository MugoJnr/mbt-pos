"""
MBT Cloud — Remote Command Center.
Desktop POS polls for pending commands and returns execution status.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from typing import Any, Callable
from urllib.parse import quote

logger = logging.getLogger('cloud.commands')

COMMANDS = {
    'run_backup': 'Run Backup',
    'force_sync': 'Force Sync',
    'refresh_license': 'Refresh License',
    'revoke_license': 'Revoke License',
    'extend_license': 'Extend License',
    'force_validate': 'Force Online Validation',
    'suspend_license': 'Suspend License',
    'collect_logs': 'Collect Logs',
    'restart_sync': 'Restart Sync',
    'restart_services': 'Restart POS Services',
    'update_now': 'Update Now',
    'verify_database': 'Verify Database',
    'test_printer': 'Test Printer',
}


class CommandCenter:
    """Manages remote commands between cloud dashboard and desktop POS."""

    POLL_INTERVAL = 30  # seconds

    def __init__(self, db_path: str, config_getter: Callable[[], dict] | None = None):
        self.db_path = db_path
        self.config_getter = config_getter or (lambda: {})
        self._handlers: dict[str, Callable] = {}
        self._poller: CommandPoller | None = None
        self._register_default_handlers()

    def register_handler(self, command: str, handler: Callable[[dict], tuple[bool, str, dict | None]]):
        self._handlers[command] = handler

    def issue_command(self, org_id: str, device_id: str, command: str,
                      params: dict | None = None, issued_by: str | None = None) -> dict | None:
        if command not in COMMANDS:
            raise ValueError(f'Unknown command: {command}')
        try:
            from backend.cloud.platform_service import service_insert
            row = {
                'org_id': org_id,
                'device_id': device_id,
                'command': command,
                'params': params or {},
                'status': 'pending',
                'issued_by': issued_by,
            }
            return service_insert('remote_commands', row)
        except Exception as e:
            logger.error('issue_command failed: %s', e)
            return None

    def issue_to_license_devices(self, org_id: str, license_id: str, command: str,
                                 params: dict | None = None, issued_by: str | None = None,
                                 *, include_inactive: bool = False) -> list:
        """Push a command to every activation for a license."""
        from backend.cloud.platform_service import service_select
        q = f'license_id=eq.{quote(license_id, safe="")}&select=device_id'
        if not include_inactive:
            q += '&is_active=eq.true'
        acts = service_select('license_activations', q) or []
        # Deduplicate device ids
        seen = set()
        results = []
        for a in acts:
            did = a.get('device_id')
            if not did or did in seen:
                continue
            seen.add(did)
            results.append(self.issue_command(org_id, did, command, params, issued_by))
        return results

    def poll_pending(self, device_id: str) -> list[dict]:
        try:
            from backend.cloud.platform_service import service_select
            return service_select(
                'remote_commands',
                f'device_id=eq.{quote(device_id, safe="")}&status=eq.pending&select=*&order=issued_at.asc',
            ) or []
        except Exception as e:
            logger.debug('poll_pending skipped: %s', e)
            return []

    def execute_local(self, command: str, params: dict | None = None) -> tuple[bool, str, dict | None]:
        handler = self._handlers.get(command)
        if not handler:
            return False, f'No handler for {command}', None
        try:
            return handler(params or {})
        except Exception as e:
            logger.error('Command %s failed: %s', command, e, exc_info=True)
            return False, str(e), None

    def report_result(self, command_id: str, success: bool, result: dict | None = None, error: str = ''):
        try:
            from backend.cloud.platform_service import service_update
            service_update('remote_commands', f'id=eq.{command_id}', {
                'status': 'completed' if success else 'failed',
                'result': result or {},
                'error': error,
                'completed_at': datetime.now().isoformat(),
            })
        except Exception as e:
            logger.warning('report_result failed: %s', e)

    def start_poller(self, device_id_getter: Callable[[], str]):
        if self._poller and self._poller.is_alive():
            return
        self._poller = CommandPoller(self, device_id_getter)
        self._poller.start()

    def stop_poller(self):
        if self._poller:
            self._poller.stop()

    def _register_default_handlers(self):
        self.register_handler('run_backup', self._cmd_run_backup)
        self.register_handler('force_sync', self._cmd_force_sync)
        self.register_handler('refresh_license', self._cmd_refresh_license)
        self.register_handler('revoke_license', self._cmd_revoke_license)
        self.register_handler('extend_license', self._cmd_extend_license)
        self.register_handler('force_validate', self._cmd_force_validate)
        self.register_handler('suspend_license', self._cmd_suspend_license)
        self.register_handler('collect_logs', self._cmd_collect_logs)
        self.register_handler('verify_database', self._cmd_verify_database)

    def _cmd_run_backup(self, params: dict) -> tuple[bool, str, dict | None]:
        try:
            from backend.db_backup import send_db_backup_now
            result = {'triggered': True}
            send_db_backup_now(self.config_getter, reason='remote_command')
            return True, 'Backup initiated', result
        except Exception as e:
            return False, str(e), None

    def _cmd_force_sync(self, params: dict) -> tuple[bool, str, dict | None]:
        try:
            from licensing.license_service import LicenseService
            # Best-effort: trigger cloud validate via engine path
            from licensing.license_engine import LicenseEngine
            eng = LicenseEngine()
            eng.revalidate()
            return True, 'Sync triggered', {'state': eng.state}
        except Exception as e:
            return True, 'Sync triggered', {'note': str(e)}

    def _cmd_refresh_license(self, params: dict) -> tuple[bool, str, dict | None]:
        try:
            from licensing.license_engine import LicenseEngine
            eng = LicenseEngine()
            state = eng.revalidate()
            return True, f'License state: {state}', {'state': state, 'status': eng.get_status_dict()}
        except Exception as e:
            return False, str(e), None

    def _cmd_revoke_license(self, params: dict) -> tuple[bool, str, dict | None]:
        try:
            from licensing.license_engine import LicenseEngine
            eng = LicenseEngine()
            ok, msg = eng.revoke_from_cloud(reason=params.get('reason') or 'Remote revoke from MugoByte Platform')
            return ok, msg, eng.get_status_dict()
        except Exception as e:
            return False, str(e), None

    def _cmd_suspend_license(self, params: dict) -> tuple[bool, str, dict | None]:
        # Treat suspend as soft revoke until unsuspend/renew
        try:
            from licensing.license_engine import LicenseEngine
            eng = LicenseEngine()
            ok, msg = eng.revoke_from_cloud(reason=params.get('reason') or 'Suspended by MugoByte Platform')
            return ok, msg, eng.get_status_dict()
        except Exception as e:
            return False, str(e), None

    def _cmd_extend_license(self, params: dict) -> tuple[bool, str, dict | None]:
        try:
            from licensing.license_engine import LicenseEngine
            eng = LicenseEngine()
            days = int(params.get('days') or params.get('extra_days') or 0)
            expires_at = params.get('expires_at')
            ok, msg = eng.extend_from_cloud(
                days,
                reason=params.get('reason') or 'Remote extend from MugoByte Platform',
                expires_at=expires_at,
            )
            return ok, msg, eng.get_status_dict()
        except Exception as e:
            return False, str(e), None

    def _cmd_force_validate(self, params: dict) -> tuple[bool, str, dict | None]:
        """Must phone home — validate against cloud license server."""
        try:
            from licensing.license_engine import LicenseEngine
            from backend.cloud.license_server import get_license_server
            from backend.cloud_backup.device_manager import get_or_create_device_id

            eng = LicenseEngine()
            key = params.get('license_key') or eng.store.get('cloud_license_key') or (eng._license_data or {}).get('license_key')
            device_id = params.get('device_id') or get_or_create_device_id() or eng.device_id
            if not key:
                eng.store.set('requires_online', True)
                return False, 'No cloud license key on device', eng.get_status_dict()
            ok, msg, data = get_license_server().validate(key, device_id)
            eng.apply_cloud_validation(ok, data, msg)
            return ok, msg, eng.get_status_dict()
        except Exception as e:
            return False, str(e), None

    def _cmd_collect_logs(self, params: dict) -> tuple[bool, str, dict | None]:
        try:
            from mbt_paths import get_project_root
            import os
            log_dir = os.path.join(get_project_root(), 'logs')
            logs = []
            if os.path.isdir(log_dir):
                for f in sorted(os.listdir(log_dir))[-5:]:
                    logs.append(f)
            return True, f'Found {len(logs)} log files', {'logs': logs}
        except Exception as e:
            return False, str(e), None

    def _cmd_verify_database(self, params: dict) -> tuple[bool, str, dict | None]:
        try:
            db = sqlite3.connect(self.db_path)
            result = db.execute('PRAGMA integrity_check').fetchone()[0]
            db.close()
            ok = result == 'ok'
            return ok, f'Database integrity: {result}', {'integrity': result}
        except Exception as e:
            return False, str(e), None


class CommandPoller(threading.Thread):
    """Polls cloud for pending remote commands and executes them."""

    def __init__(self, center: CommandCenter, device_id_getter: Callable[[], str]):
        super().__init__(daemon=True, name='CommandPoller')
        self.center = center
        self.device_id_getter = device_id_getter
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        logger.info('Remote command poller started')
        while not self._stop.is_set():
            try:
                device_id = self.device_id_getter()
                if device_id:
                    pending = self.center.poll_pending(device_id)
                    # Also poll by license engine fingerprint (may differ)
                    try:
                        from licensing.license_engine import LicenseEngine
                        fp = LicenseEngine().device_id
                        if fp and fp != device_id:
                            pending = pending + [c for c in self.center.poll_pending(fp)
                                                 if c.get('id') not in {x.get('id') for x in pending}]
                    except Exception:
                        pass
                    for cmd in pending:
                        cmd_id = cmd.get('id', '')
                        command = cmd.get('command', '')
                        params = cmd.get('params') or {}
                        if isinstance(params, str):
                            try:
                                params = json.loads(params)
                            except Exception:
                                params = {}
                        logger.info('Executing remote command: %s', command)
                        try:
                            from backend.cloud.platform_service import service_update
                            service_update(
                                'remote_commands', f'id=eq.{cmd_id}',
                                {'status': 'running', 'started_at': datetime.now().isoformat()},
                            )
                        except Exception:
                            pass
                        ok, msg, result = self.center.execute_local(command, params)
                        self.center.report_result(cmd_id, ok, result, '' if ok else msg)
            except Exception as e:
                logger.debug('Command poll error: %s', e)
            self._stop.wait(CommandCenter.POLL_INTERVAL)


_center: CommandCenter | None = None


def get_command_center(db_path: str | None = None, config_getter=None) -> CommandCenter:
    global _center
    if _center is None:
        if db_path is None:
            from mbt_paths import get_db_path
            db_path = get_db_path()
        _center = CommandCenter(db_path, config_getter)
    return _center
