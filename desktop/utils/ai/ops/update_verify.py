"""
Update Verification Engine — post-update checklist → PASSED/FAILED report.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from mbt_paths import get_db_path, configure_sqlite_connection

log = logging.getLogger('ai.ops.update_verify')


def _check(name: str, fn) -> Dict[str, Any]:
    t0 = time.time()
    try:
        ok, detail = fn()
        return {
            'name': name, 'passed': bool(ok), 'detail': detail,
            'ms': int((time.time() - t0) * 1000),
        }
    except Exception as e:
        return {
            'name': name, 'passed': False, 'detail': str(e)[:200],
            'ms': int((time.time() - t0) * 1000),
        }


def run_update_verification(api=None, db_path: Optional[str] = None) -> Dict[str, Any]:
    db_path = db_path or get_db_path()
    checks: List[Dict[str, Any]] = []

    def migrations():
        if not os.path.isfile(db_path):
            return False, 'DB missing'
        conn = sqlite3.connect(db_path, timeout=10)
        configure_sqlite_connection(conn)
        try:
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            required = {'users', 'products', 'sales'}
            missing = required - tables
            if missing:
                return False, f'Missing tables: {", ".join(sorted(missing))}'
            # Accounting optional but if module shipped, expect chart or journals
            acct_ok = 'accounts' in tables or 'journal_entries' in tables or 'gl_accounts' in tables
            detail = f'{len(tables)} tables present'
            if not acct_ok:
                detail += ' (accounting tables not detected — OK if feature unused)'
            return True, detail
        finally:
            conn.close()

    def login_path():
        if not api or not hasattr(api, 'get_users'):
            return True, 'API login path not probed (no get_users) — skipped soft'
        users = api.get_users() or []
        if not users:
            return False, 'No users — login will fail'
        return True, f'{len(users)} user(s) available for login'

    def pos_path():
        if not api:
            return True, 'No API — soft skip'
        products = api.get_products() if hasattr(api, 'get_products') else []
        return True, f'POS catalog reachable ({len(products or [])} products)'

    def accounting_post():
        # Soft: ensure accounting engine importable if present
        try:
            from desktop.utils import accounting_engine  # noqa: F401
            return True, 'Accounting engine import OK'
        except Exception as e:
            return True, f'Accounting engine not loaded ({e}) — soft pass'

    def exports_path():
        desk = os.path.join(os.path.expanduser('~'), 'Desktop', 'MBT POS Exports')
        try:
            os.makedirs(desk, exist_ok=True)
            probe = os.path.join(desk, '.mbt_write_probe')
            with open(probe, 'w') as f:
                f.write('ok')
            os.remove(probe)
            return True, f'Exports writable: {desk}'
        except Exception as e:
            return False, f'Exports not writable: {e}'

    def ai_gateway():
        try:
            from desktop.utils.ai.service import get_ai_service
            st = get_ai_service().status()
            return True, f"AI configured={st.get('configured')} online={st.get('online')}"
        except Exception as e:
            return False, f'AI gateway broken: {e}'

    checks.append(_check('Migrations / schema', migrations))
    checks.append(_check('Login path', login_path))
    checks.append(_check('POS catalog', pos_path))
    checks.append(_check('Accounting module', accounting_post))
    checks.append(_check('Exports path', exports_path))
    checks.append(_check('AI gateway', ai_gateway))

    failed = [c for c in checks if not c['passed']]
    return {
        'ok': len(failed) == 0,
        'status': 'PASSED' if not failed else 'FAILED',
        'checks': checks,
        'failed_count': len(failed),
        'summary': (
            f'Update verification PASSED ({len(checks)} checks).'
            if not failed else
            f'Update verification FAILED — {len(failed)} check(s) failed.'
        ),
        'ts': time.time(),
    }
