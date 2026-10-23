"""
MBT Cloud — Remote Command Center.
Desktop POS polls for pending commands and returns execution status.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Callable
from urllib.parse import quote

logger = logging.getLogger('cloud.commands')

_receipt_lock = threading.Lock()
_RECEIPT_LIMIT = 500


def _receipt_path() -> str:
    """Local command-id ledger. Not the shop database and not the license store."""
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    folder = os.path.join(base, 'MugoByte', 'MBT POS')
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, 'command_receipts.json')


def load_command_receipts(path: str | None = None) -> set[str]:
    path = path or _receipt_path()
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return {str(x) for x in data if str(x).strip()}
    except Exception:
        return set()
    return set()


def remember_command(command_id: str, path: str | None = None) -> None:
    """Record the id before any destructive effect. Crash-safe replace."""
    command_id = str(command_id or '').strip()
    if not command_id:
        raise ValueError('command id required')
    path = path or _receipt_path()
    with _receipt_lock:
        ids = list(load_command_receipts(path))
        if command_id not in ids:
            ids.append(command_id)
        ids = ids[-_RECEIPT_LIMIT:]
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(ids, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)


def updated_row_has_id(data: Any, command_id: str) -> bool:
    """True only when PostgREST returned the row this device changed."""
    command_id = str(command_id or '').strip()
    if not command_id:
        return False
    rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    for row in rows:
        if isinstance(row, dict) and str(row.get('id') or '') == command_id:
            return True
    return False


def claim_pending_command(command_id: str) -> bool:
    """Atomically move pending -> running. Empty or failed updates do not claim."""
    from backend.cloud.platform_service import service_update
    from backend.cloud_backup.supabase_client import SupabaseError

    command_id = str(command_id or '').strip()
    if not command_id:
        return False
    query = f'id=eq.{quote(command_id, safe="")}&status=eq.pending'
    patch = {'status': 'running', 'started_at': datetime.now().isoformat()}

    def once() -> bool:
        return updated_row_has_id(
            service_update('remote_commands', query, patch),
            command_id,
        )

    try:
        return once()
    except SupabaseError as exc:
        if exc.status not in (401, 403):
            logger.info('Command %s claim failed: %s', command_id, exc)
            return False
        if not _refresh_user_token():
            return False
        try:
            return once()
        except Exception as retry_exc:
            logger.info('Command %s claim failed after token refresh: %s', command_id, retry_exc)
            return False
    except Exception as exc:
        logger.info('Command %s claim failed: %s', command_id, exc)
        return False


def _refresh_user_token() -> bool:
    """One background refresh. Uses the existing 12s client timeout."""
    try:
        from backend.cloud_backup.supabase_client import SupabaseClient
        SupabaseClient().refresh_session()
        return True
    except Exception as exc:
        logger.info('Command poll token refresh skipped: %s', exc)
        return False

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
    'update_product_price': 'Change Product Price',
    'update_product_cost': 'Change Product Cost',
    'adjust_stock': 'Adjust Stock',
    'disable_user': 'Disable User',
    'reset_user_pin': 'Reset User PIN',
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
            from backend.cloud.net_gate import network_up
            if not network_up(1.0):
                return []
            from backend.cloud.platform_service import has_service_role, service_select
            from backend.cloud_backup.paths import load_identity
            if not has_service_role():
                identity = load_identity() or {}
                if not str(identity.get('access_token') or '').strip():
                    return []
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
        self.register_handler('update_product_price', self._cmd_update_product_price)
        self.register_handler('update_product_cost', self._cmd_update_product_cost)
        self.register_handler('adjust_stock', self._cmd_adjust_stock)
        self.register_handler('disable_user', self._cmd_disable_user)
        self.register_handler('reset_user_pin', self._cmd_reset_user_pin)
        self.register_handler('restart_sync', self._cmd_restart_sync)
        self.register_handler('update_now', self._cmd_update_now)

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

    def _shop_db(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def _one_row(self, sql: str, args: tuple) -> tuple[bool, str, dict | None]:
        """A successful HTTP-style update must change exactly one row."""
        db = self._shop_db()
        try:
            db.execute('BEGIN IMMEDIATE')
            cur = db.execute(sql, args)
            if cur.rowcount != 1:
                db.rollback()
                return False, 'No matching row was updated', None
            db.commit()
            return True, 'Updated', {'rows': 1}
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            return False, str(exc), None
        finally:
            db.close()

    def _cmd_update_product_price(self, params: dict) -> tuple[bool, str, dict | None]:
        try:
            price = round(float(params.get('price')), 2)
        except (TypeError, ValueError):
            return False, 'Enter a price', None
        if price < 0:
            return False, 'Price cannot be negative', None
        return self._one_row(
            'UPDATE products SET price=? WHERE id=?',
            (price, int(params.get('product_id') or 0)),
        )

    def _cmd_update_product_cost(self, params: dict) -> tuple[bool, str, dict | None]:
        try:
            cost = round(float(params.get('cost_price')), 2)
        except (TypeError, ValueError):
            return False, 'Enter a cost', None
        if cost < 0:
            return False, 'Cost cannot be negative', None
        return self._one_row(
            'UPDATE products SET cost_price=? WHERE id=?',
            (cost, int(params.get('product_id') or 0)),
        )

    def _cmd_adjust_stock(self, params: dict) -> tuple[bool, str, dict | None]:
        command_id = str(params.get('command_id') or '').strip()
        if not command_id:
            return False, 'A command id is required', None
        try:
            delta = float(params.get('delta'))
        except (TypeError, ValueError):
            return False, 'Enter a quantity', None
        if delta == 0:
            return False, 'Quantity cannot be zero', None
        pid = int(params.get('product_id') or 0)
        ref = f'CMD:{command_id}'
        db = self._shop_db()
        try:
            db.execute('BEGIN IMMEDIATE')
            already = db.execute(
                'SELECT id FROM stock_movements WHERE reference=?', (ref,)
            ).fetchone()
            if already:
                db.commit()
                return True, 'Already applied', {'duplicate': True}
            row = db.execute(
                'SELECT id, name, stock FROM products WHERE id=?', (pid,)
            ).fetchone()
            if not row:
                db.rollback()
                return False, 'Product was not updated', None
            old = float(row['stock'] or 0)
            new = round(old + delta, 4)
            if new < 0:
                db.rollback()
                return False, 'Stock cannot go below zero', None
            cur = db.execute(
                'UPDATE products SET stock=? WHERE id=? AND stock=?',
                (new, pid, old),
            )
            if cur.rowcount != 1:
                db.rollback()
                return False, 'Stock changed before this command', None
            db.execute(
                "INSERT INTO stock_movements "
                "(product_id,product_name,movement_type,qty_before,qty_change,"
                "qty_after,reference,reason,user_id,username) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, row['name'], 'REMOTE_ADJUST', old, delta, new,
                 ref, str(params.get('reason') or 'Remote stock adjustment'),
                 None, 'remote'),
            )
            db.commit()
            return True, 'Stock adjusted', {'stock': new}
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            return False, str(exc), None
        finally:
            db.close()

    def _cmd_disable_user(self, params: dict) -> tuple[bool, str, dict | None]:
        return self._one_row(
            'UPDATE users SET is_active=0 WHERE id=?',
            (int(params.get('user_id') or 0),),
        )

    def _cmd_reset_user_pin(self, params: dict) -> tuple[bool, str, dict | None]:
        pin = str(params.get('pin') or '')
        if not (pin.isdigit() and len(pin) == 6):
            return False, 'PIN must be 6 digits', None
        from desktop.utils.security import _pin_hash
        db = self._shop_db()
        try:
            cols = {row[1] for row in db.execute('PRAGMA table_info(users)').fetchall()}
            if 'pin_hash' not in cols:
                db.execute('ALTER TABLE users ADD COLUMN pin_hash TEXT')
            db.commit()
        except Exception as exc:
            return False, str(exc), None
        finally:
            db.close()
        ok, msg, result = self._one_row(
            'UPDATE users SET pin_hash=? WHERE id=?',
            (_pin_hash(pin), int(params.get('user_id') or 0)),
        )
        if result is not None:
            result = {'rows': 1}
        return ok, msg, result

    def _cmd_restart_sync(self, params: dict) -> tuple[bool, str, dict | None]:
        db = self._shop_db()
        try:
            db.execute(
                'CREATE TABLE IF NOT EXISTS system_settings '
                '(key TEXT PRIMARY KEY, value TEXT)'
            )
            db.execute(
                "INSERT INTO system_settings (key, value) VALUES ('sync_restart_requested', '1') "
                "ON CONFLICT(key) DO UPDATE SET value='1'"
            )
            db.commit()
            return True, 'Sync restart requested', {'processes_killed': 0}
        except Exception as exc:
            return False, str(exc), None
        finally:
            db.close()

    def _cmd_update_now(self, params: dict) -> tuple[bool, str, dict | None]:
        """Record the request. Do not launch an installer or stop the till."""
        db = self._shop_db()
        try:
            db.execute(
                'CREATE TABLE IF NOT EXISTS system_settings '
                '(key TEXT PRIMARY KEY, value TEXT)'
            )
            db.execute(
                "INSERT INTO system_settings (key, value) VALUES ('update_requested', '1') "
                "ON CONFLICT(key) DO UPDATE SET value='1'"
            )
            db.commit()
            return True, 'Update requested; installer was not started', {
                'installer_started': False,
            }
        except Exception as exc:
            return False, str(exc), None
        finally:
            db.close()


def dispatch_remote_command(center: CommandCenter, cmd: dict, receipt_path: str | None = None) -> str:
    """Claim, record, then run. A missed claim or a saved id never reaches the handler."""
    cmd_id = str(cmd.get('id') or '').strip()
    command = cmd.get('command', '')
    params = cmd.get('params') or {}
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except Exception:
            params = {}
    if not cmd_id or not command:
        return 'ignored'
    if cmd_id in load_command_receipts(receipt_path):
        logger.info('Remote command %s already handled; not running again', cmd_id)
        center.report_result(cmd_id, True, {'skipped': 'already_handled'}, '')
        return 'skipped'
    if not claim_pending_command(cmd_id):
        logger.info('Remote command %s was not claimed; not executing %s', cmd_id, command)
        return 'unclaimed'
    try:
        remember_command(cmd_id, receipt_path)
    except Exception as rec_exc:
        logger.warning('Command receipt not saved; not executing %s: %s', command, rec_exc)
        return 'receipt_failed'
    logger.info('Executing remote command: %s', command)
    ok, msg, result = center.execute_local(command, params)
    center.report_result(cmd_id, ok, result, '' if ok else msg)
    return 'executed'


class CommandPoller(threading.Thread):
    """Polls cloud for pending remote commands and executes them."""

    def __init__(self, center: CommandCenter, device_id_getter: Callable[[], str]):
        super().__init__(daemon=True, name='CommandPoller')
        self.center = center
        self.device_id_getter = device_id_getter
        self._stop = threading.Event()
        self._license_fp = ''

    def stop(self):
        self._stop.set()

    def _get_license_device_id(self) -> str:
        if self._license_fp:
            return self._license_fp
        from licensing.license_engine import LicenseEngine
        self._license_fp = str(getattr(LicenseEngine(), 'device_id', '') or '')
        return self._license_fp

    def run(self):
        logger.info('Remote command poller started')
        while not self._stop.is_set():
            try:
                device_id = self.device_id_getter()
                if device_id:
                    pending = self.center.poll_pending(device_id)
                    # Also poll by license fingerprint (may differ).
                    # Resolve once. A new LicenseEngine every poll runs wmic
                    # and flashes a command window.
                    try:
                        if not self._license_fp:
                            from licensing.license_engine import resolve_device_id
                            self._license_fp = resolve_device_id() or ''
                        fp = self._license_fp
                        if fp and fp != device_id:
                            pending = pending + [c for c in self.center.poll_pending(fp)
                                                 if c.get('id') not in {x.get('id') for x in pending}]
                    except Exception:
                        pass
                    for cmd in pending:
                        dispatch_remote_command(self.center, cmd)
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
