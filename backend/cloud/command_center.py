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
    # Phase 1 remote ops (shop SQLite mutations via command bus)
    'update_product': 'Update Product',
    'adjust_stock': 'Adjust Stock',
    'set_user_active': 'Set User Active',
    'reset_user_pin': 'Reset User PIN',
}

# Non-destructive ops: skip replay only when local receipt is completed/failed.
_IDEMPOTENT_SKIP_COMPLETED = frozenset({
    'update_product',
    'adjust_stock',
    'set_user_active',
    'reset_user_pin',
    'run_backup',
    'force_sync',
    'refresh_license',
    'extend_license',
    'force_validate',
    'collect_logs',
    'restart_sync',
    'restart_services',
    'update_now',
    'verify_database',
    'test_printer',
})

_PRODUCT_UPDATE_FIELDS = (
    'name', 'price', 'cost_price', 'min_stock', 'is_active',
    'barcode', 'unit', 'category', 'sku',
)

_REMOTE_ACTOR = 'remote_owner'


def _ensure_command_jwt(*, reason: str = 'command_poll') -> bool:
    """Refresh identity JWT via the same path SyncManager uses on 401/403."""
    try:
        from backend.cloud_backup.paths import load_identity
        ident = load_identity() or {}
        if not str(ident.get('refresh_token') or '').strip():
            logger.debug('JWT refresh skipped (%s): no refresh_token', reason)
            return False
        from backend.cloud_backup.supabase_client import SupabaseClient
        SupabaseClient().refresh_session()
        logger.info('Command JWT refreshed (%s)', reason)
        return True
    except Exception as e:
        logger.warning('Command JWT refresh failed (%s): %s', reason, e)
        return False


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
            # Never touch *.supabase.co DNS while offline — stalls splash/login.
            if not network_up(1.0):
                return []
            from backend.cloud_backup.paths import load_identity
            from backend.cloud.platform_service import has_service_role
            identity = load_identity() or {}
            if not str(identity.get('access_token') or '').strip() and not has_service_role():
                # Bare anon credentials cannot read device commands under RLS.
                # Avoid a guaranteed-futile TLS handshake every poll interval.
                return []
            # Proactively refresh before poll so pending→running claims succeed.
            _ensure_command_jwt(reason='before_poll_pending')
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

    def _shop_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _audit(self, conn: sqlite3.Connection, action: str, module: str, details: str):
        conn.execute(
            "INSERT INTO audit_log (user_id, username, action, module, details) "
            "VALUES (?,?,?,?,?)",
            (None, _REMOTE_ACTOR, action, module, details),
        )

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
        self.register_handler('restart_sync', self._cmd_restart_sync)
        self.register_handler('update_now', self._cmd_update_now)
        self.register_handler('restart_services', self._cmd_not_implemented)
        self.register_handler('test_printer', self._cmd_not_implemented)
        self.register_handler('update_product', self._cmd_update_product)
        self.register_handler('adjust_stock', self._cmd_adjust_stock)
        self.register_handler('set_user_active', self._cmd_set_user_active)
        self.register_handler('reset_user_pin', self._cmd_reset_user_pin)

    def _cmd_not_implemented(self, params: dict) -> tuple[bool, str, dict | None]:
        # Prefer explicit failure over silent no-handler.
        cmd = (params or {}).get('_command_name') or 'command'
        return False, f'Not implemented on this desktop build: {cmd}', {
            'implemented': False,
        }

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
            from licensing.license_engine import LicenseEngine
            eng = LicenseEngine()
            eng.revalidate()
            return True, 'Sync triggered', {'state': eng.state}
        except Exception as e:
            return True, 'Sync triggered', {'note': str(e)}

    def _cmd_restart_sync(self, params: dict) -> tuple[bool, str, dict | None]:
        """Flush entity outbox / restart sync loop best-effort."""
        try:
            from backend.cloud_backup.sync_manager import SyncManager
            sm = SyncManager.instance()
            flushed = 0
            try:
                flushed = int(sm.flush_entity_outbox() or 0)
            except Exception as flush_err:
                logger.warning('restart_sync flush_entity_outbox: %s', flush_err)
            try:
                sm.clear_device_approval_backoff()
            except Exception:
                pass
            try:
                # Ensure background loop is running
                sm.start()
            except Exception as start_err:
                logger.debug('restart_sync start: %s', start_err)
            return True, f'Sync restarted; flushed {flushed} outbox rows', {
                'flushed': flushed,
            }
        except Exception as e:
            return False, f'restart_sync failed: {e}', {'implemented': True}

    def _cmd_update_now(self, params: dict) -> tuple[bool, str, dict | None]:
        """Check for published update metadata; silent auto-install is not Phase 1."""
        try:
            from backend.cloud.update_center import get_update_center
            import mbt_version
            current = getattr(mbt_version, 'APP_VERSION', '') or ''
            center = get_update_center()
            latest = center.check_for_update(current) if current else center.get_latest()
            if not latest:
                return True, 'No update available', {'update_available': False, 'current': current}
            return True, 'Update available — install from Downloads / installer', {
                'update_available': True,
                'current': current,
                'latest': latest,
                'auto_install': False,
                'note': 'Phase 1 reports availability only; silent install is not implemented',
            }
        except Exception as e:
            return False, f'update_now not available: {e}', {'implemented': False}

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

    def _cmd_update_product(self, params: dict) -> tuple[bool, str, dict | None]:
        """Remote owner product metadata update — no local SA PIN required."""
        try:
            pid = int(params.get('product_id') or 0)
        except (TypeError, ValueError):
            return False, 'product_id required', None
        if pid <= 0:
            return False, 'product_id required', None

        fields = params.get('fields') if isinstance(params.get('fields'), dict) else None
        if fields is None:
            fields = {k: params[k] for k in _PRODUCT_UPDATE_FIELDS if k in params}
        patch = {k: fields[k] for k in _PRODUCT_UPDATE_FIELDS if k in fields}
        if 'stock' in (params or {}) or 'stock' in (fields or {}):
            return False, 'Stock cannot be changed via update_product; use adjust_stock', None
        if not patch:
            return False, 'No updatable fields provided', None

        conn = self._shop_db()
        try:
            row = conn.execute('SELECT id, name FROM products WHERE id=?', (pid,)).fetchone()
            if not row:
                return False, f'Product {pid} not found', None
            sets, values = [], []
            for key, val in patch.items():
                if key == 'is_active':
                    val = 1 if val in (True, 1, '1', 'true', 'True') else 0
                sets.append(f'{key}=?')
                values.append(val)
            sets.append('updated_at=?')
            values.append(datetime.now().isoformat())
            values.append(pid)
            conn.execute(f"UPDATE products SET {', '.join(sets)} WHERE id=?", values)
            self._audit(
                conn, 'REMOTE_UPDATE_PRODUCT', 'inventory',
                f'pid={pid} fields={sorted(patch.keys())} actor={_REMOTE_ACTOR}',
            )
            conn.commit()
            return True, f'Product {pid} updated', {
                'product_id': pid,
                'fields': sorted(patch.keys()),
            }
        except sqlite3.IntegrityError as e:
            conn.rollback()
            return False, f'Update failed: {e}', None
        except Exception as e:
            conn.rollback()
            return False, str(e), None
        finally:
            conn.close()

    def _cmd_adjust_stock(self, params: dict) -> tuple[bool, str, dict | None]:
        """Remote owner stock adjust — command is auth; reason still required."""
        try:
            pid = int(params.get('product_id') or 0)
        except (TypeError, ValueError):
            return False, 'product_id required', None
        if pid <= 0:
            return False, 'product_id required', None

        reason = str(params.get('reason') or '').strip()
        if not reason:
            return False, 'reason is required for stock adjustments', None
        notes = str(params.get('notes') or '').strip()
        if notes:
            reason = f'{reason} | {notes}'

        direction = str(params.get('direction') or '').strip().lower()
        raw_qty = params.get('quantity')
        try:
            import math
            quantity = float(raw_qty)
        except (TypeError, ValueError):
            return False, 'quantity required (number)', None
        if not math.isfinite(quantity):
            return False, 'quantity must be finite', None

        if direction in ('add', 'remove', 'set'):
            qty_abs = abs(quantity)
        else:
            # Signed quantity: positive = add, negative = remove
            if quantity == 0:
                return True, 'No-op (quantity 0)', {'no_op': True, 'product_id': pid}
            direction = 'add' if quantity > 0 else 'remove'
            qty_abs = abs(quantity)

        if direction != 'set' and qty_abs <= 0:
            return False, 'quantity must be > 0 for add/remove', None
        if direction == 'set' and quantity < 0:
            return False, 'set quantity cannot be negative', None

        conn = self._shop_db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute(
                'SELECT id, name, stock, cost_price FROM products WHERE id=?',
                (pid,),
            ).fetchone()
            if not row:
                conn.rollback()
                return False, f'Product {pid} not found', None
            old_stock = round(float(row['stock'] or 0), 4)
            if direction == 'set':
                new_qty = round(float(quantity), 4)
                qty_change = round(new_qty - old_stock, 4)
            elif direction == 'add':
                qty_change = round(qty_abs, 4)
                new_qty = round(old_stock + qty_change, 4)
            else:
                qty_change = round(-qty_abs, 4)
                new_qty = round(old_stock + qty_change, 4)

            if new_qty < 0:
                conn.rollback()
                return False, f'Cannot reduce below zero (have {old_stock:g})', {
                    'current_stock': old_stock,
                }
            if qty_change == 0:
                conn.rollback()
                return True, 'No-op (stock unchanged)', {
                    'no_op': True,
                    'product_id': pid,
                    'old_stock': old_stock,
                    'new_stock': old_stock,
                }

            # Soften catalog direction rules for remote free-text reasons
            try:
                from desktop.utils.option_lists import stock_reason_matches_delta
                if not stock_reason_matches_delta(reason, qty_change):
                    reason = f'Other: {reason}'
            except Exception:
                pass

            now = datetime.now().isoformat()
            changed = conn.execute(
                'UPDATE products SET stock=?, updated_at=? '
                'WHERE id=? AND COALESCE(stock,0)=?',
                (new_qty, now, pid, old_stock),
            )
            if changed.rowcount != 1:
                conn.rollback()
                return False, 'Stock changed concurrently; retry', None

            conn.execute(
                'INSERT INTO stock_movements '
                '(product_id, product_name, movement_type, qty_before, qty_change, '
                'qty_after, reference, reason, user_id, username) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                (
                    pid, row['name'], 'REMOTE_ADJUST',
                    old_stock, qty_change, new_qty,
                    f'REMOTE_ADJUST_pid={pid}', reason,
                    None, _REMOTE_ACTOR,
                ),
            )
            mov_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            self._audit(
                conn, 'REMOTE_STOCK_ADJUSTED', 'inventory',
                f'pid={pid} name={row["name"]} change={qty_change} '
                f'previous={old_stock} new={new_qty} reason={reason}',
            )
            conn.commit()
            return True, f'Stock adjusted to {new_qty:g}', {
                'product_id': pid,
                'old_stock': old_stock,
                'new_stock': new_qty,
                'qty_change': qty_change,
                'movement_id': mov_id,
                'direction': direction,
            }
        except Exception as e:
            conn.rollback()
            return False, str(e), None
        finally:
            conn.close()

    def _resolve_user_row(self, conn: sqlite3.Connection, params: dict):
        uid = params.get('user_id')
        username = str(params.get('username') or '').strip()
        if uid is not None and str(uid).strip() != '':
            try:
                uid_i = int(uid)
            except (TypeError, ValueError):
                return None
            return conn.execute(
                'SELECT id, username, role, is_active FROM users WHERE id=?',
                (uid_i,),
            ).fetchone()
        if username:
            return conn.execute(
                'SELECT id, username, role, is_active FROM users '
                'WHERE LOWER(username)=LOWER(?)',
                (username,),
            ).fetchone()
        return None

    def _cmd_set_user_active(self, params: dict) -> tuple[bool, str, dict | None]:
        if 'is_active' not in params:
            return False, 'is_active bool required', None
        active = params.get('is_active')
        is_active = 1 if active in (True, 1, '1', 'true', 'True') else 0

        conn = self._shop_db()
        try:
            row = self._resolve_user_row(conn, params)
            if not row:
                return False, 'User not found (user_id or username required)', None
            conn.execute(
                'UPDATE users SET is_active=? WHERE id=?',
                (is_active, row['id']),
            )
            self._audit(
                conn, 'REMOTE_SET_USER_ACTIVE', 'admin',
                f'user_id={row["id"]} username={row["username"]} '
                f'is_active={is_active}',
            )
            conn.commit()
            return True, (
                f'User {row["username"]} '
                f'{"enabled" if is_active else "disabled"}'
            ), {
                'user_id': row['id'],
                'username': row['username'],
                'is_active': bool(is_active),
            }
        except Exception as e:
            conn.rollback()
            return False, str(e), None
        finally:
            conn.close()

    def _cmd_reset_user_pin(self, params: dict) -> tuple[bool, str, dict | None]:
        """Reset shop-user login password (hashed). Prefer set_user_active when unsure."""
        new_pin = str(params.get('new_pin') or params.get('new_password') or '').strip()
        if not new_pin:
            return False, (
                'new_pin required — or use set_user_active to disable the account instead'
            ), {'prefer': 'set_user_active'}
        if len(new_pin) < 4:
            return False, 'new_pin must be at least 4 characters', None

        conn = self._shop_db()
        try:
            row = self._resolve_user_row(conn, params)
            if not row:
                return False, 'User not found (user_id or username required)', None
            try:
                from desktop.utils.api_client import _hash_pw
                pw_hash = _hash_pw(new_pin)
            except Exception:
                # Fallback: bcrypt if api_client unavailable in minimal test env
                import bcrypt
                pw_hash = bcrypt.hashpw(new_pin.encode(), bcrypt.gensalt(rounds=12)).decode()
            conn.execute(
                'UPDATE users SET password_hash=? WHERE id=?',
                (pw_hash, row['id']),
            )
            self._audit(
                conn, 'REMOTE_RESET_USER_PIN', 'admin',
                f'user_id={row["id"]} username={row["username"]}',
            )
            conn.commit()
            return True, f'Password reset for {row["username"]}', {
                'user_id': row['id'],
                'username': row['username'],
            }
        except Exception as e:
            conn.rollback()
            return False, str(e), None
        finally:
            conn.close()


