"""
MBT POS - Diagnostic & Self-Healing Engine
Monitors system health, auto-restarts failed modules, generates health reports.
"""
import os
import sys
import json
import time
import socket
import sqlite3
import logging
import threading
import subprocess
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

try:
    from mbt_paths import get_project_root, ensure_data_dirs
    _LOG_ROOT = ensure_data_dirs(get_project_root())
except Exception:
    _LOG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DIAG_LOG = os.path.join(_LOG_ROOT, 'logs', 'diagnostics.log')
os.makedirs(os.path.dirname(DIAG_LOG), exist_ok=True)

diag_logger = logging.getLogger('diagnostics')
fh = logging.FileHandler(DIAG_LOG)
fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
diag_logger.addHandler(fh)
diag_logger.setLevel(logging.DEBUG)


class DiagnosticEngine(threading.Thread):
    """
    Runs continuous health checks in background.
    Stores results, triggers auto-fixes, alerts on critical failures.
    """

    def __init__(self, db_path, config_getter, restart_callback=None):
        super().__init__(daemon=True, name="DiagnosticEngine")
        self.db_path = db_path
        self.config_getter = config_getter
        self.restart_callback = restart_callback
        self._stop = threading.Event()
        self.health_report = {}
        self.check_interval = 60  # seconds
        self.error_counts = {}
        self.MAX_ERRORS_BEFORE_RESTART = 5

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                self._run_all_checks()
            except Exception as e:
                diag_logger.error(f"Diagnostic engine error: {e}")
            self._stop.wait(self.check_interval)

    def _run_all_checks(self):
        report = {
            'timestamp': datetime.now().isoformat(),
            'checks': {}
        }

        checks = [
            ('database', self._check_database),
            ('disk_space', self._check_disk_space),
            ('log_files', self._check_log_files),
            ('telegram', self._check_telegram),
            ('tunnel', self._check_tunnel),
            ('backend_process', self._check_backend),
        ]

        overall = 'healthy'
        for name, fn in checks:
            try:
                result = fn()
                report['checks'][name] = result
                if result.get('status') == 'critical':
                    overall = 'critical'
                    self._handle_critical(name, result)
                elif result.get('status') == 'warning' and overall == 'healthy':
                    overall = 'warning'
            except Exception as e:
                report['checks'][name] = {'status': 'error', 'message': str(e)}
                diag_logger.error(f"Check '{name}' raised: {e}")

        report['overall'] = overall
        self.health_report = report
        diag_logger.debug(f"Health: {overall}")
        return report

    def _check_database(self):
        try:
            db = sqlite3.connect(self.db_path, timeout=5)
            db.execute("PRAGMA integrity_check")
            count = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.close()
            return {'status': 'healthy', 'message': f'DB OK — {count} sales records', 'sales_count': count}
        except Exception as e:
            self._log_error('database', str(e))
            return {'status': 'critical', 'message': str(e)}

    def _check_disk_space(self):
        try:
            import shutil
            total, used, free = shutil.disk_usage(os.path.dirname(self.db_path))
            free_pct = (free / total) * 100
            free_gb = free / (1024 ** 3)
            if free_pct < 5:
                return {'status': 'critical', 'message': f'Only {free_gb:.1f}GB free ({free_pct:.1f}%)', 'free_gb': round(free_gb, 2)}
            elif free_pct < 15:
                return {'status': 'warning', 'message': f'{free_gb:.1f}GB free ({free_pct:.1f}%)', 'free_gb': round(free_gb, 2)}
            return {'status': 'healthy', 'message': f'{free_gb:.1f}GB free', 'free_gb': round(free_gb, 2)}
        except Exception as e:
            return {'status': 'warning', 'message': str(e)}

    def _check_log_files(self):
        log_dir = os.path.join(os.path.dirname(os.path.dirname(self.db_path)), 'logs')
        warnings = []
        try:
            for f in os.listdir(log_dir):
                fpath = os.path.join(log_dir, f)
                size_mb = os.path.getsize(fpath) / (1024 * 1024)
                if size_mb > 100:
                    warnings.append(f"{f}: {size_mb:.1f}MB")
            if warnings:
                return {'status': 'warning', 'message': f'Large logs: {", ".join(warnings)}'}
            return {'status': 'healthy', 'message': 'Log files normal'}
        except Exception as e:
            return {'status': 'warning', 'message': str(e)}

    def _check_telegram(self):
        """Bot token + chat readiness (does not expose secrets)."""
        try:
            cfg = self.config_getter() or {}
            token = (cfg.get('telegram_bot_token') or '').strip()
            chat = (cfg.get('telegram_chat_id') or cfg.get('developer_chat_id') or '').strip()
            if not token:
                try:
                    from config.deploy import load_deploy_config
                    token = (load_deploy_config().get('telegram_bot_token') or '').strip()
                    chat = chat or (load_deploy_config().get('developer_chat_id') or '').strip()
                except Exception:
                    pass
            if not token:
                return {'status': 'warning', 'message': 'Telegram bot token missing'}
            if not chat:
                return {'status': 'warning', 'message': 'Bot token set — shop chat ID not linked'}
            return {'status': 'healthy', 'message': 'Telegram configured (token + chat)'}
        except Exception as e:
            return {'status': 'warning', 'message': str(e)}

    def _check_tunnel(self):
        """Cloudflare tunnel / remote dashboard readiness (token-aware, no false ACTIVE)."""
        try:
            from backend.cloudflare_setup import get_cloudflare_health_panel
            p = get_cloudflare_health_panel()
            domain = p.get('domain') or '—'
            state = p.get('connection_state') or 'unknown'
            if state == 'active' and p.get('ssl_ok'):
                return {'status': 'healthy',
                        'message': f'ACTIVE — {domain} (DNS+SSL OK)'}
            if p.get('wrong_token_type'):
                return {'status': 'critical',
                        'message': f'Wrong token type (cfut_ in API slot) — {domain}'}
            if p.get('token_type') == 'missing' and domain != '—':
                return {'status': 'warning',
                        'message': f'Vendor management token missing — {domain}'}
            if p.get('tunnel_running') and not p.get('ssl_ok'):
                return {'status': 'warning',
                        'message': f'Tunnel up, HTTPS pending — {domain}'}
            if p.get('dns_ok') and not p.get('ssl_ok'):
                return {'status': 'warning',
                        'message': f'DNS OK, SSL pending — {domain}'}
            if state in ('configured', 'pending', 'running'):
                return {'status': 'warning',
                        'message': f'{state} — {domain}'}
            if state == 'off':
                return {'status': 'healthy', 'message': 'Remote disabled (LAN only)'}
            return {'status': 'warning',
                    'message': f'{state} — {domain}'}
        except Exception:
            pass
        # Fallback without cloudflare_setup import
        try:
            root = os.path.dirname(os.path.dirname(self.db_path))
            cfg_path = os.path.join(root, 'config', 'web_config.json')
            domain = '—'
            remote_ok = False
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r', encoding='utf-8-sig') as f:
                    w = json.load(f)
                domain = w.get('tunnel_domain') or '—'
                remote_ok = bool(w.get('remote_setup_ok'))
            if remote_ok:
                return {'status': 'warning',
                        'message': f'Config says OK — verify HTTPS — {domain}'}
            return {'status': 'warning',
                    'message': f'Remote setup incomplete — {domain}'}
        except Exception as e:
            return {'status': 'warning', 'message': str(e)}

    def _check_backend(self):
        try:
            import urllib.request
            with urllib.request.urlopen('http://127.0.0.1:5050/api/health', timeout=2) as r:
                if r.status == 200:
                    return {'status': 'healthy', 'message': 'Backend :5050 OK'}
            return {'status': 'warning', 'message': 'Backend health unexpected'}
        except Exception:
            return {'status': 'warning', 'message': 'Backend not reachable on :5050'}

    def _handle_critical(self, check_name, result):
        key = f"critical_{check_name}"
        self.error_counts[key] = self.error_counts.get(key, 0) + 1
        diag_logger.critical(f"CRITICAL [{check_name}]: {result.get('message')} (count={self.error_counts[key]})")

        # No auto-restart hooks for report/telegram warnings

    def _log_error(self, module, message):
        try:
            db = sqlite3.connect(self.db_path, timeout=3)
            db.execute("""INSERT OR IGNORE INTO sync_queue (action_type, payload)
                          VALUES (?, ?)""",
                       ('error', json.dumps({'module': module, 'message': message,
                                             'time': datetime.now().isoformat()})))
            db.commit()
            db.close()
        except Exception:
            pass

    def get_health_report(self):
        if not self.health_report:
            return self._run_all_checks()
        return self.health_report

    def run_manual_check(self):
        return self._run_all_checks()

    def rotate_logs(self):
        """Rotate large log files."""
        log_dir = os.path.join(os.path.dirname(os.path.dirname(self.db_path)), 'logs')
        rotated = []
        try:
            for f in os.listdir(log_dir):
                if not f.endswith('.log'):
                    continue
                fpath = os.path.join(log_dir, f)
                size_mb = os.path.getsize(fpath) / (1024 * 1024)
                if size_mb > 50:
                    archive = fpath + '.' + datetime.now().strftime('%Y%m%d%H%M%S') + '.bak'
                    os.rename(fpath, archive)
                    rotated.append(f)
                    diag_logger.info(f"Rotated: {f} → {os.path.basename(archive)}")
        except Exception as e:
            diag_logger.error(f"Log rotation error: {e}")
        return rotated

    def export_full_report(self, output_path=None):
        """Export comprehensive diagnostic report as JSON."""
        report = self.get_health_report()
        report['system'] = {
            'platform': sys.platform,
            'python': sys.version,
            'pid': os.getpid(),
            'cwd': os.getcwd(),
        }
        report['generated_at'] = datetime.now().isoformat()
        report['powered_by'] = 'MugoByte Technologies — mugobyte.com'

        if output_path is None:
            output_path = os.path.join(
                os.path.dirname(os.path.dirname(self.db_path)),
                'logs',
                f'health_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            )
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        diag_logger.info(f"Health report exported: {output_path}")
        return output_path