class CommandPoller(threading.Thread):
    """Polls cloud for pending remote commands and executes them."""

    def __init__(self, center: CommandCenter, device_id_getter: Callable[[], str]):
        super().__init__(daemon=True, name='CommandPoller')
        self.center = center
        self.device_id_getter = device_id_getter
        self._stop = threading.Event()
        self._license_device_id: str | None = None

    def _get_license_device_id(self) -> str:
        """Resolve the legacy license alias once, not on every poll.

        LicenseEngine initialization includes legacy hardware compatibility and
        encrypted-store validation. Repeating it every 30 seconds caused WMIC
        subprocess launches and expensive PBKDF2 work during otherwise-idle
        installed sessions.
        """
        if self._license_device_id is None:
            try:
                from licensing.license_engine import LicenseEngine
                self._license_device_id = LicenseEngine().device_id or ''
            except Exception:
                self._license_device_id = ''
        return self._license_device_id

    def stop(self):
        self._stop.set()

    def _receipt_repo(self):
        try:
            from desktop.payments.repository import PaymentRepository
            import sqlite3 as _sqlite3
            db_path = self.center.db_path

            def factory():
                conn = _sqlite3.connect(db_path)
                conn.row_factory = _sqlite3.Row
                return conn

            return PaymentRepository(factory)
        except Exception:
            return None

    def _already_executed(self, command_id: str, command: str = '') -> bool:
        repo = self._receipt_repo()
        if not repo:
            return False
        try:
            # Destructive: any local receipt means never run again
            if command in ('revoke_license', 'suspend_license'):
                return repo.has_command_receipt(command_id)
            # Phase-1 ops + others: only skip if completed/failed
            if command in _IDEMPOTENT_SKIP_COMPLETED or command:
                return repo.has_command_receipt(
                    command_id, statuses=['completed', 'failed'],
                )
            return repo.has_command_receipt(
                command_id, statuses=['completed', 'failed'],
            )
        except Exception:
            return False

    def _record_receipt(self, command_id: str, command: str, status: str, result=None):
        repo = self._receipt_repo()
        if not repo:
            return
        try:
            device_id = ''
            try:
                device_id = self.device_id_getter() or ''
            except Exception:
                pass
            repo.record_command_receipt(
                command_id, command, device_id, status, result if isinstance(result, dict) else {},
            )
        except Exception as e:
            logger.warning('record_command_receipt failed: %s', e)

    def _ack_command_safe(self, command_id: str, success: bool, result=None, error: str = ''):
        """Ack to cloud; treat HTTP success with 0 updated rows as failure."""
        if not command_id:
            return
        payload = {
            'status': 'completed' if success else 'failed',
            'result': result or {},
            'error': error,
            'completed_at': datetime.now().isoformat(),
        }
        try:
            from backend.cloud.platform_service import service_update
            updated = service_update(
                'remote_commands',
                f'id=eq.{command_id}',
                payload,
            )
            if isinstance(updated, list) and len(updated) == 0:
                logger.error(
                    'Ack updated 0 rows for command %s — JWT/RLS failure suspected; refreshing JWT',
                    command_id,
                )
                if _ensure_command_jwt(reason='ack_zero_rows'):
                    updated = service_update(
                        'remote_commands',
                        f'id=eq.{command_id}',
                        payload,
                    )
                    if isinstance(updated, list) and len(updated) == 0:
                        logger.error(
                            'Ack still 0 rows after JWT refresh for command %s',
                            command_id,
                        )
                        return False
                    return True
                # Do NOT clear local receipt — prevents re-execution of revoke
                return False
            return True
        except Exception as e:
            logger.warning('ack_command_safe failed: %s', e)
            return False

    def run(self):
        logger.info('Remote command poller started')
        # Let splash/login paint before first Supabase attempt.
        if self._stop.wait(5):
            return
        while not self._stop.is_set():
            try:
                device_id = self.device_id_getter()
                if device_id:
                    pending = self.center.poll_pending(device_id)
                    # Also poll by license engine fingerprint (may differ)
                    try:
                        fp = self._get_license_device_id()
                        if fp and fp != device_id:
                            pending = pending + [c for c in self.center.poll_pending(fp)
                                                 if c.get('id') not in {x.get('id') for x in pending}]
                    except Exception:
                        pass
                    for cmd in pending:
                        cmd_id = str(cmd.get('id', '') or '')
                        command = cmd.get('command', '')
                        params = cmd.get('params') or {}
                        if isinstance(params, str):
                            try:
                                params = json.loads(params)
                            except Exception:
                                params = {}
                        # Durable local receipt BEFORE destructive effects.
                        # Prevents DESKTOP-IKE2VDO-style repeated revoke_license
                        # when JWT expires and cloud ack updates 0 rows.
                        if cmd_id and self._already_executed(cmd_id, command):
                            logger.info(
                                'Skipping already-executed command %s (%s)',
                                command, cmd_id,
                            )
                            self._ack_command_safe(cmd_id, True, {
                                'idempotent': True,
                                'note': 'local_receipt_exists',
                            })
                            continue
                        logger.info('Executing remote command: %s', command)
                        claimed = False
                        try:
                            from backend.cloud.platform_service import service_update
                            # Atomic claim: only transition pending → running
                            updated = service_update(
                                'remote_commands',
                                f'id=eq.{cmd_id}&status=eq.pending',
                                {
                                    'status': 'running',
                                    'started_at': datetime.now().isoformat(),
                                    'claimed_by': device_id,
                                },
                            )
                            # HTTP success with 0 updated rows = ack/claim failure
                            if isinstance(updated, list) and len(updated) == 0:
                                logger.warning(
                                    'Claim updated 0 rows for %s — refreshing JWT and retrying claim',
                                    cmd_id,
                                )
                                if _ensure_command_jwt(reason='claim_zero_rows'):
                                    updated = service_update(
                                        'remote_commands',
                                        f'id=eq.{cmd_id}&status=eq.pending',
                                        {
                                            'status': 'running',
                                            'started_at': datetime.now().isoformat(),
                                            'claimed_by': device_id,
                                        },
                                    )
                                if isinstance(updated, list) and len(updated) == 0:
                                    logger.warning(
                                        'Claim still 0 rows for %s — not executing',
                                        cmd_id,
                                    )
                                    continue
                            if isinstance(updated, dict) and updated.get('count') == 0:
                                continue
                            claimed = True
                        except Exception as e:
                            logger.warning('claim failed for %s: %s', cmd_id, e)
                            # Without atomic claim, refuse destructive commands
                            if command in ('revoke_license', 'suspend_license'):
                                continue
                        if not claimed and command in ('revoke_license', 'suspend_license'):
                            continue
                        # Receipt BEFORE destructive effects
                        if cmd_id:
                            self._record_receipt(
                                cmd_id, command, 'claimed', {'device_id': device_id},
                            )
                        # Tag not-implemented handlers with command name
                        if command in ('restart_services', 'test_printer'):
                            params = dict(params or {})
                            params['_command_name'] = command
                        ok, msg, result = self.center.execute_local(command, params)
                        if cmd_id:
                            self._record_receipt(
                                cmd_id, command,
                                'completed' if ok else 'failed',
                                result if isinstance(result, dict) else {'msg': msg},
                            )
                        self._ack_command_safe(cmd_id, ok, result, '' if ok else msg)
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
