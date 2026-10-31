"""
MBT POS — Direct Database Client
MugoByte Technologies | mugobyte.com

Calls the database DIRECTLY — no HTTP, no Flask, no localhost ports.
Eliminates firewall / antivirus blocking completely.
Works 100% offline by design.
"""
import os
import sys
import json
import sqlite3
import hashlib
import logging
import secrets
import threading
import jwt
from datetime import datetime, date, timedelta
from runtime_security import get_jwt_secret

logger = logging.getLogger(__name__)

_PIN_FAILS = {}
_PIN_FAILS_LOCK = threading.Lock()
_PIN_WINDOW_SECONDS = 600
_PIN_MAX_FAILURES = 8
_APPROVAL_CLAIM_SECONDS = 45


def _pin_failures_blocked(user_id) -> tuple[bool, int]:
    """Shared PIN lockout stored in the shop database."""
    from desktop.utils.account_sessions import pin_blocked
    return pin_blocked(user_id)


def _pin_failure_record(user_id) -> None:
    from desktop.utils.account_sessions import pin_record
    pin_record(user_id)


def _pin_failures_clear(user_id) -> None:
    from desktop.utils.account_sessions import pin_clear
    pin_clear(user_id)


def _request_payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _ensure_request_receipts(db) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS request_receipts (
            client_token TEXT PRIMARY KEY,
            operation TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            result_json TEXT NOT NULL
        )"""
    )


def _read_request_receipt(db, token: str, operation: str, payload: dict):
    """Inside a write transaction. None means this call has no token."""
    token = (token or '').strip()
    if not token:
        return None
    _ensure_request_receipts(db)
    digest = _request_payload_hash({'operation': operation, 'payload': payload})
    row = db.execute(
        "SELECT operation, payload_hash, result_json FROM request_receipts "
        "WHERE client_token=?",
        (token,),
    ).fetchone()
    if not row:
        return {'new': True, 'hash': digest}
    if row['operation'] != operation or row['payload_hash'] != digest:
        return {
            'error': 'This request token was already used for a different change.',
            'status': 409,
        }
    prior = json.loads(row['result_json'])
    prior['duplicate'] = True
    prior['success'] = True
    return prior


def _save_request_receipt(db, token: str, operation: str, digest: str, result: dict) -> None:
    token = (token or '').strip()
    if not token or not digest:
        return
    _ensure_request_receipts(db)
    stored = {key: value for key, value in result.items() if key != 'duplicate'}
    db.execute(
        "INSERT INTO request_receipts "
        "(client_token, operation, payload_hash, result_json) VALUES (?,?,?,?)",
        (token, operation, digest, json.dumps(stored, default=str)),
    )

from mbt_paths import get_project_root, get_db_path, ensure_data_dirs, configure_sqlite_connection

PROJECT_ROOT = ensure_data_dirs(get_project_root())


def _get_export_dir() -> str:
    """Return user-friendly export folder (Desktop/MBT POS Exports or fallback)."""
    for candidate in (
        os.path.join(os.path.expanduser('~'), 'Desktop'),
        os.path.join(os.path.expanduser('~'), 'Documents'),
        os.path.expanduser('~'),
    ):
        if os.path.isdir(candidate):
            folder = os.path.join(candidate, 'MBT POS Exports')
            os.makedirs(folder, exist_ok=True)
            return folder
    folder = os.path.join(PROJECT_ROOT, 'exports')
    os.makedirs(folder, exist_ok=True)
    return folder

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

SECRET_KEY = get_jwt_secret()

# Failed-login lockout (memory cache + system_settings persistence).
LOGIN_MAX_FAILED_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 60
RECOVERY_LOCKOUT_SECONDS = 15 * 60
LOGIN_LOCKOUT_SETTING_KEY = 'login_lockout_state'
_LOGIN_ATTEMPTS: dict[str, dict] = {}


def _lockout_load_from_db(db) -> dict[str, dict]:
    """Load persisted lockout map; prune expired entries."""
    import time
    try:
        row = db.execute(
            "SELECT value FROM system_settings WHERE key=?",
            (LOGIN_LOCKOUT_SETTING_KEY,),
        ).fetchone()
        raw = row['value'] if row else ''
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            return {}
        now = time.time()
        cleaned = {}
        for k, v in data.items():
            if not isinstance(v, dict):
                continue
            fails = int(v.get('fails') or 0)
            until = float(v.get('locked_until') or 0)
            if until > now or fails > 0:
                cleaned[str(k).lower()] = {'fails': fails, 'locked_until': until}
        return cleaned
    except Exception:
        return {}


def _lockout_save_to_db(db, state: dict[str, dict]) -> None:
    try:
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key,value,updated_at) VALUES (?,?,?)",
            (LOGIN_LOCKOUT_SETTING_KEY, json.dumps(state), datetime.now().isoformat()),
        )
        db.commit()
    except Exception:
        pass


def clear_login_lockout_cache() -> None:
    """Test helper — clear in-process lockout cache."""
    _LOGIN_ATTEMPTS.clear()


def _recovery_lockout_status(db, key: str) -> dict | None:
    """Return a user-facing lock response when a recovery factor is throttled."""
    import time
    normalized = f"recovery:{key}".lower()
    persisted = _lockout_load_from_db(db)
    for cache_key, value in persisted.items():
        _LOGIN_ATTEMPTS.setdefault(cache_key, value)
    state = _LOGIN_ATTEMPTS.get(normalized) or {}
    locked_until = float(state.get('locked_until') or 0)
    if locked_until <= time.time():
        return None
    retry_after = max(1, int(locked_until - time.time() + 0.999))
    return {
        'error': f'Too many failed recovery attempts. Try again in {retry_after}s.',
        'locked': True,
        'retry_after': retry_after,
    }


def _record_recovery_attempt(db, key: str, success: bool) -> None:
    """Persist recovery failures so app restarts cannot bypass throttling."""
    import time
    normalized = f"recovery:{key}".lower()
    if success:
        _LOGIN_ATTEMPTS.pop(normalized, None)
    else:
        state = _LOGIN_ATTEMPTS.get(normalized) or {
            'fails': 0, 'locked_until': 0.0}
        fails = int(state.get('fails') or 0) + 1
        if fails >= LOGIN_MAX_FAILED_ATTEMPTS:
            state = {
                'fails': 0,
                'locked_until': time.time() + RECOVERY_LOCKOUT_SECONDS,
            }
        else:
            state = {'fails': fails, 'locked_until': 0.0}
        _LOGIN_ATTEMPTS[normalized] = state
    _lockout_save_to_db(db, dict(_LOGIN_ATTEMPTS))


# ── Password helpers (must match backend/app.py) ────────────────────────────────
def _check_pw(pw: str, stored: str) -> bool:
    """
    Detect hash format first, then verify.
    bcrypt hashes start with $2b$ or $2a$.
    Our custom format is: hexsalt:sha256hex
    """
    if stored.startswith((b'$2b$', b'$2a$', b'$2y$')
                         if isinstance(stored, bytes)
                         else ('$2b$', '$2a$', '$2y$')):
        try:
            import bcrypt as _bc
            return _bc.checkpw(pw.encode(), stored.encode()
                               if isinstance(stored, str) else stored)
        except Exception:
            return False
    # Custom salt:sha256 format
    parts = stored.split(':', 1)
    if len(parts) != 2:
        return False
    salt, hashed = parts
    return hashlib.sha256((salt + pw).encode()).hexdigest() == hashed


def _hash_pw(pw: str) -> str:
    """Always use our custom salt:sha256 format for consistency."""
    salt = os.urandom(16).hex()
    return salt + ':' + hashlib.sha256((salt + pw).encode()).hexdigest()


# ── Database connection ─────────────────────────────────────────────────────────
_SCHEMA_READY = False


def _db(*, ensure_schema: bool = True) -> sqlite3.Connection:
    """Open SQLite connection. Schema bootstrap runs once per process (not every call)."""
    global _SCHEMA_READY
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=3.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    # Always ensure schema exists (safe on existing DBs via CREATE IF NOT EXISTS)
    # Running full migrations on every open caused multi-second stalls / lock storms
    # under rapid POS API sequences (sale → debt → payment).
    if ensure_schema and not _SCHEMA_READY:
        _ensure_schema(conn)
        _SCHEMA_READY = True
    _ensure_permission_columns(conn)
    return conn


def _db_light() -> sqlite3.Connection:
    """Connection for audit/helpers — skip schema bootstrap."""
    return _db(ensure_schema=False)


def _ensure_permission_columns(conn) -> None:
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    except Exception:
        return
    if not cols:
        return
    if "permission_grants" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN permission_grants TEXT DEFAULT '[]'")
    if "permission_denials" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN permission_denials TEXT DEFAULT '[]'")


def _rows(cursor) -> list:
    return [dict(r) for r in cursor.fetchall()]


def _row(cursor):
    r = cursor.fetchone()
    return dict(r) if r else None


# ── Schema bootstrap (called on every _db() open so tables always exist) ────────
def _ensure_schema(conn: sqlite3.Connection):
    """Create all tables if they don't exist yet.  Safe to call repeatedly."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'cashier',
        full_name TEXT,
        email TEXT,
        is_active INTEGER DEFAULT 1,
        tab_permissions TEXT DEFAULT '["dashboard","sales","inventory"]',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        last_login TEXT
    );
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        sku TEXT UNIQUE,
        category TEXT,
        price REAL NOT NULL DEFAULT 0,
        cost_price REAL DEFAULT 0,
        stock INTEGER DEFAULT 0,
        min_stock INTEGER DEFAULT 5,
        unit TEXT DEFAULT 'pcs',
        barcode TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_number TEXT UNIQUE NOT NULL,
        cashier_id INTEGER,
        cashier_name TEXT,
        subtotal REAL DEFAULT 0,
        discount REAL DEFAULT 0,
        tax REAL DEFAULT 0,
        total REAL NOT NULL,
        payment_method TEXT DEFAULT 'cash',
        amount_paid REAL DEFAULT 0,
        change_amount REAL DEFAULT 0,
        notes TEXT,
        status TEXT DEFAULT 'completed',
        synced INTEGER DEFAULT 0,
        sale_date TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(cashier_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        product_id INTEGER,
        product_name TEXT NOT NULL,
        sku TEXT,
        quantity REAL NOT NULL,
        unit_price REAL NOT NULL,
        discount REAL DEFAULT 0,
        total REAL NOT NULL,
        FOREIGN KEY(sale_id) REFERENCES sales(id),
        FOREIGN KEY(product_id) REFERENCES products(id)
    );
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        action TEXT NOT NULL,
        module TEXT,
        details TEXT,
        ip_address TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT,
        content TEXT,
        pinned INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS sync_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        attempts INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        synced_at TEXT
    );
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS stock_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        movement_type TEXT NOT NULL,
        qty_before REAL NOT NULL,
        qty_change REAL NOT NULL,
        qty_after REAL NOT NULL,
        reference TEXT,
        reason TEXT,
        user_id INTEGER,
        username TEXT,
        device_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS sale_edits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        edited_by_id INTEGER,
        edited_by_name TEXT,
        edit_type TEXT NOT NULL,
        field_name TEXT,
        old_value TEXT,
        new_value TEXT,
        reason TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        email TEXT,
        address TEXT,
        credit_limit REAL DEFAULT 0,
        notes TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS debt_invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT UNIQUE NOT NULL,
        sale_id INTEGER,
        receipt_number TEXT,
        customer_id INTEGER NOT NULL,
        customer_name TEXT NOT NULL,
        customer_phone TEXT,
        total_amount REAL NOT NULL,
        amount_paid REAL DEFAULT 0,
        balance REAL NOT NULL,
        status TEXT DEFAULT 'pending',
        due_date TEXT,
        cashier_id INTEGER,
        cashier_name TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS debt_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_receipt TEXT UNIQUE NOT NULL,
        invoice_id INTEGER NOT NULL,
        customer_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        payment_method TEXT DEFAULT 'cash',
        balance_before REAL NOT NULL,
        balance_after REAL NOT NULL,
        cashier_id INTEGER,
        cashier_name TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS departments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS stock_consumptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reference_no TEXT UNIQUE NOT NULL,
        date TEXT NOT NULL,
        department_id INTEGER,
        reason TEXT NOT NULL,
        notes TEXT,
        taken_by TEXT,
        total_cost REAL DEFAULT 0,
        created_by INTEGER,
        created_by_name TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        voided INTEGER DEFAULT 0,
        voided_by INTEGER,
        voided_by_name TEXT,
        voided_at TEXT,
        void_reason TEXT,
        FOREIGN KEY(department_id) REFERENCES departments(id)
    );
    CREATE TABLE IF NOT EXISTS stock_consumption_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        consumption_id INTEGER NOT NULL,
        product_id INTEGER,
        product_name TEXT,
        quantity REAL NOT NULL,
        unit_cost REAL NOT NULL,
        total_cost REAL NOT NULL,
        selling_price REAL DEFAULT 0,
        retail_opportunity REAL DEFAULT 0,
        foregone_profit REAL DEFAULT 0,
        unit TEXT,
        stock_before REAL,
        stock_after REAL,
        FOREIGN KEY(consumption_id) REFERENCES stock_consumptions(id),
        FOREIGN KEY(product_id) REFERENCES products(id)
    );
    CREATE TABLE IF NOT EXISTS customer_wallet (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL UNIQUE,
        balance REAL NOT NULL DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(customer_id) REFERENCES customers(id)
    );
    CREATE TABLE IF NOT EXISTS wallet_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        sale_id INTEGER,
        receipt_number TEXT,
        txn_type TEXT NOT NULL,
        amount REAL NOT NULL,
        balance_before REAL NOT NULL,
        balance_after REAL NOT NULL,
        notes TEXT,
        cashier_id INTEGER,
        cashier_name TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(customer_id) REFERENCES customers(id)
    );
    CREATE TABLE IF NOT EXISTS payment_variances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER,
        receipt_number TEXT,
        customer_id INTEGER,
        customer_name TEXT,
        payment_method TEXT,
        sale_total REAL NOT NULL,
        amount_received REAL NOT NULL,
        excess_amount REAL NOT NULL,
        handling TEXT NOT NULL,
        misc_category TEXT,
        reason TEXT,
        credit_applied REAL DEFAULT 0,
        tip_amount REAL DEFAULT 0,
        transport_amount REAL DEFAULT 0,
        deposit_amount REAL DEFAULT 0,
        advance_amount REAL DEFAULT 0,
        change_returned REAL DEFAULT 0,
        misc_amount REAL DEFAULT 0,
        manager_approved INTEGER DEFAULT 0,
        manager_name TEXT,
        cashier_id INTEGER,
        cashier_name TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(sale_id) REFERENCES sales(id)
    );
    """)
    # Production never creates a known default credential. API-only development
    # may opt in with an explicit, non-empty bootstrap password.
    bootstrap_password = os.environ.get('MBT_BOOTSTRAP_ADMIN_PASSWORD', '').strip()
    existing = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not existing and bootstrap_password:
        from roles import default_tab_permissions
        import json as _json
        pw_hash = _hash_pw(bootstrap_password)
        conn.execute(
            "INSERT INTO users (username,password_hash,role,full_name,tab_permissions) VALUES (?,?,?,?,?)",
            ('admin', pw_hash, 'superadmin', 'Shop Owner',
             _json.dumps(default_tab_permissions('superadmin')))
        )
    _migrate_columns(conn)
    # Seed default settings if missing (per-shop; see config/deploy.py)
    try:
        from config.deploy import shop_settings_defaults
        defaults = shop_settings_defaults()
    except Exception:
        try:
            from config.deploy import shop_settings_defaults
            defaults = shop_settings_defaults()
        except Exception:
            defaults = {
                'shop_name': 'My Shop', 'shop_address': '', 'shop_phone': '',
                'shop_email': '', 'currency_symbol': 'KES', 'tax_rate': '0',
                'receipt_footer': 'Thank you for shopping with us!',
                'theme': 'dark', 'sync_interval': '30',
                'printer_name': '', 'printer_port': 'USB', 'auto_print': '1',
                'auto_report_daily': '1', 'auto_report_weekly': '0',
                'auto_report_interval_hours': '4', 'auto_report_weekday': '0',
                'auto_db_backup': '1', 'auto_db_backup_interval_hours': '24',
                'mpesa_mode': 'manual', 'mpesa_till': '', 'mpesa_paybill': '',
                'mpesa_business_name': '',
                'variance_enabled': '1',
                'variance_enable_deposits': '1',
                'variance_enable_tips': '1',
                'variance_enable_transport': '1',
                'variance_max_cashier': '1000',
                'variance_require_customer_deposit': '1',
                'variance_allow_refund_after_finalize': '0',
                'cash_rounding_enabled': '1',
                'cash_rounding_mode': 'nearest',
                'cash_rounding_value': '5',
                'cash_rounding_apply_cash': '1',
                'cash_rounding_apply_mpesa': '0',
                'cash_rounding_apply_card': '0',
                'cash_rounding_apply_bank': '0',
                'after_sale_default_customer': 'walk_in',
                'after_sale_default_payment': 'Cash',
                'after_sale_focus_barcode': '1',
                'after_sale_auto_clear_cart': '1',
                'after_sale_reset_discounts': '1',
                'after_sale_reset_notes': '1',
            }
    # Payment variance defaults (upgrade-safe)
    for k, v in (
        ('variance_enabled', '1'),
        ('variance_enable_deposits', '1'),
        ('variance_enable_tips', '1'),
        ('variance_enable_transport', '1'),
        ('variance_max_cashier', '1000'),
        ('variance_require_customer_deposit', '1'),
        ('variance_allow_refund_after_finalize', '0'),
        ('cash_rounding_enabled', '1'),
        ('cash_rounding_mode', 'nearest'),
        ('cash_rounding_value', '5'),
        ('cash_rounding_apply_cash', '1'),
        ('cash_rounding_apply_mpesa', '0'),
        ('cash_rounding_apply_card', '0'),
        ('cash_rounding_apply_bank', '0'),
        ('after_sale_default_customer', 'walk_in'),
        ('after_sale_default_payment', 'Cash'),
        ('after_sale_focus_barcode', '1'),
        ('after_sale_auto_clear_cart', '1'),
        ('after_sale_reset_discounts', '1'),
        ('after_sale_reset_notes', '1'),
        ('pos_checkout_layout', 'product_explorer'),
    ):
        conn.execute("INSERT OR IGNORE INTO system_settings (key,value) VALUES (?,?)", (k, v))
    for k, v in defaults.items():
        conn.execute("INSERT OR IGNORE INTO system_settings (key,value) VALUES (?,?)", (k, v))
    # Telegram settings are retired — clear any leftover keys on upgrade.
    for key in ('telegram_bot_token', 'telegram_chat_id', 'developer_chat_id'):
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key,value) VALUES (?,?)",
            (key, ''),
        )
    conn.commit()


def _migrate_columns(conn: sqlite3.Connection):
    """Add columns/settings introduced after first release."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sales)").fetchall()}
    if 'mpesa_ref' not in cols:
        conn.execute("ALTER TABLE sales ADD COLUMN mpesa_ref TEXT")
    if 'status' not in cols:
        conn.execute("ALTER TABLE sales ADD COLUMN status TEXT DEFAULT 'completed'")
        conn.execute(
            "UPDATE sales SET status='completed' WHERE status IS NULL OR status=''"
        )
    # First shop owner: upgrade legacy admin to superadmin (Security tab)
    conn.execute(
        "UPDATE users SET role='superadmin' WHERE username='admin' AND role='admin'"
    )
    # Admin role must not keep owner-only tabs (security / license)
    for row in conn.execute(
        "SELECT id, role, tab_permissions FROM users WHERE role IN ('admin','manager','cashier','viewer')"
    ).fetchall():
        try:
            from roles import sanitize_tab_permissions
            import json as _json
            perms = _json.loads(row['tab_permissions'] or '[]')
            fixed = sanitize_tab_permissions(row['role'], perms)
            if (row['role'] or '').lower() == 'cashier' and 'consumption' not in fixed:
                fixed.append('consumption')
            if 'sales' in fixed and 'receipts' not in fixed:
                fixed.insert(fixed.index('sales') + 1, 'receipts')
            if fixed != perms:
                conn.execute(
                    "UPDATE users SET tab_permissions=? WHERE id=?",
                    (_json.dumps(fixed), row['id']),
                )
        except Exception:
            pass
    # Unused default departments are archived only when they have no history.
    # A new shop starts with an empty department list.
    for dept_name in (
        'Kitchen', 'Bakery', 'Juice Bar', 'Office',
        'Workshop', 'Manufacturing', 'Maintenance',
    ):
        row = conn.execute(
            "SELECT id FROM departments WHERE name=?", (dept_name,)
        ).fetchone()
        if not row:
            continue
        used = conn.execute(
            "SELECT COUNT(*) FROM stock_consumptions WHERE department_id=?",
            (row['id'],),
        ).fetchone()[0]
        if int(used or 0) == 0:
            conn.execute(
                "UPDATE departments SET active=0 WHERE id=?",
                (row['id'],),
            )
    # Ensure consumption void / taken_by columns on upgrades
    try:
        sc_cols = {r[1] for r in conn.execute("PRAGMA table_info(stock_consumptions)").fetchall()}
        for col, ddl in (
            ('taken_by', "ALTER TABLE stock_consumptions ADD COLUMN taken_by TEXT"),
            ('total_cost', "ALTER TABLE stock_consumptions ADD COLUMN total_cost REAL DEFAULT 0"),
            ('created_by_name', "ALTER TABLE stock_consumptions ADD COLUMN created_by_name TEXT"),
            ('voided', "ALTER TABLE stock_consumptions ADD COLUMN voided INTEGER DEFAULT 0"),
            ('voided_by', "ALTER TABLE stock_consumptions ADD COLUMN voided_by INTEGER"),
            ('voided_by_name', "ALTER TABLE stock_consumptions ADD COLUMN voided_by_name TEXT"),
            ('voided_at', "ALTER TABLE stock_consumptions ADD COLUMN voided_at TEXT"),
            ('void_reason', "ALTER TABLE stock_consumptions ADD COLUMN void_reason TEXT"),
        ):
            if sc_cols and col not in sc_cols:
                conn.execute(ddl)
        item_cols = {r[1] for r in conn.execute("PRAGMA table_info(stock_consumption_items)").fetchall()}
        for col, ddl in (
            ('selling_price', "ALTER TABLE stock_consumption_items ADD COLUMN selling_price REAL DEFAULT 0"),
            ('retail_opportunity', "ALTER TABLE stock_consumption_items ADD COLUMN retail_opportunity REAL DEFAULT 0"),
            ('foregone_profit', "ALTER TABLE stock_consumption_items ADD COLUMN foregone_profit REAL DEFAULT 0"),
            ('unit', "ALTER TABLE stock_consumption_items ADD COLUMN unit TEXT"),
            ('stock_before', "ALTER TABLE stock_consumption_items ADD COLUMN stock_before REAL"),
            ('stock_after', "ALTER TABLE stock_consumption_items ADD COLUMN stock_after REAL"),
        ):
            if item_cols and col not in item_cols:
                conn.execute(ddl)
    except Exception:
        pass
    # Customer type for standardized customer form
    try:
        cust_cols = {r[1] for r in conn.execute("PRAGMA table_info(customers)").fetchall()}
        if cust_cols and 'customer_type' not in cust_cols:
            conn.execute(
                "ALTER TABLE customers ADD COLUMN customer_type TEXT DEFAULT 'Retail'")
    except Exception:
        pass
    # Grant Internal Consumption tab to existing inventory-capable staff
    for row in conn.execute(
        "SELECT id, role, tab_permissions FROM users "
        "WHERE role IN ('superadmin','admin','manager')"
    ).fetchall():
        try:
            import json as _json
            perms = _json.loads(row['tab_permissions'] or '[]')
            if 'consumption' not in perms and (
                'inventory' in perms or row['role'] in ('superadmin', 'admin', 'manager')
            ):
                # Insert after inventory when present
                if 'inventory' in perms:
                    i = perms.index('inventory') + 1
                    perms.insert(i, 'consumption')
                else:
                    perms.append('consumption')
                conn.execute(
                    "UPDATE users SET tab_permissions=? WHERE id=?",
                    (_json.dumps(perms), row['id']),
                )
        except Exception:
            pass
    # Payment variance tables (upgrade path)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS customer_wallet (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL UNIQUE,
        balance REAL NOT NULL DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(customer_id) REFERENCES customers(id)
    );
    CREATE TABLE IF NOT EXISTS wallet_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        sale_id INTEGER,
        receipt_number TEXT,
        txn_type TEXT NOT NULL,
        amount REAL NOT NULL,
        balance_before REAL NOT NULL,
        balance_after REAL NOT NULL,
        notes TEXT,
        cashier_id INTEGER,
        cashier_name TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS payment_variances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER,
        receipt_number TEXT,
        customer_id INTEGER,
        customer_name TEXT,
        payment_method TEXT,
        sale_total REAL NOT NULL,
        amount_received REAL NOT NULL,
        excess_amount REAL NOT NULL,
        handling TEXT NOT NULL,
        misc_category TEXT,
        reason TEXT,
        credit_applied REAL DEFAULT 0,
        tip_amount REAL DEFAULT 0,
        transport_amount REAL DEFAULT 0,
        deposit_amount REAL DEFAULT 0,
        advance_amount REAL DEFAULT 0,
        change_returned REAL DEFAULT 0,
        misc_amount REAL DEFAULT 0,
        manager_approved INTEGER DEFAULT 0,
        manager_name TEXT,
        cashier_id INTEGER,
        cashier_name TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    # Sale columns for credit applied / variance snapshot
    try:
        sales_cols = {r[1] for r in conn.execute("PRAGMA table_info(sales)").fetchall()}
        if 'credit_applied' not in sales_cols:
            conn.execute("ALTER TABLE sales ADD COLUMN credit_applied REAL DEFAULT 0")
        if 'customer_id' not in sales_cols:
            conn.execute("ALTER TABLE sales ADD COLUMN customer_id INTEGER")
        if 'variance_handling' not in sales_cols:
            conn.execute("ALTER TABLE sales ADD COLUMN variance_handling TEXT")
        if 'original_total' not in sales_cols:
            conn.execute("ALTER TABLE sales ADD COLUMN original_total REAL DEFAULT 0")
        if 'cash_rounding_adj' not in sales_cols:
            conn.execute("ALTER TABLE sales ADD COLUMN cash_rounding_adj REAL DEFAULT 0")
        if 'electronic_paid' not in sales_cols:
            conn.execute("ALTER TABLE sales ADD COLUMN electronic_paid REAL DEFAULT 0")
        if 'electronic_method' not in sales_cols:
            conn.execute("ALTER TABLE sales ADD COLUMN electronic_method TEXT")
        if 'cash_paid' not in sales_cols:
            conn.execute("ALTER TABLE sales ADD COLUMN cash_paid REAL DEFAULT 0")
        if 'payment_tenders' not in sales_cols:
            conn.execute("ALTER TABLE sales ADD COLUMN payment_tenders TEXT")
        if 'original_sale_id' not in sales_cols:
            conn.execute("ALTER TABLE sales ADD COLUMN original_sale_id INTEGER")
        if 'sale_date' not in sales_cols:
            conn.execute("ALTER TABLE sales ADD COLUMN sale_date TEXT")
        conn.execute(
            "UPDATE sales SET sale_date=date(created_at) "
            "WHERE sale_date IS NULL OR sale_date=''"
        )
        if 'client_token' not in sales_cols:
            conn.execute("ALTER TABLE sales ADD COLUMN client_token TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_client_token "
            "ON sales(client_token) WHERE client_token IS NOT NULL AND client_token != ''"
        )
    except Exception:
        pass
    # Sale-item returned qty tracking (partial returns)
    try:
        si_cols = {r[1] for r in conn.execute("PRAGMA table_info(sale_items)").fetchall()}
        if si_cols and 'returned_qty' not in si_cols:
            conn.execute(
                "ALTER TABLE sale_items ADD COLUMN returned_qty REAL DEFAULT 0")
    except Exception:
        pass
    # Suppliers + optional product link (receiving / V05)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        email TEXT,
        address TEXT,
        notes TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS stock_receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_number TEXT UNIQUE,
        supplier_id INTEGER,
        reference_note TEXT,
        notes TEXT,
        grand_total REAL DEFAULT 0,
        user_id INTEGER,
        username TEXT,
        client_token TEXT UNIQUE,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS stock_receipt_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_id INTEGER NOT NULL,
        product_id INTEGER,
        product_name TEXT,
        quantity REAL NOT NULL,
        unit_cost REAL DEFAULT 0,
        line_total REAL DEFAULT 0,
        movement_id INTEGER
    );
    CREATE TABLE IF NOT EXISTS stock_adjustment_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_number TEXT UNIQUE,
        product_id INTEGER NOT NULL,
        product_name TEXT,
        current_stock REAL,
        requested_qty REAL NOT NULL,
        reason TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        user_id INTEGER,
        username TEXT,
        reviewer_id INTEGER,
        reviewer_name TEXT,
        review_note TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TEXT
    );
    """)
    try:
        receipt_cols = {r[1] for r in conn.execute("PRAGMA table_info(stock_receipts)").fetchall()}
        if receipt_cols and 'status' not in receipt_cols:
            conn.execute("ALTER TABLE stock_receipts ADD COLUMN status TEXT DEFAULT 'posted'")
        if receipt_cols and 'reversed_at' not in receipt_cols:
            conn.execute("ALTER TABLE stock_receipts ADD COLUMN reversed_at TEXT")
    except Exception:
        pass
    try:
        from desktop.utils.supplier_payables import ensure_schema as _supplier_schema
        _supplier_schema(conn)
    except Exception:
        logger.exception('supplier payables schema')
    try:
        prod_cols = {r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()}
        if prod_cols and 'supplier_id' not in prod_cols:
            conn.execute("ALTER TABLE products ADD COLUMN supplier_id INTEGER")
        if prod_cols and 'image_path' not in prod_cols:
            conn.execute("ALTER TABLE products ADD COLUMN image_path TEXT")
    except Exception:
        pass
    # Cash rounding adjustment ledger (does not inflate product revenue)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS cash_rounding_adjustments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER,
        receipt_number TEXT,
        original_amount REAL NOT NULL,
        rounded_amount REAL NOT NULL,
        adjustment REAL NOT NULL,
        electronic_paid REAL DEFAULT 0,
        cash_original REAL DEFAULT 0,
        cash_rounded REAL DEFAULT 0,
        payment_method TEXT,
        cashier_id INTEGER,
        cashier_name TEXT,
        voided INTEGER DEFAULT 0,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    # Debt integrity: customer national_id + payment reference
    try:
        cust_cols = {r[1] for r in conn.execute("PRAGMA table_info(customers)").fetchall()}
        if 'national_id' not in cust_cols:
            conn.execute("ALTER TABLE customers ADD COLUMN national_id TEXT")
    except Exception:
        pass
    try:
        dp_cols = {r[1] for r in conn.execute("PRAGMA table_info(debt_payments)").fetchall()}
        if 'payment_reference' not in dp_cols:
            conn.execute("ALTER TABLE debt_payments ADD COLUMN payment_reference TEXT")
        if 'reversed' not in dp_cols:
            conn.execute("ALTER TABLE debt_payments ADD COLUMN reversed INTEGER DEFAULT 0")
        if 'reversed_at' not in dp_cols:
            conn.execute("ALTER TABLE debt_payments ADD COLUMN reversed_at TEXT")
        if 'reversal_reason' not in dp_cols:
            conn.execute("ALTER TABLE debt_payments ADD COLUMN reversal_reason TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_debt_payment_reference "
            "ON debt_payments(invoice_id, payment_reference) "
            "WHERE payment_reference IS NOT NULL AND payment_reference != ''"
        )
    except Exception:
        pass
    # Notes: pin support
    try:
        note_cols = {r[1] for r in conn.execute("PRAGMA table_info(notes)").fetchall()}
        if 'pinned' not in note_cols:
            conn.execute("ALTER TABLE notes ADD COLUMN pinned INTEGER DEFAULT 0")
    except Exception:
        pass
    # Category visual management
    _ensure_categories_table(conn)
    # Enterprise accounting (double-entry) — offline SQLite
    try:
        from desktop.utils.accounting_engine import ensure_accounting_schema
        ensure_accounting_schema(conn)
    except Exception as _acc_err:
        logger.error('accounting schema: %s', _acc_err, exc_info=True)
    # Grant Accounting tab to managers / admins on upgrade
    for row in conn.execute(
        "SELECT id, role, tab_permissions FROM users "
        "WHERE role IN ('superadmin','admin','manager')"
    ).fetchall():
        try:
            import json as _json
            perms = _json.loads(row['tab_permissions'] or '[]')
            if 'accounting' not in perms:
                if 'reports' in perms:
                    perms.insert(perms.index('reports'), 'accounting')
                else:
                    perms.append('accounting')
                conn.execute(
                    "UPDATE users SET tab_permissions=? WHERE id=?",
                    (_json.dumps(perms), row['id']),
                )
        except Exception:
            pass
    conn.commit()
    # Cloud backup sync columns (non-breaking) + change log hook table
    try:
        from backend.cloud_backup.sync_manager import ensure_change_log_table
        ensure_change_log_table(conn)
        for table in ('products', 'sales', 'customers'):
            try:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            except Exception:
                continue
            for col, ddl in (
                ('sync_id', f"ALTER TABLE {table} ADD COLUMN sync_id TEXT"),
                ('sync_status', f"ALTER TABLE {table} ADD COLUMN sync_status TEXT DEFAULT 'local'"),
            ):
                if col not in cols:
                    try:
                        conn.execute(ddl)
                    except Exception:
                        pass
            if table == 'customers' and 'updated_at' not in cols:
                try:
                    conn.execute(
                        "ALTER TABLE customers ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP")
                except Exception:
                    pass
            if table == 'sales' and 'updated_at' not in cols:
                try:
                    conn.execute(
                        "ALTER TABLE sales ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP")
                except Exception:
                    pass
        conn.commit()
    except Exception:
        pass


def _ensure_categories_table(conn: sqlite3.Connection):
    """Create categories table, migrate visual columns, seed from product names."""
    conn.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT,
        visual_type TEXT DEFAULT 'icon',
        icon_name TEXT,
        image_path TEXT,
        accent_color TEXT DEFAULT '#3B82F6',
        sort_order INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(categories)").fetchall()}
    for col, ddl in (
        ('visual_type', "ALTER TABLE categories ADD COLUMN visual_type TEXT DEFAULT 'icon'"),
        ('icon_name', "ALTER TABLE categories ADD COLUMN icon_name TEXT"),
        ('image_path', "ALTER TABLE categories ADD COLUMN image_path TEXT"),
        ('accent_color', "ALTER TABLE categories ADD COLUMN accent_color TEXT DEFAULT '#3B82F6'"),
        ('description', "ALTER TABLE categories ADD COLUMN description TEXT"),
        ('sort_order', "ALTER TABLE categories ADD COLUMN sort_order INTEGER DEFAULT 0"),
        ('is_active', "ALTER TABLE categories ADD COLUMN is_active INTEGER DEFAULT 1"),
        ('updated_at', "ALTER TABLE categories ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP"),
    ):
        if col not in cols:
            try:
                conn.execute(ddl)
            except Exception:
                pass
    # Seed from distinct product categories + sensible defaults
    try:
        from desktop.utils.category_suggest import suggest_visual_for_category_name
    except Exception:
        suggest_visual_for_category_name = None
    names = set()
    try:
        for row in conn.execute(
            "SELECT DISTINCT category FROM products "
            "WHERE category IS NOT NULL AND TRIM(category) != ''"
        ).fetchall():
            names.add((row[0] or '').strip())
    except Exception:
        pass
    for default_name in (
        'General', 'Grocery', 'Pharmacy', 'Electronics', 'Clothing',
        'Hardware', 'Beverages', 'Beauty',
    ):
        names.add(default_name)
    for name in sorted(n for n in names if n):
        existing = conn.execute(
            "SELECT id, icon_name FROM categories WHERE LOWER(name)=LOWER(?)",
            (name,),
        ).fetchone()
        if existing:
            # Fill missing icon via smart match
            if not (existing['icon_name'] if isinstance(existing, sqlite3.Row)
                    else existing[1]) and suggest_visual_for_category_name:
                vis = suggest_visual_for_category_name(name)
                conn.execute(
                    "UPDATE categories SET icon_name=?, accent_color=?, "
                    "visual_type='icon', updated_at=? WHERE id=?",
                    (vis.get('icon_name'), vis.get('accent_color'),
                     datetime.now().isoformat(),
                     existing['id'] if isinstance(existing, sqlite3.Row) else existing[0]),
                )
            continue
        vis = suggest_visual_for_category_name(name) if suggest_visual_for_category_name else {
            'visual_type': 'icon',
            'icon_name': 'generic/general-product',
            'accent_color': '#3B82F6',
        }
        try:
            conn.execute(
                "INSERT INTO categories "
                "(name, visual_type, icon_name, accent_color, is_active) "
                "VALUES (?,?,?,?,1)",
                (name, vis.get('visual_type', 'icon'),
                 vis.get('icon_name'), vis.get('accent_color', '#3B82F6')),
            )
        except sqlite3.IntegrityError:
            pass


# ── Receipt number generator ────────────────────────────────────────────────────
def _sale_day_expr(alias: str = '') -> str:
    """SQL: business/reporting day for a sale (sale_date or date(created_at))."""
    from desktop.utils.shop_time import sale_day_sql
    return sale_day_sql(alias)


def _next_receipt(conn=None, business_day=None) -> str:
    """Generate the next receipt number for a business day (default: shop today).

    Accepts an optional open connection so it runs inside the caller's transaction,
    eliminating the race condition when two sales happen in the same second.
    """
    from desktop.utils.shop_time import business_day_iso, shop_today
    day_s = business_day_iso(business_day) if business_day else shop_today().isoformat()
    ymd = day_s.replace('-', '')
    close_after = conn is None
    db = conn if conn is not None else _db()
    try:
        day_expr = _sale_day_expr()
        count = db.execute(
            f"SELECT COUNT(*) FROM sales WHERE {day_expr}=?",
            (day_s,),
        ).fetchone()[0]
        return f"RCP-{ymd}-{count+1:04d}"
    finally:
        if close_after:
            db.close()


# ── Audit logger ────────────────────────────────────────────────────────────────
def _audit(user_id, username, action, module='system', details='', conn=None):
    try:
        own = conn is None
        db = conn if conn is not None else _db_light()
        db.execute(
            "INSERT INTO audit_log (user_id,username,action,module,details) VALUES (?,?,?,?,?)",
            (user_id, username, action, module, details)
        )
        if own:
            db.commit()
            db.close()
    except Exception as e:
        logger.warning(f"Audit log: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# APIClient — drop-in replacement for the HTTP version
# Same method signatures, same return shapes. Just uses SQLite directly.
# ══════════════════════════════════════════════════════════════════════════════

class APIClient:
    def __init__(self, base_url=None):
        # base_url ignored — kept for compatibility with call sites
        self.token     = None
        self._user_id  = None
        self._username = None
        self._role     = None

    def set_token(self, token: str):
        """Decode the JWT token to extract user context."""
        self.token = token
        try:
            payload    = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            self._user_id  = payload.get('user_id')
            self._username = payload.get('username')
            self._role     = payload.get('role')
        except Exception as e:
            logger.warning(f"Token decode: {e}")

    # ── Generic HTTP-compatible helpers (ignored in direct mode) ────────────────
    def get(self, path, params=None):
        """Route GET-style calls to internal methods."""
        return self._route('GET', path, params=params)

    def post(self, path, data=None):
        return self._route('POST', path, data=data)

    def put(self, path, data=None):
        return self._route('PUT', path, data=data)

    def delete(self, path):
        return self._route('DELETE', path)

    def _route(self, method, path, data=None, params=None):
        """Internal router — maps HTTP-style paths to direct DB methods."""
        try:
            # Settings
            if path == '/api/settings' and method == 'GET':
                return self.get_settings()
            if path == '/api/settings' and method == 'PUT':
                return self.update_settings(data or {})
            if path == '/api/health':
                return {'status': 'ok', 'time': datetime.now().isoformat()}
            # Audit
            if path == '/api/audit':
                return self.get_audit_log()
            # Users
            if path == '/api/users' and method == 'GET':
                return self.get_users()
            if path == '/api/users' and method == 'POST':
                return self.create_user(data or {})
            # Products
            if path == '/api/products' and method == 'GET':
                return self.get_products()
            if path == '/api/products' and method == 'POST':
                return self.create_product(data or {})
            # Categories
            if path == '/api/categories' and method == 'GET':
                return self.get_categories()
            if path == '/api/categories' and method == 'POST':
                return self.create_category(data or {})
            # Notes
            if path == '/api/notes' and method == 'GET':
                return self.get_notes()
            if path == '/api/notes' and method == 'POST':
                return self.create_note(data or {})
            # Reports
            if path == '/api/reports/summary' and params:
                return self.get_report_summary(
                    params.get('start', str(date.today())),
                    params.get('end',   str(date.today()))
                )
            # Parametric paths
            import re
            m = re.match(r'/api/users/(\d+)', path)
            if m:
                uid = int(m.group(1))
                if method == 'PUT':   return self.update_user(uid, data or {})
                if method == 'DELETE': return self.delete_user(uid)
            m = re.match(r'/api/products/(\d+)', path)
            if m:
                pid = int(m.group(1))
                if method == 'PUT':    return self.update_product(pid, data or {})
                if method == 'DELETE': return self.delete_product(pid)
            m = re.match(r'/api/categories/(\d+)', path)
            if m:
                cid = int(m.group(1))
                if method == 'PUT':    return self.update_category(cid, data or {})
                if method == 'DELETE': return self.delete_category(cid)
                if method == 'GET':    return self.get_category(cid)
            m = re.match(r'/api/sales/(\d+)', path)
            if m:
                return self.get_sale(int(m.group(1)))
            m = re.match(r'/api/notes/(\d+)', path)
            if m:
                nid = int(m.group(1))
                if method == 'PUT':    return self.update_note(nid, data or {})
                if method == 'DELETE': return self.delete_note(nid)
            if path == '/api/sales' and method == 'GET':
                return self.get_sales(**(params or {}))
            logger.warning(f"Unrouted: {method} {path}")
            return None
        except Exception as e:
            logger.error(f"Route {method} {path}: {e}")
            return None

    # ── AUTH ────────────────────────────────────────────────────────────────────

    def login(self, username: str, password: str) -> dict:
        import time
        # Case-insensitive username match (Admin == admin == ADMIN)
        uname = (username or '').strip()
        key = uname.lower() or '__empty__'
        now = time.time()

        db = _db()
        try:
            # Merge DB-persisted lockout into process cache (survives restart)
            if key not in _LOGIN_ATTEMPTS:
                persisted = _lockout_load_from_db(db)
                if key in persisted:
                    _LOGIN_ATTEMPTS[key] = dict(persisted[key])
                # Keep other usernames warm in cache too
                for k, v in persisted.items():
                    _LOGIN_ATTEMPTS.setdefault(k, dict(v))

            state = _LOGIN_ATTEMPTS.get(key) or {'fails': 0, 'locked_until': 0.0}
            locked_until = float(state.get('locked_until') or 0)
            if locked_until > now:
                retry_after = max(1, int(locked_until - now + 0.999))
                return {
                    'error': f'Too many failed attempts. Try again in {retry_after}s.',
                    'locked': True,
                    'retry_after': retry_after,
                }

            user = _row(db.execute(
                "SELECT * FROM users WHERE LOWER(username)=LOWER(?) AND is_active=1",
                (uname,),
            ))
            if not user or not _check_pw(password, user['password_hash']):
                fails = int(state.get('fails') or 0) + 1
                if fails >= LOGIN_MAX_FAILED_ATTEMPTS:
                    _LOGIN_ATTEMPTS[key] = {
                        'fails': 0,
                        'locked_until': now + LOGIN_LOCKOUT_SECONDS,
                    }
                else:
                    _LOGIN_ATTEMPTS[key] = {
                        'fails': fails,
                        'locked_until': 0.0,
                    }
                _lockout_save_to_db(db, dict(_LOGIN_ATTEMPTS))
                if fails >= LOGIN_MAX_FAILED_ATTEMPTS:
                    return {
                        'error': (
                            f'Too many failed attempts. '
                            f'Locked for {LOGIN_LOCKOUT_SECONDS}s.'
                        ),
                        'locked': True,
                        'retry_after': LOGIN_LOCKOUT_SECONDS,
                    }
                remaining = LOGIN_MAX_FAILED_ATTEMPTS - fails
                return {
                    'error': 'Invalid credentials',
                    'attempts_remaining': remaining,
                }

            # Successful login clears lockout for this username
            if key in _LOGIN_ATTEMPTS:
                _LOGIN_ATTEMPTS.pop(key, None)
                _lockout_save_to_db(db, dict(_LOGIN_ATTEMPTS))

            db.execute("UPDATE users SET last_login=? WHERE id=?",
                       (datetime.now().isoformat(), user['id']))
            db.commit()

            token = jwt.encode({
                'user_id':  user['id'],
                'username': user['username'],
                'role':     user['role'],
                'exp':      time.time() + 86400 * 7,
            }, SECRET_KEY, algorithm='HS256')

            perms = json.loads(user.get('tab_permissions') or '[]')
            till_session_id = None
            try:
                from desktop.utils.account_sessions import open_till_session
                till_session_id = open_till_session(db, user)
                db.commit()
            except Exception:
                logger.exception('till session')
            self._till_session_id = till_session_id
            result = {
                'token': token,
                'till_session_id': till_session_id,
                'user': {
                    'id':              user['id'],
                    'username':        user['username'],
                    'full_name':       user['full_name'],
                    'role':            user['role'],
                    'tab_permissions': perms,
                }
            }
            # Apply session context immediately (desktop login also calls set_token)
            try:
                self.set_token(token)
            except Exception:
                pass
            return result
        finally:
            db.close()

    def poll_till_logout(self) -> bool:
        """True when the dashboard has ended this till sign-in."""
        sid = getattr(self, '_till_session_id', None)
        if not sid:
            return False
        db = _db()
        try:
            from desktop.utils.account_sessions import take_till_end
            ended = take_till_end(db, int(sid))
            if ended:
                db.commit()
            return ended
        finally:
            db.close()

    def change_own_password(self, current_password: str, new_password: str,
                            confirm_password: str = '') -> dict:
        """Change the signed-in account. Requires the current password."""
        current_password = '' if current_password is None else str(current_password)
        new_password = '' if new_password is None else str(new_password)
        confirm_password = '' if confirm_password is None else str(confirm_password)
        if confirm_password and confirm_password != new_password:
            return {'error': 'New password and confirmation do not match.'}
        if len(new_password.strip()) < 6 or new_password != new_password.strip():
            return {'error': 'New password must be at least 6 characters.'}
        if not self._user_id:
            return {'error': 'Sign in before changing the password.', 'status': 401}
        db = _db()
        try:
            user = db.execute(
                "SELECT id, password_hash FROM users WHERE id=? AND is_active=1",
                (self._user_id,),
            ).fetchone()
            if not user or not _check_pw(current_password, user['password_hash']):
                return {'error': 'Current password is incorrect.'}
            db.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (_hash_pw(new_password), user['id']),
            )
            db.commit()
            _audit(self._user_id, self._username, 'PASSWORD_CHANGED', 'users', 'own account')
            return {'success': True}
        finally:
            db.close()

    def change_superadmin_pin(self, current_pin: str, new_pin: str, confirm_pin: str) -> dict:
        """Set or change the shop Super-Admin PIN. Superadmin only."""
        if (self._role or '').lower() != 'superadmin':
            return {'error': 'Only the superadmin can change the Super-Admin PIN.', 'status': 403}
        new_pin = '' if new_pin is None else str(new_pin).strip()
        confirm_pin = '' if confirm_pin is None else str(confirm_pin).strip()
        current_pin = '' if current_pin is None else str(current_pin).strip()
        if len(new_pin) < 6 or new_pin != confirm_pin:
            return {'error': 'Enter a new PIN of at least 6 characters and confirm it.'}
        if not new_pin.isdigit():
            return {'error': 'The Super-Admin PIN must be digits only.'}
        from desktop.utils.security import _pin_hash, set_superadmin_pin
        cfg = self.get_settings() or {}
        stored = str(cfg.get('superadmin_pin_hash') or '')
        if stored:
            blocked, retry_after = _pin_failures_blocked(self._user_id)
            if blocked:
                return {
                    'error': 'Too many PIN attempts. Wait and try again.',
                    'status': 429,
                    'retry_after': retry_after,
                }
            if not current_pin or _pin_hash(current_pin) != stored:
                _pin_failure_record(self._user_id)
                return {'error': 'Current Super-Admin PIN is incorrect.', 'status': 403}
            _pin_failures_clear(self._user_id)
        if not set_superadmin_pin(new_pin, self):
            return {'error': 'Could not save the Super-Admin PIN.'}
        _audit(self._user_id, self._username, 'SUPERADMIN_PIN_CHANGED', 'security', 'pin updated')
        return {'success': True}

    def reset_forgotten_admin_password(self, pin: str, target_username: str, new_password: str) -> dict:
        """Self-service emergency reset for admin/superadmin accounts using Super-Admin PIN."""
        if not pin or not pin.strip():
            return {'error': 'Super-Admin PIN is required.'}
        if not target_username or not target_username.strip():
            return {'error': 'Target username is required.'}
        if not new_password or len(new_password) < 6:
            return {'error': 'New password must be at least 6 characters.'}

        from desktop.utils.security import _pin_hash
        db = _db()
        try:
            recovery_key = f"pin:{target_username.strip().lower()}"
            locked = _recovery_lockout_status(db, recovery_key)
            if locked:
                return locked
            cfg_rows = db.execute("SELECT value FROM system_settings WHERE key='superadmin_pin_hash'").fetchone()
            stored_pin_hash = cfg_rows['value'] if cfg_rows else None
            if not stored_pin_hash:
                return {'error': 'Super-Admin PIN is not set on this system. Contact MugoByte support.'}

            if _pin_hash(pin.strip()) != stored_pin_hash:
                _record_recovery_attempt(db, recovery_key, False)
                _audit(None, 'SYSTEM', 'EMERGENCY_RESET_FAIL', 'security', f"target={target_username} invalid_pin")
                return {'error': 'Incorrect Super-Admin PIN.'}

            user = _row(db.execute(
                "SELECT id, username, role FROM users WHERE LOWER(username)=LOWER(?) AND is_active=1",
                (target_username.strip(),)
            ))
            if not user:
                return {'error': f"User '{target_username}' not found."}
            from roles import is_shop_admin_role
            if not is_shop_admin_role(user.get('role')):
                _audit(
                    user['id'], user['username'], 'EMERGENCY_RESET_FAIL',
                    'security', f"role={user['role']} target_not_admin")
                return {'error': 'Emergency recovery is limited to admin accounts.'}

            pw_hash = _hash_pw(new_password)
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, user['id']))
            db.commit()

            # Clear any failed login lockouts for this username
            key = target_username.strip().lower()
            if key in _LOGIN_ATTEMPTS:
                _LOGIN_ATTEMPTS.pop(key, None)
            _record_recovery_attempt(db, recovery_key, True)

            _audit(user['id'], user['username'], 'EMERGENCY_RESET_SUCCESS', 'security', f"role={user['role']} pin_authorized")
            return {'success': True, 'username': user['username']}
        finally:
            db.close()

    def reset_admin_via_license_key(self, license_key: str, target_username: str, new_password: str, new_pin: str = '') -> dict:
        """Emergency Tier-2 reset using the device's activation key (offline & online compatible)."""
        clean_key = (license_key or '').strip().upper()
        if not clean_key:
            return {'error': 'Activation License Key is required.'}
        if not target_username or not target_username.strip():
            return {'error': 'Target username is required.'}
        if not new_password or len(new_password) < 6:
            return {'error': 'New password must be at least 6 characters.'}

        recovery_key = f"license:{target_username.strip().lower()}"
        gate_db = _db()
        try:
            locked = _recovery_lockout_status(gate_db, recovery_key)
            if locked:
                return locked
        finally:
            gate_db.close()

        # Check local cryptographic license store binding
        from licensing.license_engine import LicenseEngine
        try:
            engine = LicenseEngine()
            engine_status = engine.get_status_dict()
            active_key = (engine_status.get('license_key') or '').strip().upper()
            
            # If engine doesn't have key directly in status, check store directly
            if not active_key:
                active_key = (engine.store.get('cloud_license_key') or '').strip().upper()

            # Compare provided key with the device's authenticated license key
            key_matched = False
            if active_key and clean_key == active_key:
                key_matched = True
            elif active_key and clean_key.replace('-', '') == active_key.replace('-', ''):
                key_matched = True

            # If local key didn't match directly, try cloud query only if local key is not present
            if not key_matched and not active_key:
                try:
                    from backend.cloud.platform_service import service_select
                    rows = service_select('licenses', f"license_key=eq.{clean_key}&is_active=eq.true")
                    if rows and len(rows) > 0:
                        # Ensure this device is in license_activations for this key
                        did = engine.device_id
                        acts = service_select('license_activations', f"license_id=eq.{rows[0]['id']}&is_active=eq.true")
                        for a in acts:
                            if a.get('device_id') == did or a.get('device_alias') == did:
                                key_matched = True
                                break
                except Exception:
                    pass

            if not key_matched:
                gate_db = _db()
                try:
                    _record_recovery_attempt(gate_db, recovery_key, False)
                finally:
                    gate_db.close()
                _audit(None, 'SYSTEM', 'LICENSE_KEY_RESET_FAIL', 'security', f"target={target_username} key_mismatch")
                return {'error': 'License key does not match the activation key for this PC.'}

            db = _db()
            try:
                user = _row(db.execute(
                    "SELECT id, username, role FROM users WHERE LOWER(username)=LOWER(?) AND is_active=1",
                    (target_username.strip(),)
                ))
                if not user:
                    return {'error': f"User '{target_username}' not found."}
                from roles import is_shop_admin_role
                if not is_shop_admin_role(user.get('role')):
                    _audit(
                        user['id'], user['username'], 'LICENSE_KEY_RESET_FAIL',
                        'security', f"role={user['role']} target_not_admin")
                    return {'error': 'Emergency recovery is limited to admin accounts.'}

                pw_hash = _hash_pw(new_password)
                db.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, user['id']))

                # If a new PIN was provided, update the Super-Admin PIN as well
                if (
                    new_pin and len(new_pin.strip()) >= 4
                    and (user.get('role') or '').strip().lower() == 'superadmin'
                ):
                    from desktop.utils.security import _pin_hash
                    p_hash = _pin_hash(new_pin.strip())
                    db.execute(
                        "INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)",
                        ('superadmin_pin_hash', p_hash, datetime.now().isoformat())
                    )

                db.commit()

                # Clear lockout
                key = target_username.strip().lower()
                if key in _LOGIN_ATTEMPTS:
                    _LOGIN_ATTEMPTS.pop(key, None)
                _record_recovery_attempt(db, recovery_key, True)

                _audit(user['id'], user['username'], 'LICENSE_KEY_RESET_SUCCESS', 'security', f"role={user['role']} key_authorized")
                return {'success': True, 'username': user['username']}
            finally:
                db.close()

        except Exception as e:
            logger.error(f"reset_admin_via_license_key: {e}")
            return {'error': f"Verification error: {e}"}

    # ── SETTINGS ────────────────────────────────────────────────────────────────

    def get_settings(self) -> dict:
        db = _db()
        try:
            rows = db.execute("SELECT key, value FROM system_settings").fetchall()
            return {r['key']: r['value'] for r in rows}
        finally:
            db.close()

    def update_settings(self, data: dict) -> dict:
        from backend.settings_guard import reject_privileged_settings, reject_secret_settings
        try:
            data = reject_secret_settings(data or {})
            data = reject_privileged_settings(data, self._role or '')
        except ValueError as exc:
            return {'success': False, 'error': str(exc)}
        db = _db()
        try:
            for k, v in data.items():
                db.execute(
                    "INSERT OR REPLACE INTO system_settings (key,value,updated_at) VALUES (?,?,?)",
                    (k, str(v), datetime.now().isoformat())
                )
            db.commit()
            _audit(self._user_id, self._username, 'UPDATE_SETTINGS', 'settings',
                   f"keys={list(data.keys())}")
            return {'success': True}
        finally:
            db.close()

    # ── USERS ────────────────────────────────────────────────────────────────────

    def get_users(self) -> list:
        db = _db()
        try:
            return _rows(db.execute(
                "SELECT id,username,full_name,role,email,is_active,"
                "tab_permissions,permission_grants,permission_denials,created_at,last_login FROM users"
            ))
        finally:
            db.close()

    def create_user(self, data: dict) -> dict:
        from roles import default_tab_permissions, can_assign_role, sanitize_tab_permissions
        actor_role = (self._role or 'cashier')
        new_role = data.get('role', 'cashier')
        if not can_assign_role(actor_role, new_role):
            return {'error': 'Only the shop owner (Super Admin) can assign the Super Admin role.'}
        db = _db()
        try:
            pw_hash = _hash_pw(data['password'])
            raw_perms = data.get('tab_permissions')
            if raw_perms is None:
                perms = default_tab_permissions(new_role)
            else:
                perms = sanitize_tab_permissions(new_role, raw_perms)
            perms_json = json.dumps(perms)
            db.execute(
                "INSERT INTO users (username,password_hash,role,full_name,email,tab_permissions)"
                " VALUES (?,?,?,?,?,?)",
                (data['username'], pw_hash, new_role,
                 data.get('full_name'), data.get('email'), perms_json)
            )
            db.commit()
            _audit(self._user_id, self._username, 'CREATE_USER', 'admin',
                   f"user={data['username']}")
            return {'success': True}
        except sqlite3.IntegrityError:
            return {'error': 'Username already exists'}
        finally:
            db.close()

    def update_user(self, uid: int, data: dict) -> dict:
        from roles import can_assign_role, sanitize_tab_permissions, is_superadmin_role
        db = _db()
        try:
            target = db.execute(
                "SELECT id, role FROM users WHERE id=?", (uid,)
            ).fetchone()
            if not target:
                return {'error': 'User not found'}
            actor_role = (self._role or 'cashier')
            new_role = data.get('role', target['role'])
            if not can_assign_role(actor_role, new_role):
                return {'error': 'Only the shop owner (Super Admin) can assign the Super Admin role.'}
            if not is_superadmin_role(actor_role) and is_superadmin_role(target['role']):
                return {'error': 'Only the shop owner can change a Super Admin account.'}
            if (
                'role' in data
                and (data.get('role') or '') != (target['role'] or '')
                and int(uid) == int(self._user_id or 0)
            ):
                return {'error': 'You cannot change your own role.', 'status': 400}
            if (
                not is_superadmin_role(actor_role)
                and (target['role'] or '').lower() == 'admin'
                and int(uid) != int(self._user_id or 0)
            ):
                return {'error': 'Only the shop owner can change another administrator.', 'status': 403}
            if 'is_active' in data:
                from desktop.utils.security import client_actor, has_permission
                if not has_permission(client_actor(self), 'users.delete'):
                    return {
                        'error': 'Only an administrator can remove a staff account.',
                        'status': 403,
                    }
                if data.get('is_active') in (0, '0', False) and int(uid) == int(self._user_id or 0):
                    return {'error': 'You cannot deactivate your own account.', 'status': 400}
            demoting = 'role' in data and not is_superadmin_role(data.get('role'))
            disabling = data.get('is_active') in (0, '0', False)
            if is_superadmin_role(target['role']) and (demoting or disabling):
                others = db.execute(
                    "SELECT COUNT(*) AS c FROM users "
                    "WHERE role='superadmin' AND is_active=1 AND id!=?",
                    (uid,),
                ).fetchone()['c']
                if int(others or 0) == 0:
                    return {
                        'error': 'The shop must keep one active Super Admin.',
                        'status': 400,
                    }
            fields, values = [], []
            for field in ('role','full_name','email','is_active'):
                if field in data:
                    fields.append(f"{field}=?"); values.append(data[field])
            if 'tab_permissions' in data:
                fields.append("tab_permissions=?")
                values.append(json.dumps(
                    sanitize_tab_permissions(new_role, data['tab_permissions'])
                ))
            if 'permission_grants' in data or 'permission_denials' in data:
                from desktop.utils.security import clean_permission_change
                if int(uid) == int(self._user_id or 0):
                    return {'error': 'You cannot change your own permissions.', 'status': 400}
                if is_superadmin_role(target['role']):
                    return {'error': 'Super Admin access follows that role.', 'status': 400}
                cleaned = clean_permission_change(
                    {'id': self._user_id, 'role': actor_role},
                    new_role,
                    data.get('permission_grants') or [],
                    data.get('permission_denials') or [],
                )
                if cleaned.get('error'):
                    return cleaned
                fields.append("permission_grants=?")
                values.append(json.dumps(cleaned['permission_grants']))
                fields.append("permission_denials=?")
                values.append(json.dumps(cleaned['permission_denials']))
            if 'password' in data:
                fields.append("password_hash=?")
                values.append(_hash_pw(data['password']))
            if fields:
                values.append(uid)
                db.execute(f"UPDATE users SET {','.join(fields)} WHERE id=?", values)
                db.commit()
            _audit(self._user_id, self._username, 'UPDATE_USER', 'admin', f"id={uid}")
            return {'success': True}
        finally:
            db.close()

    def delete_user(self, uid: int) -> dict:
        from roles import is_superadmin_role
        from desktop.utils.security import client_actor, has_permission
        actor_role = (self._role or '').lower()
        if not has_permission(client_actor(self), 'users.delete'):
            return {
                'error': 'Only an administrator can remove a staff account.',
                'status': 403,
            }
        if uid == self._user_id:
            return {'error': 'You cannot deactivate your own account.', 'status': 400}
        db = _db()
        try:
            target = db.execute(
                "SELECT role, is_active FROM users WHERE id=?", (uid,)
            ).fetchone()
            if target and is_superadmin_role(target['role']) and not is_superadmin_role(actor_role):
                return {
                    'error': 'Only the shop owner can change a Super Admin account.',
                    'status': 403,
                }
            if target and is_superadmin_role(target['role']) and int(target['is_active'] or 0) == 1:
                others = db.execute(
                    "SELECT COUNT(*) AS c FROM users "
                    "WHERE role='superadmin' AND is_active=1 AND id!=?",
                    (uid,),
                ).fetchone()['c']
                if int(others or 0) == 0:
                    return {
                        'error': 'The shop must keep one active Super Admin.',
                        'status': 400,
                    }
            db.execute("UPDATE users SET is_active=0 WHERE id=?", (uid,))
            db.commit()
            return {'success': True}
        finally:
            db.close()

    # ── CATEGORIES (visual management) ─────────────────────────────────────────

    def get_categories(self, active_only: bool = True) -> list:
        db = _db()
        try:
            q = "SELECT * FROM categories"
            if active_only:
                q += " WHERE is_active=1"
            q += " ORDER BY sort_order, name"
            return _rows(db.execute(q))
        finally:
            db.close()

    def get_category(self, cid: int) -> dict:
        db = _db()
        try:
            row = _row(db.execute("SELECT * FROM categories WHERE id=?", (cid,)))
            return row or {'error': 'Category not found'}
        finally:
            db.close()

    def get_category_by_name(self, name: str) -> dict:
        db = _db()
        try:
            return _row(db.execute(
                "SELECT * FROM categories WHERE LOWER(name)=LOWER(?)",
                ((name or '').strip(),),
            )) or {}
        finally:
            db.close()

    def categories_by_name_map(self) -> dict:
        """name -> category dict (also lower-case keys)."""
        out = {}
        for c in self.get_categories(active_only=False):
            n = c.get('name') or ''
            out[n] = c
            out[n.lower()] = c
        return out

    def create_category(self, data: dict) -> dict:
        name = (data.get('name') or '').strip()
        if not name:
            return {'error': 'Category name is required.'}
        from desktop.utils.category_suggest import suggest_visual_for_category_name
        vis = suggest_visual_for_category_name(name)
        vt = (data.get('visual_type') or vis.get('visual_type') or 'icon').lower()
        if vt not in ('icon', 'image'):
            vt = 'icon'
        icon_name = data.get('icon_name') or vis.get('icon_name')
        image_path = data.get('image_path')
        accent = data.get('accent_color') or vis.get('accent_color') or '#3B82F6'
        db = _db()
        try:
            db.execute(
                "INSERT INTO categories "
                "(name, description, visual_type, icon_name, image_path, "
                " accent_color, sort_order, is_active, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (name, data.get('description') or '',
                 vt, icon_name, image_path, accent,
                 int(data.get('sort_order') or 0), 1,
                 datetime.now().isoformat()),
            )
            cid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.commit()
            _audit(self._user_id, self._username, 'CREATE_CATEGORY', 'inventory',
                   f'category={name}')
            return _row(db.execute("SELECT * FROM categories WHERE id=?", (cid,)))
        except sqlite3.IntegrityError:
            return {'error': 'Category name already exists'}
        finally:
            db.close()

    def update_category(self, cid: int, data: dict) -> dict:
        db = _db()
        try:
            row = _row(db.execute("SELECT * FROM categories WHERE id=?", (cid,)))
            if not row:
                return {'error': 'Category not found'}
            name = (data.get('name') or row['name'] or '').strip()
            vt = (data.get('visual_type') or row.get('visual_type') or 'icon').lower()
            if vt not in ('icon', 'image'):
                vt = 'icon'
            fields = {
                'name': name,
                'description': data.get('description', row.get('description')),
                'visual_type': vt,
                'icon_name': data.get('icon_name', row.get('icon_name')),
                'image_path': data.get('image_path', row.get('image_path')),
                'accent_color': data.get('accent_color', row.get('accent_color')) or '#3B82F6',
                'sort_order': int(data.get('sort_order', row.get('sort_order') or 0)),
                'is_active': int(data.get('is_active', row.get('is_active', 1))),
                'updated_at': datetime.now().isoformat(),
            }
            old_name = row.get('name')
            db.execute(
                "UPDATE categories SET name=?, description=?, visual_type=?, "
                "icon_name=?, image_path=?, accent_color=?, sort_order=?, "
                "is_active=?, updated_at=? WHERE id=?",
                (fields['name'], fields['description'], fields['visual_type'],
                 fields['icon_name'], fields['image_path'], fields['accent_color'],
                 fields['sort_order'], fields['is_active'], fields['updated_at'], cid),
            )
            # Rename product.category free-text when category renamed
            if old_name and name and old_name != name:
                db.execute(
                    "UPDATE products SET category=? WHERE category=?",
                    (name, old_name),
                )
            db.commit()
            _audit(self._user_id, self._username, 'UPDATE_CATEGORY', 'inventory',
                   f'id={cid} name={name}')
            return _row(db.execute("SELECT * FROM categories WHERE id=?", (cid,)))
        except sqlite3.IntegrityError:
            return {'error': 'Category name already exists'}
        finally:
            db.close()

    def delete_category(self, cid: int) -> dict:
        db = _db()
        try:
            row = _row(db.execute("SELECT * FROM categories WHERE id=?", (cid,)))
            if not row:
                return {'error': 'Category not found'}
            db.execute("UPDATE categories SET is_active=0, updated_at=? WHERE id=?",
                       (datetime.now().isoformat(), cid))
            db.commit()
            return {'success': True}
        finally:
            db.close()

    def ensure_category_for_product_name(self, name: str) -> dict:
        """When saving a product with a new category string, ensure a categories row."""
        name = (name or '').strip()
        if not name:
            return {}
        existing = self.get_category_by_name(name)
        if existing:
            return existing
        return self.create_category({'name': name})

    # ── PRODUCTS ─────────────────────────────────────────────────────────────────

    def get_products(self) -> list:
        db = _db()
        try:
            # Narrow columns — SELECT * was a main-thread stall on large catalogs
            cols = {row[1] for row in db.execute("PRAGMA table_info(products)").fetchall()}
            image_sql = ", image_path" if "image_path" in cols else ""
            return _rows(db.execute(
                "SELECT id, name, sku, barcode, category, price, cost_price, "
                f"stock, min_stock, unit, is_active{image_sql} "
                "FROM products WHERE is_active=1 ORDER BY name"
            ))
        finally:
            db.close()

    def create_product(self, data: dict) -> dict:
        from desktop.utils.security import client_actor, has_permission
        role = (self._role or '').lower()
        known = ('cashier', 'viewer', 'manager', 'admin', 'superadmin')
        if role not in known or not has_permission(client_actor(self), 'inventory.create'):
            return {'error': 'You cannot add a product.', 'status': 403}
        name = (data.get('name') or '').strip()
        if not name:
            return {'error': 'Product name is required.'}
        cat_name = (data.get('category') or '').strip()
        result = None
        db = _db()
        try:
            initial_stock = round(float(data.get('stock', 0) or 0), 4)
            sku = (data.get('sku') or '').strip() or None
            db.execute(
                "INSERT INTO products (name,sku,category,price,cost_price,stock,min_stock,unit,barcode)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (name, sku, data.get('category'),
                 float(data.get('price') or 0), float(data.get('cost_price') or 0),
                 initial_stock, int(data.get('min_stock', 5) or 5),
                 data.get('unit') or 'pcs', data.get('barcode'))
            )
            pid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            if initial_stock > 0:
                try:
                    db.execute(
                        "INSERT INTO stock_movements "
                        "(product_id,product_name,movement_type,qty_before,qty_change,"
                        "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (pid, name, 'INITIAL', 0, initial_stock, initial_stock,
                         'PRODUCT_CREATE', 'Initial stock on product creation',
                         self._user_id, self._username or 'system')
                    )
                except Exception as e:
                    logger.warning(f"Stock movement log skipped: {e}")
                from desktop.utils.stock_layers import add_layer
                layer = add_layer(
                    db, pid, initial_stock, float(data.get('cost_price') or 0),
                    'opening', str(pid),
                    product_name=name,
                    purchase_unit_cost=float(data.get('cost_price') or 0),
                    extra_unit_cost=0,
                    supplier_name='Opening stock',
                    reference_note='Inherited from the product cost. Supplier unknown.',
                )
                if layer.get('error'):
                    db.rollback()
                    return {'error': layer['error']}
            db.commit()
            _audit(self._user_id, self._username, 'CREATE_PRODUCT', 'inventory',
                   f"name={name} stock={initial_stock}")
            result = {'success': True, 'id': pid, 'name': name}
        except sqlite3.IntegrityError as e:
            logger.warning(f"create_product integrity: {e}")
            msg = str(e).lower()
            if 'sku' in msg or 'unique' in msg:
                return {'error': 'A product with this SKU / code already exists.\n'
                                 'Use a different code or leave SKU blank.'}
            return {'error': 'This product could not be saved because it duplicates existing data.'}
        except Exception as e:
            logger.exception('create_product failed')
            return {'error': f'Could not save product: {e}'}
        finally:
            db.close()
        if result and cat_name:
            try:
                self.ensure_category_for_product_name(cat_name)
            except Exception:
                pass
        return result or {'error': 'Could not save product'}

    def save_product_image(self, product_id: int, source_path: str) -> dict:
        """Store a product photograph beside the shop database and link it."""
        from desktop.utils.product_photo import MAX_IMAGE_BYTES, image_error, sniff_image
        from desktop.utils.security import client_actor, has_permission
        role = (self._role or '').lower()
        known = ('cashier', 'viewer', 'manager', 'admin', 'superadmin')
        if role not in known or not has_permission(client_actor(self), 'inventory.edit_info'):
            return {'error': 'You cannot change a product photograph.', 'status': 403}
        source_path = (source_path or '').strip()
        if not source_path or not os.path.isfile(source_path):
            return {'error': 'Choose a photograph first.'}
        try:
            with open(source_path, 'rb') as handle:
                data = handle.read(MAX_IMAGE_BYTES + 1)
        except OSError:
            return {'error': 'That photograph could not be read.'}
        error = image_error(data)
        if error:
            return {'error': error}
        ext = sniff_image(data)
        from mbt_paths import get_data_dir
        folder = os.path.join(get_data_dir(), 'product-images')
        os.makedirs(folder, exist_ok=True)
        filename = f"product-{int(product_id)}{ext}"
        dest = os.path.join(folder, filename)
        for old_ext in ('.jpg', '.png', '.webp'):
            old = os.path.join(folder, f"product-{int(product_id)}{old_ext}")
            if old != dest and os.path.isfile(old):
                os.remove(old)
        with open(dest, 'wb') as handle:
            handle.write(data)
        db = _db()
        try:
            cols = {row[1] for row in db.execute("PRAGMA table_info(products)").fetchall()}
            if 'image_path' not in cols:
                db.execute("ALTER TABLE products ADD COLUMN image_path TEXT")
            changed = db.execute(
                "UPDATE products SET image_path=?, updated_at=? WHERE id=?",
                (filename, datetime.now().isoformat(), int(product_id)),
            )
            if changed.rowcount != 1:
                db.rollback()
                return {'error': 'Product not found.', 'status': 404}
            db.commit()
            _audit(self._user_id, self._username, 'PRODUCT_IMAGE', 'inventory',
                   f"pid={product_id} image={filename}")
            return {'success': True, 'image_path': filename}
        finally:
            db.close()

    def clear_product_image(self, product_id: int) -> dict:
        """Remove a product photograph and show the empty photo tile again."""
        from desktop.utils.security import client_actor, has_permission
        role = (self._role or '').lower()
        known = ('cashier', 'viewer', 'manager', 'admin', 'superadmin')
        if role not in known or not has_permission(client_actor(self), 'inventory.edit_info'):
            return {'error': 'You cannot change a product photograph.', 'status': 403}
        from mbt_paths import get_data_dir
        folder = os.path.join(get_data_dir(), 'product-images')
        for ext in ('.jpg', '.png', '.webp'):
            path = os.path.join(folder, f"product-{int(product_id)}{ext}")
            if os.path.isfile(path):
                os.remove(path)
        db = _db()
        try:
            changed = db.execute(
                "UPDATE products SET image_path=NULL, updated_at=? WHERE id=?",
                (datetime.now().isoformat(), int(product_id)),
            )
            if changed.rowcount != 1:
                db.rollback()
                return {'error': 'Product not found.', 'status': 404}
            db.commit()
            _audit(self._user_id, self._username, 'PRODUCT_IMAGE_CLEAR', 'inventory',
                   f"pid={product_id}")
            return {'success': True, 'image_path': ''}
        finally:
            db.close()

    def update_product(self, pid: int, data: dict, pin_verified=False) -> dict:
        """Update a product. Stock changes go through adjust_stock only."""
        from desktop.utils.security import client_actor, has_permission
        role = (self._role or '').lower()
        known = ('cashier', 'viewer', 'manager', 'admin', 'superadmin')
        if role not in known or not has_permission(client_actor(self), 'inventory.edit_info'):
            return {'error': 'You cannot change this product.', 'status': 403}
        if 'name' in data and not str(data.get('name') or '').strip():
            return {'error': 'Product name is required.', 'status': 400}
        for key in ('price', 'cost_price'):
            if key not in data:
                continue
            try:
                if float(data[key]) < 0:
                    return {'error': 'Price and cost cannot be negative.', 'status': 400}
            except (TypeError, ValueError):
                return {'error': 'Enter a valid price.', 'status': 400}
        db = _db()
        try:
            if 'stock' in data:
                return {
                    'error': 'Change stock through the protected Adjust Stock action.',
                    'status': 403,
                }

            # Get current values for audit trail
            old = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if not old:
                return {'error': 'Product not found.', 'status': 404}
            if 'is_active' in data:
                try:
                    new_active = 1 if int(data.get('is_active') or 0) else 0
                except (TypeError, ValueError):
                    return {'error': 'Enter a valid product status.', 'status': 400}
                old_active = 1 if int(old['is_active'] or 0) else 0
                if new_active != old_active and not has_permission(client_actor(self), 'inventory.delete'):
                    return {
                        'error': 'Only an administrator can remove a product.',
                        'status': 403,
                    }

            fields, values = [], []
            for field in ('name','sku','category','price','cost_price',
                          'min_stock','unit','barcode','is_active'):
                if field in data:
                    fields.append(f"{field}=?"); values.append(data[field])

            if fields:
                fields.append("updated_at=?"); values.append(datetime.now().isoformat())
                values.append(pid)
                db.execute(f"UPDATE products SET {','.join(fields)} WHERE id=?", values)
                db.commit()

            changes = []
            if old is not None:
                for key in ('name', 'sku', 'barcode', 'category', 'price', 'cost_price', 'unit', 'min_stock', 'is_active'):
                    if key not in data:
                        continue
                    before = old[key] if key in old.keys() else ''
                    after = data[key]
                    if key in ('price', 'cost_price', 'min_stock', 'is_active'):
                        try:
                            changed = float(before or 0) != float(after or 0)
                        except (TypeError, ValueError):
                            changed = str(before) != str(after)
                    else:
                        changed = str(before or '') != str(after or '')
                    if changed:
                        changes.append(f"{key} {before}->{after}")
            _audit(self._user_id, self._username, 'UPDATE_PRODUCT', 'inventory',
                   f"pid={pid} " + (", ".join(changes) or f"fields={list(data.keys())}"))
            result_ok = True
        except sqlite3.IntegrityError as e:
            logger.warning(f"update_product integrity: {e}")
            msg = str(e).lower()
            if 'sku' in msg or 'unique' in msg:
                return {'error': 'Another product already uses this SKU / code.'}
            return {'error': 'Update failed: duplicate value.'}
        except Exception as e:
            logger.exception('update_product failed')
            return {'error': f'Could not update product: {e}'}
        finally:
            db.close()
        if result_ok and 'category' in data and (data.get('category') or '').strip():
            try:
                self.ensure_category_for_product_name(data['category'])
            except Exception:
                pass
        return {'success': True}

    def adjust_stock(self, pid: int, new_qty, reason: str = '',
                     fourth=None, *, pin=None, expected_stock=None,
                     idempotency_key: str = '') -> dict:
        """
        Super-admin stock adjustment.

        Absolute form: adjust_stock(product_id, new_quantity, reason, pin=...).
        Direction form: adjust_stock(product_id, 'add'|'remove'|'set', quantity, reason, pin=...).
        A reduction by anyone except the signed-in Super Admin requires the PIN.
        """
        from desktop.utils.security import client_actor, has_permission
        if not has_permission(client_actor(self), 'inventory.adjust_stock'):
            return {
                'error': 'Only Super-Admin can adjust stock quantities.',
                'status': 403,
            }
        direction = None
        absolute = None
        if isinstance(new_qty, str):
            direction = new_qty.strip().lower()
            quantity = reason
            reason = '' if fourth is None else fourth
        else:
            absolute = new_qty
            quantity = None
            if fourth not in (None, '') and expected_stock is None:
                expected_stock = fourth
        return self._apply_stock_adjustment(
            pid, direction, quantity, absolute, str(reason or ''),
            pin=pin, expected_stock=expected_stock,
            idempotency_key=idempotency_key,
        )

    def _apply_stock_adjustment(self, pid, direction, quantity, absolute, reason, *,
                                pin, expected_stock, idempotency_key='') -> dict:
        import math
        from desktop.utils.option_lists import (
            STOCK_DECREASE_REASONS, STOCK_INCREASE_REASONS,
        )
        from desktop.utils.security import _pin_hash

        def _number(value):
            rounded = round(float(value), 4)
            if abs(rounded - round(rounded)) < 1e-9:
                return int(round(rounded))
            return rounded

        def _qty_text(value) -> str:
            return f'{float(value):.4f}'.rstrip('0').rstrip('.') or '0'

        reason = str(reason or '').strip()
        if direction is not None and direction not in ('add', 'remove', 'set'):
            return {'error': 'Choose add, remove, or set.', 'status': 400}
        try:
            amount = round(float(quantity if direction else absolute), 4)
        except (TypeError, ValueError):
            return {'error': 'Enter a valid stock quantity.', 'status': 400}
        if not math.isfinite(amount):
            return {'error': 'Enter a valid stock quantity.', 'status': 400}
        if direction in ('add', 'remove') and amount <= 0:
            return {'error': 'Enter a quantity greater than zero.', 'status': 400}
        if direction == 'set' and (amount < 0 or amount > 999999):
            return {'error': 'Stock quantity is outside the allowed range.', 'status': 400}
        if direction is None and (amount < 0 or amount > 999999):
            return {'error': 'Stock quantity is outside the allowed range.', 'status': 400}
        if not reason:
            return {'error': 'A reason is required for stock adjustments.', 'status': 400}

        db = _db()
        try:
            row = db.execute(
                "SELECT id, name, stock, cost_price FROM products WHERE id=?", (pid,)
            ).fetchone()
            if not row:
                return {'error': 'Product not found', 'status': 404}
            old_stock = round(float(row['stock'] or 0), 4)
            if direction == 'add':
                new_stock = round(old_stock + amount, 4)
                signed = amount
            elif direction == 'remove':
                new_stock = round(old_stock - amount, 4)
                signed = -amount
            else:
                new_stock = amount
                signed = round(new_stock - old_stock, 4)
            if new_stock < 0 or new_stock > 999999:
                return {'error': 'Stock quantity is outside the allowed range.', 'status': 400}
            if abs(signed) < 1e-9:
                return {'success': True, 'no_op': True, 'old_stock': _number(old_stock),
                        'new_stock': _number(old_stock)}
            if (
                expected_stock is not None
                and round(float(expected_stock), 4) != old_stock
            ):
                return {
                    'error': 'Stock changed. Refresh and review the latest quantity.',
                    'current_stock': _number(old_stock),
                    'status': 409,
                }
            decreasing = signed < 0
            if direction is not None:
                catalog = STOCK_DECREASE_REASONS if decreasing else STOCK_INCREASE_REASONS
                other = reason.startswith('Other:') and bool(reason[6:].strip())
                if reason not in catalog and not other:
                    return {'error': 'That reason does not match this stock change.', 'status': 400}
            if (self._role or '').lower() == 'superadmin':
                _audit(
                    self._user_id, self._username, 'SUPERADMIN_SESSION_AUTH', 'security',
                    f'stock_adjust pid={pid} pin_skipped=session',
                )
            elif decreasing:
                blocked, retry_after = _pin_failures_blocked(self._user_id)
                if blocked:
                    return {
                        'error': 'Too many PIN attempts. Wait and try again.',
                        'status': 429,
                        'retry_after': retry_after,
                    }
                stored = db.execute(
                    "SELECT value FROM system_settings WHERE key='superadmin_pin_hash'"
                ).fetchone()
                stored_hash = str(stored['value'] if stored else '')
                supplied = '' if pin is None else str(pin)
                if not supplied or not stored_hash or _pin_hash(supplied) != stored_hash:
                    _pin_failure_record(self._user_id)
                    _audit(
                        self._user_id, self._username, 'SUPERADMIN_PIN_FAIL', 'security',
                        f'stock_adjust pid={pid} result=fail',
                    )
                    message = (
                        'Incorrect Super-Admin PIN.'
                        if supplied else
                        'Super-Admin PIN is required to reduce stock.'
                    )
                    return {'error': message, 'status': 403}
                _pin_failures_clear(self._user_id)

            db.execute('BEGIN IMMEDIATE')
            movement_ref = (idempotency_key or '').strip() or f'ADJUST_pid={pid}'
            if (idempotency_key or '').strip():
                prior = db.execute(
                    "SELECT id FROM stock_movements WHERE reference=? LIMIT 1",
                    (movement_ref,),
                ).fetchone()
                if prior:
                    db.rollback()
                    return {'success': True, 'duplicate': True}
            current = db.execute(
                "SELECT COALESCE(stock,0) AS stock FROM products WHERE id=?", (pid,)
            ).fetchone()
            current_stock = round(float(current['stock'] if current else 0), 4)
            if current_stock != old_stock or (
                expected_stock is not None
                and round(float(expected_stock), 4) != current_stock
            ):
                db.rollback()
                return {
                    'error': 'Stock changed. Refresh and review the latest quantity.',
                    'current_stock': _number(current_stock),
                    'status': 409,
                }
            changed = db.execute(
                "UPDATE products SET stock=?, updated_at=? "
                "WHERE id=? AND COALESCE(stock,0)=?",
                (new_stock, datetime.now().isoformat(), pid, current_stock),
            )
            if changed.rowcount != 1:
                db.rollback()
                return {'error': 'Stock changed. Refresh and try again.', 'status': 409}
            db.execute(
                "INSERT INTO stock_movements "
                "(product_id,product_name,movement_type,qty_before,qty_change,"
                "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, row['name'], 'SUPERADMIN_ADJUST',
                 current_stock, signed, new_stock,
                 movement_ref, reason,
                 self._user_id, self._username or 'superadmin'),
            )
            mov_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            from desktop.utils.stock_layers import add_layer, consume_fifo
            if signed > 0:
                layer = add_layer(
                    db, pid, signed, float(row['cost_price'] or 0),
                    'adjust', str(mov_id),
                )
            else:
                layer = consume_fifo(db, pid, abs(signed), reference=movement_ref)
            if layer.get('error'):
                db.rollback()
                return {'error': layer['error'], 'status': 400}
            shown_direction = direction or ('remove' if decreasing else 'add')
            shown_qty = amount if direction in ('add', 'remove') else abs(signed)
            db.execute(
                "INSERT INTO audit_log (user_id,username,action,module,details) "
                "VALUES (?,?,?,?,?)",
                (self._user_id, self._username or 'superadmin', 'STOCK_ADJUSTED',
                 'inventory',
                 f"pid={pid} direction={shown_direction} quantity={_qty_text(shown_qty)} "
                 f"{_qty_text(current_stock)}→{_qty_text(new_stock)} reason={reason}"),
            )
            try:
                from desktop.utils.accounting_hooks import post_stock_adjust_journal
                posted = post_stock_adjust_journal(
                    db, product_id=pid, product_name=row['name'],
                    qty_change=signed, unit_cost=float(row['cost_price'] or 0),
                    reason=reason, movement_id=mov_id, user_id=self._user_id,
                    username=self._username or 'superadmin', safe=False)
            except Exception as journal_error:
                logger.error('stock adjust accounting: %s', journal_error, exc_info=True)
                db.rollback()
                return {'error': 'Could not post the stock adjustment.', 'status': 500}
            if (
                isinstance(posted, dict)
                and posted.get('error')
                and not posted.get('success')
                and not posted.get('skipped')
            ):
                db.rollback()
                return {'error': 'Could not post the stock adjustment.', 'status': 500}
            db.commit()
            return {
                'success': True,
                'old_stock': _number(current_stock),
                'new_stock': _number(new_stock),
            }
        except sqlite3.Error as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error('stock adjust failed: %s', exc, exc_info=True)
            return {'error': 'Could not adjust stock.', 'status': 500}
        finally:
            db.close()

    def get_suppliers(self, *, active_only: bool = True) -> list:
        db = _db()
        try:
            q = "SELECT * FROM suppliers"
            if active_only:
                q += " WHERE COALESCE(is_active,1)=1"
            q += " ORDER BY name COLLATE NOCASE"
            return _rows(db.execute(q))
        finally:
            db.close()

    def create_supplier(self, data: dict) -> dict:
        name = (data.get('name') or '').strip()
        if not name:
            return {'error': 'Supplier name is required.'}
        db = _db()
        try:
            db.execute(
                "INSERT INTO suppliers (name,phone,email,address,notes) VALUES (?,?,?,?,?)",
                (name, (data.get('phone') or '').strip(),
                 (data.get('email') or '').strip(),
                 (data.get('address') or '').strip(),
                 (data.get('notes') or '').strip()),
            )
            db.commit()
            sid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            _audit(self._user_id, self._username, 'CREATE_SUPPLIER', 'inventory',
                   f"id={sid} name={name}")
            return {'success': True, 'id': sid}
        finally:
            db.close()

    def update_supplier(self, sid: int, data: dict) -> dict:
        db = _db()
        try:
            fields, vals = [], []
            for f in ('name', 'phone', 'email', 'address', 'notes', 'is_active'):
                if f in data:
                    fields.append(f"{f}=?")
                    vals.append(data[f])
            if not fields:
                return {'error': 'No fields to update.'}
            fields.append("updated_at=?")
            vals.append(datetime.now().isoformat())
            vals.append(sid)
            db.execute(
                f"UPDATE suppliers SET {', '.join(fields)} WHERE id=?", vals)
            db.commit()
            return {'success': True}
        finally:
            db.close()

    def receive_stock(self, product_id: int, qty_add: float, *,
                      supplier_id: int = None, notes: str = '',
                      unit_cost: float = None, client_token: str = '') -> dict:
        """One product on a supplier delivery. Authorized roles, no extra PIN."""
        result = self.receive_delivery(
            supplier_id,
            [{'product_id': product_id, 'quantity': qty_add, 'unit_cost': unit_cost}],
            notes=notes,
            client_token=client_token,
        )
        if result.get('error'):
            return result
        line = (result.get('lines') or [{}])[0]
        return {
            'success': True,
            'duplicate': bool(result.get('duplicate')),
            'old_stock': line.get('old_stock'),
            'new_stock': line.get('new_stock'),
            'supplier_id': result.get('supplier_id'),
            'supplier_name': result.get('supplier_name'),
            'receipt_number': result.get('receipt_number'),
            'receipt_id': result.get('receipt_id'),
        }

    def receive_delivery(self, supplier_id, lines, *,
                         reference: str = '', notes: str = '',
                         client_token: str = '', payment_amount=0,
                         payment_method: str = '', payment_reference: str = '',
                         due_date: str = '', effective_date: str = '',
                         delivery_extra=None) -> dict:
        """One supplier delivery, many products, one receipt. Atomic."""
        if (self._role or '').lower() not in ('cashier', 'manager', 'admin', 'superadmin'):
            return {'error': 'You cannot receive supplier stock.'}
        try:
            supplier_id = int(supplier_id) if supplier_id not in (None, '', 0, '0') else None
        except (TypeError, ValueError):
            return {'error': 'Select a supplier.'}
        if not supplier_id:
            return {'error': 'Select a supplier.'}
        cleaned = []
        seen = set()
        for raw in lines or []:
            try:
                pid = int(raw.get('product_id'))
                qty = round(float(raw.get('quantity') or 0), 4)
            except (TypeError, ValueError, AttributeError):
                return {'error': 'Each line needs a product and a quantity.'}
            if qty != qty or qty <= 0 or qty > 999999:
                return {'error': 'Quantity to receive must be greater than zero.'}
            if pid in seen:
                return {'error': 'Each product can appear once on a delivery.'}
            seen.add(pid)
            cost = raw.get('unit_cost')
            try:
                cost = round(float(cost), 4) if cost not in (None, '') else None
            except (TypeError, ValueError):
                return {'error': 'Enter a valid purchase cost.'}
            if cost is not None and cost < 0:
                return {'error': 'Purchase cost cannot be negative.'}
            try:
                extra = round(float(raw.get('extra_unit_cost') or 0), 4)
            except (TypeError, ValueError):
                return {'error': 'Enter a valid extra delivery cost.'}
            if extra < 0:
                return {'error': 'Extra delivery cost cannot be negative.'}
            cleaned.append({
                'product_id': pid, 'quantity': qty,
                'unit_cost': cost, 'extra_unit_cost': extra,
            })
        if not cleaned:
            return {'error': 'Add at least one product.'}
        token = (client_token or '').strip()
        db = _db()
        try:
            sup = db.execute(
                "SELECT id, name FROM suppliers WHERE id=? AND COALESCE(is_active,1)=1",
                (supplier_id,),
            ).fetchone()
            if not sup:
                return {'error': 'Supplier not found'}
            supplier_name = sup['name'] or ''
            for _attempt in range(5):
                saved = self._write_delivery(
                    db, supplier_id, supplier_name, cleaned,
                    reference, notes, token, number_offset=_attempt,
                    payment_amount=payment_amount, payment_method=payment_method,
                    payment_reference=payment_reference, due_date=due_date,
                    effective_date=effective_date, delivery_extra=delivery_extra,
                )
                if saved.get('retry'):
                    continue
                return saved
            return {'error': 'Could not save that delivery. Try again.'}
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error('receive_delivery: %s', exc, exc_info=True)
            return {'error': 'Could not save that delivery.'}
        finally:
            db.close()

    def _write_delivery(self, db, supplier_id, supplier_name, cleaned,
                        reference, notes, token, number_offset=0, *,
                        payment_amount=0, payment_method='', payment_reference='',
                        due_date='', effective_date='', delivery_extra=None) -> dict:
        """Write one delivery. Returns retry=True when the receipt number collided."""
        try:
            db.execute("BEGIN IMMEDIATE")
            if token:
                prior = db.execute(
                    "SELECT id, receipt_number, grand_total FROM stock_receipts WHERE client_token=?",
                    (token,),
                ).fetchone()
                if prior:
                    db.rollback()
                    return {
                        'success': True, 'duplicate': True,
                        'receipt_id': prior['id'],
                        'receipt_number': prior['receipt_number'],
                        'grand_total': prior['grand_total'],
                        'supplier_id': supplier_id,
                        'supplier_name': supplier_name,
                    }
            day = datetime.now().strftime('%Y%m%d')
            prefix = f'RCV-{day}-'
            latest = db.execute(
                "SELECT receipt_number FROM stock_receipts WHERE receipt_number LIKE ? "
                "ORDER BY receipt_number DESC LIMIT 1",
                (prefix + '%',),
            ).fetchone()
            seq = 1
            if latest and latest['receipt_number']:
                tail = str(latest['receipt_number']).rsplit('-', 1)[-1]
                try:
                    seq = int(tail) + 1
                except ValueError:
                    seq = 1
            receipt_number = f"{prefix}{seq + int(number_offset):04d}"
            now = datetime.now().isoformat()
            ref_note = (reference or '').strip()
            note_txt = (notes or '').strip()
            reason = f'Received from Supplier: {supplier_name}'
            extra = ' — '.join(bit for bit in (ref_note, note_txt) if bit)
            if extra:
                reason = f'{reason} — {extra}'
            saved = []
            grand = 0.0
            from desktop.utils.stock_layers import add_layer, allocate_delivery_extra
            if delivery_extra is not None:
                preview = []
                for line in cleaned:
                    row = db.execute(
                        "SELECT cost_price FROM products WHERE id=?",
                        (line['product_id'],),
                    ).fetchone()
                    buy = line['unit_cost']
                    if buy is None and row is not None:
                        buy = round(float(row['cost_price'] or 0), 4)
                    preview.append({
                        'quantity': line['quantity'],
                        'unit_cost': buy,
                    })
                allocated = allocate_delivery_extra(preview, delivery_extra)
                if allocated.get('error'):
                    return allocated
                for line, share_line in zip(cleaned, preview):
                    line['extra_unit_cost'] = share_line['extra_unit_cost']
                grand_extra = round(float(allocated['total']), 2)
            else:
                grand_extra = 0.0
            for line in cleaned:
                row = db.execute(
                    "SELECT id, name, sku, unit, stock, cost_price, supplier_id, "
                    "COALESCE(is_active,1) AS is_active FROM products WHERE id=?",
                    (line['product_id'],),
                ).fetchone()
                if not row:
                    db.rollback()
                    return {'error': 'Product not found'}
                if not int(row['is_active'] or 0):
                    db.rollback()
                    return {'error': f"{row['name']} is not active."}
                old_stock = round(float(row['stock'] or 0), 4)
                new_stock = round(old_stock + line['quantity'], 4)
                unit_cost = line['unit_cost']
                if unit_cost is None:
                    unit_cost = round(float(row['cost_price'] or 0), 4)
                line_total = round(line['quantity'] * float(unit_cost), 2)
                grand = round(grand + line_total, 2)
                changed = db.execute(
                    "UPDATE products SET stock=?, updated_at=? WHERE id=? AND COALESCE(stock,0)=?",
                    (new_stock, now, row['id'], float(row['stock'] or 0)),
                )
                if changed.rowcount != 1:
                    db.rollback()
                    return {'error': 'Stock changed while this delivery was saving. Try again.'}
                if not row['supplier_id']:
                    db.execute(
                        "UPDATE products SET supplier_id=? WHERE id=?",
                        (supplier_id, row['id']),
                    )
                if line['unit_cost'] is not None:
                    db.execute(
                        "UPDATE products SET cost_price=? WHERE id=?",
                        (float(line['unit_cost']), row['id']),
                    )
                db.execute(
                    "INSERT INTO stock_movements "
                    "(product_id,product_name,movement_type,qty_before,qty_change,"
                    "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (row['id'], row['name'], 'PURCHASE',
                     old_stock, line['quantity'], new_stock,
                     f"RECEIVE_sup={supplier_id}|RCV={receipt_number}", reason,
                     self._user_id, self._username or self._role),
                )
                mov_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                extra_cost = round(float(line.get('extra_unit_cost') or 0), 4)
                landed = round(float(unit_cost) + extra_cost, 4)
                layer = add_layer(
                    db, row['id'], line['quantity'], landed,
                    'purchase', f'{receipt_number}:{row["id"]}',
                    supplier_id=supplier_id,
                    supplier_name=supplier_name,
                    reference_note=ref_note,
                    purchase_unit_cost=float(unit_cost),
                    extra_unit_cost=extra_cost,
                    product_name=row['name'],
                    username=self._username or self._role or '',
                )
                if layer.get('error'):
                    db.rollback()
                    return {'error': layer['error']}
                saved.append({
                    'product_id': row['id'], 'product_name': row['name'],
                    'sku': row['sku'] or '', 'unit': row['unit'] or '',
                    'quantity': line['quantity'], 'unit_cost': float(unit_cost),
                    'line_total': line_total, 'old_stock': old_stock,
                    'new_stock': new_stock, 'movement_id': mov_id,
                })
            from desktop.utils.supplier_payables import ensure_schema as _supplier_schema
            _supplier_schema(db)
            due = str(due_date or '').strip()[:10] or None
            effective = str(effective_date or '').strip()[:10] or now[:10]
            db.execute(
                "INSERT INTO stock_receipts "
                "(receipt_number,supplier_id,reference_note,notes,grand_total,"
                "user_id,username,client_token,created_at,status,due_date,effective_date) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (receipt_number, supplier_id, ref_note, note_txt, grand,
                 self._user_id, self._username or self._role, token or None, now, 'posted',
                 due, effective),
            )
            receipt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            for line in saved:
                db.execute(
                    "INSERT INTO stock_receipt_lines "
                    "(receipt_id,product_id,product_name,quantity,unit_cost,line_total,movement_id) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (receipt_id, line['product_id'], line['product_name'],
                     line['quantity'], line['unit_cost'], line['line_total'],
                     line['movement_id']),
                )
            paid_now = 0.0
            try:
                paid_now = round(float(payment_amount or 0), 2)
            except (TypeError, ValueError):
                db.rollback()
                return {'error': 'Enter a valid amount paid.'}
            if paid_now < 0:
                db.rollback()
                return {'error': 'Amount paid cannot be negative.'}
            payment = None
            if grand_extra:
                grand = round(grand + grand_extra, 2)
                db.execute(
                    "UPDATE stock_receipts SET grand_total=? WHERE id=?",
                    (grand, receipt_id),
                )
            if paid_now > 0:
                from desktop.utils.supplier_payables import apply_receipt_payment
                payment = apply_receipt_payment(
                    db, self, receipt_id, supplier_id, paid_now,
                    payment_method, payment_reference,
                )
            db.commit()
            _audit(self._user_id, self._username, 'RECEIVE_STOCK', 'inventory',
                   f"receipt={receipt_number} supplier={supplier_id} lines={len(saved)} total={grand}")
            outstanding = round(grand - min(paid_now, grand), 2)
            return {
                'success': True, 'receipt_id': receipt_id,
                'receipt_number': receipt_number, 'supplier_id': supplier_id,
                'supplier_name': supplier_name, 'reference': ref_note,
                'notes': note_txt, 'grand_total': grand, 'lines': saved,
                'amount_paid': round(min(paid_now, grand), 2),
                'outstanding': outstanding,
                'payment': payment,
            }
        except sqlite3.IntegrityError:
            try:
                db.rollback()
            except Exception:
                pass
            return {'retry': True}

    def list_stock_receipts(self, limit: int = 30) -> list:
        db = _db()
        try:
            rows = db.execute(
                "SELECT r.id, r.receipt_number, r.supplier_id, r.reference_note, r.notes, "
                "r.grand_total, r.username, r.created_at, COALESCE(r.status,'posted') AS status, "
                "r.due_date, r.effective_date, s.name AS supplier_name "
                "FROM stock_receipts r LEFT JOIN suppliers s ON s.id=r.supplier_id "
                "ORDER BY r.id DESC LIMIT ?",
                (int(limit),),
            )
            from desktop.utils.supplier_payables import annotate_receipts
            return annotate_receipts(db, _rows(rows))
        except Exception:
            return []
        finally:
            db.close()

    def get_stock_receipt(self, receipt_id: int) -> dict:
        db = _db()
        try:
            header = db.execute(
                "SELECT r.*, s.name AS supplier_name, s.phone AS supplier_phone "
                "FROM stock_receipts r LEFT JOIN suppliers s ON s.id=r.supplier_id "
                "WHERE r.id=?",
                (int(receipt_id),),
            ).fetchone()
            if not header:
                return {'error': 'Delivery was not found.'}
            lines = db.execute(
                "SELECT l.product_id, l.product_name, l.quantity, l.unit_cost, l.line_total, "
                "COALESCE(l.returned_qty,0) AS returned_qty, "
                "p.sku, p.unit, m.qty_before AS old_stock, m.qty_after AS new_stock "
                "FROM stock_receipt_lines l "
                "LEFT JOIN products p ON p.id=l.product_id "
                "LEFT JOIN stock_movements m ON m.id=l.movement_id "
                "WHERE l.receipt_id=? ORDER BY l.id",
                (header['id'],),
            ).fetchall()
            data = dict(header)
            data['status'] = data.get('status') or 'posted'
            data['lines'] = [dict(line) for line in lines]
            from desktop.utils.security import client_actor, redact_cost_fields, sees_product_cost
            if not sees_product_cost(client_actor(self)):
                redact_cost_fields(data)
            from desktop.utils.supplier_payables import receipt_money
            money_row = receipt_money(db, data['id'])
            if not money_row.get('error'):
                data.update({
                    'amount_paid': money_row.get('amount_paid'),
                    'outstanding': money_row.get('outstanding'),
                    'payment_status': money_row.get('payment_status'),
                    'payments': money_row.get('payments') or [],
                    'events': money_row.get('events') or [],
                    'effective_date': money_row.get('effective_date'),
                    'due_date': money_row.get('due_date') or data.get('due_date'),
                })
            return data
        finally:
            db.close()

    def record_supplier_payment(self, supplier_id, amount, *, method='cash', reference='',
                                notes='', mode='oldest', allocations=None,
                                client_token='', paid_at='') -> dict:
        from desktop.utils.supplier_payables import record_payment
        return record_payment(
            self, supplier_id, amount, method=method, reference=reference,
            notes=notes, mode=mode, allocations=allocations,
            client_token=client_token, paid_at=paid_at,
        )

    def supplier_payable_summary(self, start=None, end=None) -> dict:
        db = _db()
        try:
            from desktop.utils.supplier_payables import shop_summary
            return shop_summary(db, start, end)
        finally:
            db.close()

    def supplier_statement(self, supplier_id: int) -> dict:
        db = _db()
        try:
            from desktop.utils.supplier_payables import statement
            return statement(db, int(supplier_id))
        finally:
            db.close()

    def backdate_stock_receipt(self, receipt_id: int, effective_date: str, reason: str = '') -> dict:
        from desktop.utils.supplier_payables import backdate_receipt
        return backdate_receipt(self, receipt_id, effective_date, reason)

    def update_stock_receipt_header(self, receipt_id: int, *, reference=None, notes=None,
                                    due_date=None) -> dict:
        from desktop.utils.supplier_payables import update_receipt_header
        return update_receipt_header(
            self, receipt_id, reference=reference, notes=notes, due_date=due_date,
        )

    def request_delivery_action(self, receipt_id: int, kind: str, reason: str,
                                requested_date: str = '') -> dict:
        from desktop.utils.supplier_payables import request_delivery_action
        return request_delivery_action(self, receipt_id, kind, reason, requested_date)

    def list_delivery_requests(self, status: str = 'pending') -> list:
        db = _db()
        try:
            from desktop.utils.supplier_payables import list_delivery_requests
            return list_delivery_requests(db, status)
        finally:
            db.close()

    def review_delivery_request(self, request_id: int, decision: str, note: str = '',
                                pin: str = '') -> dict:
        from desktop.utils.supplier_payables import review_delivery_request
        return review_delivery_request(self, request_id, decision, note, pin)

    def return_receipt_line(self, receipt_id: int, product_id: int, quantity, *,
                            reason: str = '', pin: str = '', client_token: str = '') -> dict:
        from desktop.utils.supplier_payables import return_receipt_line
        return return_receipt_line(
            self, receipt_id, product_id, quantity, reason=reason, pin=pin,
            client_token=client_token,
        )

    def _stock_reduce_authorized(self, db, pin, action: str):
        """None when this user may reduce received stock. Otherwise an error dict."""
        role = (self._role or '').lower()
        if role not in ('admin', 'superadmin'):
            return {
                'error': 'Only an administrator can correct or reverse a supplier delivery.',
                'status': 403,
            }
        if role == 'superadmin':
            _audit(
                self._user_id, self._username, 'SUPERADMIN_SESSION_AUTH', 'security',
                f'{action} pin_skipped=session',
            )
            return None
        from desktop.utils.security import _pin_hash
        blocked, retry_after = _pin_failures_blocked(self._user_id)
        if blocked:
            return {
                'error': 'Too many PIN attempts. Wait and try again.',
                'status': 429, 'retry_after': retry_after,
            }
        stored = db.execute(
            "SELECT value FROM system_settings WHERE key='superadmin_pin_hash'"
        ).fetchone()
        stored_hash = str(stored['value'] if stored else '')
        supplied = '' if pin is None else str(pin)
        if not supplied or not stored_hash or _pin_hash(supplied) != stored_hash:
            _pin_failure_record(self._user_id)
            return {
                'error': 'Incorrect Super-Admin PIN.' if supplied else 'Super-Admin PIN is required.',
                'status': 403,
            }
        _pin_failures_clear(self._user_id)
        return None

    def _shift_purchase_layer(self, db, product_id, source_id, qty_delta, *,
                              unit_cost=None, close=False) -> dict:
        row = db.execute(
            "SELECT id, original_qty, remaining_qty, unit_cost FROM cost_layers "
            "WHERE product_id=? AND source_type='purchase' AND source_id=?",
            (int(product_id), str(source_id)),
        ).fetchone()
        if not row:
            return {'error': 'The cost record for this delivery line is missing.', 'status': 409}
        if close:
            take = round(abs(float(qty_delta)), 4)
            if float(row['remaining_qty'] or 0) + 0.0001 < take:
                return {
                    'error': 'Some of this delivery has already been sold, so it cannot be reversed.',
                    'status': 409,
                }
            changed = db.execute(
                "UPDATE cost_layers SET remaining_qty=remaining_qty-? WHERE id=? AND remaining_qty>=?",
                (take, row['id'], take),
            )
            if changed.rowcount != 1:
                return {'error': 'The cost record changed. Try again.', 'status': 409}
            return {'success': True, 'layer_id': row['id']}
        new_orig = round(float(row['original_qty'] or 0) + float(qty_delta), 4)
        new_rem = round(float(row['remaining_qty'] or 0) + float(qty_delta), 4)
        if new_orig <= 0.0001:
            return {
                'error': 'Reduce the line with a correction, or reverse the whole delivery.',
                'status': 400,
            }
        if new_rem < -0.0001:
            return {
                'error': 'Some of this delivery has already been sold, so it cannot be reduced by that much.',
                'status': 409,
            }
        cost = float(row['unit_cost'] or 0) if unit_cost is None else round(float(unit_cost), 4)
        db.execute(
            "UPDATE cost_layers SET original_qty=?, remaining_qty=?, unit_cost=? WHERE id=?",
            (new_orig, new_rem, cost, row['id']),
        )
        return {'success': True, 'layer_id': row['id']}

    def _refresh_displayed_cost(self, db, product_id) -> None:
        latest = db.execute(
            "SELECT unit_cost FROM cost_layers "
            "WHERE product_id=? AND source_type='purchase' AND remaining_qty>0.0001 "
            "ORDER BY id DESC LIMIT 1",
            (int(product_id),),
        ).fetchone()
        if latest:
            db.execute(
                "UPDATE products SET cost_price=? WHERE id=?",
                (float(latest[0]), int(product_id)),
            )

    def reverse_stock_receipt(self, receipt_id: int, *, reason: str = '',
                              pin: str = '', client_token: str = '') -> dict:
        """Put the received quantities back once. Does not create a second receipt."""
        db = _db()
        try:
            denied = self._stock_reduce_authorized(db, pin, 'reverse_receipt')
            if denied:
                return denied
            reason = (reason or '').strip() or 'Delivery reversed'
            token = (client_token or '').strip()
            db.execute("BEGIN IMMEDIATE")
            header = db.execute(
                "SELECT * FROM stock_receipts WHERE id=?", (int(receipt_id),)
            ).fetchone()
            if not header:
                db.rollback()
                return {'error': 'Delivery was not found.', 'status': 404}
            status = (header['status'] if 'status' in header.keys() else '') or 'posted'
            if status == 'reversed':
                db.rollback()
                return {'error': 'This delivery was already reversed.', 'status': 409}
            lines = db.execute(
                "SELECT * FROM stock_receipt_lines WHERE receipt_id=? ORDER BY id",
                (header['id'],),
            ).fetchall()
            if not lines:
                db.rollback()
                return {'error': 'This delivery has no products.', 'status': 409}
            now = datetime.now().isoformat()
            saved = []
            for line in lines:
                prod = db.execute(
                    "SELECT id, name, stock FROM products WHERE id=?",
                    (line['product_id'],),
                ).fetchone()
                if not prod:
                    db.rollback()
                    return {'error': 'Product not found', 'status': 404}
                qty = round(float(line['quantity'] or 0), 4)
                old_stock = round(float(prod['stock'] or 0), 4)
                new_stock = round(old_stock - qty, 4)
                if new_stock < -0.0001:
                    db.rollback()
                    return {
                        'error': f"Not enough {prod['name']} left to reverse this delivery.",
                        'status': 409,
                    }
                shifted = self._shift_purchase_layer(
                    db, prod['id'], f"{header['receipt_number']}:{prod['id']}",
                    -qty, close=True,
                )
                if shifted.get('error'):
                    db.rollback()
                    return shifted
                changed = db.execute(
                    "UPDATE products SET stock=?, updated_at=? WHERE id=? AND COALESCE(stock,0)=?",
                    (new_stock, now, prod['id'], float(prod['stock'] or 0)),
                )
                if changed.rowcount != 1:
                    db.rollback()
                    return {'error': 'Stock changed while reversing. Try again.', 'status': 409}
                self._refresh_displayed_cost(db, prod['id'])
                ref = f"REVERSE|{header['receipt_number']}|{prod['id']}"
                if token:
                    ref = f"REVERSE|{token}|{prod['id']}"
                db.execute(
                    "INSERT INTO stock_movements "
                    "(product_id,product_name,movement_type,qty_before,qty_change,"
                    "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (prod['id'], prod['name'], 'PURCHASE_REVERSAL',
                     old_stock, -qty, new_stock, ref,
                     f"Reversed {header['receipt_number']} — {reason}",
                     self._user_id, self._username or self._role),
                )
                saved.append({
                    'product_id': prod['id'], 'product_name': prod['name'],
                    'quantity': qty, 'old_stock': old_stock, 'new_stock': new_stock,
                })
            from desktop.utils.supplier_payables import release_allocations
            released = release_allocations(db, header['id'])
            changed = db.execute(
                "UPDATE stock_receipts SET status='reversed', reversed_at=?, void_reason=? "
                "WHERE id=? AND COALESCE(status,'posted')!='reversed'",
                (now, reason, header['id']),
            )
            if changed.rowcount != 1:
                db.rollback()
                return {'error': 'This delivery was already reversed.', 'status': 409}
            db.commit()
            _audit(self._user_id, self._username, 'REVERSE_STOCK_RECEIPT', 'inventory',
                   f"receipt={header['receipt_number']} lines={len(saved)}")
            return {
                'success': True, 'receipt_id': header['id'],
                'receipt_number': header['receipt_number'], 'lines': saved,
                'supplier_credit': released,
            }
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error('reverse_stock_receipt: %s', exc, exc_info=True)
            return {'error': 'Could not reverse that delivery.'}
        finally:
            db.close()

    def correct_stock_receipt_line(self, receipt_id: int, product_id: int, quantity, *,
                                   unit_cost=None, pin: str = '', reason: str = '') -> dict:
        """Change one received quantity. Stock moves by the difference only."""
        try:
            new_qty = round(float(quantity), 4)
        except (TypeError, ValueError):
            return {'error': 'Enter a valid quantity.', 'status': 400}
        if new_qty != new_qty or new_qty <= 0 or new_qty > 999999:
            return {'error': 'Quantity must be greater than zero.', 'status': 400}
        new_cost = None
        if unit_cost not in (None, ''):
            try:
                new_cost = round(float(unit_cost), 4)
            except (TypeError, ValueError):
                return {'error': 'Enter a valid purchase cost.', 'status': 400}
            if new_cost < 0:
                return {'error': 'Purchase cost cannot be negative.', 'status': 400}
        role = (self._role or '').lower()
        if role not in ('admin', 'superadmin'):
            return {
                'error': 'Only an administrator can correct a supplier delivery.',
                'status': 403,
            }
        db = _db()
        try:
            preview = db.execute(
                "SELECT l.quantity, l.unit_cost, COALESCE(r.status,'posted') AS status "
                "FROM stock_receipt_lines l JOIN stock_receipts r ON r.id=l.receipt_id "
                "WHERE l.receipt_id=? AND l.product_id=?",
                (int(receipt_id), int(product_id)),
            ).fetchone()
            if not preview:
                return {'error': 'That product is not on this delivery.', 'status': 404}
            if (preview['status'] or 'posted') == 'reversed':
                return {'error': 'A reversed delivery cannot be corrected.', 'status': 409}
            preview_delta = round(new_qty - round(float(preview['quantity'] or 0), 4), 4)
            if preview_delta < -0.0001:
                denied = self._stock_reduce_authorized(db, pin, 'correct_receipt')
                if denied:
                    return denied
            db.execute("BEGIN IMMEDIATE")
            header = db.execute(
                "SELECT * FROM stock_receipts WHERE id=?", (int(receipt_id),)
            ).fetchone()
            if not header:
                db.rollback()
                return {'error': 'Delivery was not found.', 'status': 404}
            if ((header['status'] if 'status' in header.keys() else '') or 'posted') == 'reversed':
                db.rollback()
                return {'error': 'A reversed delivery cannot be corrected.', 'status': 409}
            line = db.execute(
                "SELECT * FROM stock_receipt_lines WHERE receipt_id=? AND product_id=?",
                (header['id'], int(product_id)),
            ).fetchone()
            if not line:
                db.rollback()
                return {'error': 'That product is not on this delivery.', 'status': 404}
            old_qty = round(float(line['quantity'] or 0), 4)
            old_cost = round(float(line['unit_cost'] or 0), 4)
            cost = old_cost if new_cost is None else new_cost
            delta = round(new_qty - old_qty, 4)
            if abs(delta) < 0.0001 and abs(cost - old_cost) < 0.0001:
                db.rollback()
                return {'success': True, 'no_op': True, 'quantity': old_qty, 'unit_cost': old_cost}
            if delta < -0.0001 and preview_delta >= -0.0001:
                db.rollback()
                return {'error': 'The quantity changed. Review it and submit again.', 'status': 409}
            prod = db.execute(
                "SELECT id, name, stock FROM products WHERE id=?", (int(product_id),)
            ).fetchone()
            if not prod:
                db.rollback()
                return {'error': 'Product not found', 'status': 404}
            old_stock = round(float(prod['stock'] or 0), 4)
            new_stock = round(old_stock + delta, 4)
            if new_stock < -0.0001:
                db.rollback()
                return {'error': f"Not enough {prod['name']} left for that correction.", 'status': 409}
            source = f"{header['receipt_number']}:{prod['id']}"
            shifted = self._shift_purchase_layer(
                db, prod['id'], source, delta, unit_cost=cost,
            )
            if shifted.get('error'):
                db.rollback()
                return shifted
            now = datetime.now().isoformat()
            if abs(delta) >= 0.0001:
                changed = db.execute(
                    "UPDATE products SET stock=?, updated_at=? WHERE id=? AND COALESCE(stock,0)=?",
                    (new_stock, now, prod['id'], float(prod['stock'] or 0)),
                )
                if changed.rowcount != 1:
                    db.rollback()
                    return {'error': 'Stock changed while correcting. Try again.', 'status': 409}
            latest = db.execute(
                "SELECT id, source_id FROM cost_layers "
                "WHERE product_id=? AND source_type='purchase' ORDER BY id DESC LIMIT 1",
                (prod['id'],),
            ).fetchone()
            if latest and str(latest['source_id']) == source:
                db.execute(
                    "UPDATE products SET cost_price=? WHERE id=?",
                    (cost, prod['id']),
                )
            line_total = round(new_qty * cost, 2)
            db.execute(
                "UPDATE stock_receipt_lines SET quantity=?, unit_cost=?, line_total=? "
                "WHERE id=?",
                (new_qty, cost, line_total, line['id']),
            )
            total = db.execute(
                "SELECT COALESCE(SUM(line_total),0) FROM stock_receipt_lines WHERE receipt_id=?",
                (header['id'],),
            ).fetchone()[0]
            db.execute(
                "UPDATE stock_receipts SET grand_total=? WHERE id=?",
                (round(float(total or 0), 2), header['id']),
            )
            from desktop.utils.supplier_payables import trim_allocations
            trim_allocations(db, header['id'], round(float(total or 0), 2))
            if abs(delta) >= 0.0001:
                note = (reason or '').strip() or 'Delivery quantity corrected'
                db.execute(
                    "INSERT INTO stock_movements "
                    "(product_id,product_name,movement_type,qty_before,qty_change,"
                    "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (prod['id'], prod['name'], 'PURCHASE_CORRECTION',
                     old_stock, delta, new_stock,
                     f"CORRECT|{header['receipt_number']}|{prod['id']}|{now}",
                     f"Corrected {header['receipt_number']} from {old_qty:g} to {new_qty:g} — {note}",
                     self._user_id, self._username or self._role),
                )
            db.commit()
            _audit(self._user_id, self._username, 'CORRECT_STOCK_RECEIPT', 'inventory',
                   f"receipt={header['receipt_number']} product={prod['id']} {old_qty}->{new_qty}")
            return {
                'success': True, 'receipt_id': header['id'],
                'receipt_number': header['receipt_number'],
                'product_id': prod['id'], 'old_quantity': old_qty,
                'quantity': new_qty, 'delta': delta,
                'old_stock': old_stock, 'new_stock': new_stock,
                'unit_cost': cost, 'line_total': line_total,
                'grand_total': round(float(total or 0), 2),
            }
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error('correct_stock_receipt_line: %s', exc, exc_info=True)
            return {'error': 'Could not correct that delivery.'}
        finally:
            db.close()

    def request_stock_adjustment(self, product_id: int, requested_qty, reason: str) -> dict:
        """Cashier asks an administrator to change stock. Does not change stock."""
        if (self._role or '').lower() not in ('cashier', 'manager', 'admin', 'superadmin'):
            return {'error': 'You cannot request a stock adjustment.'}
        reason = (reason or '').strip()
        if not reason:
            return {'error': 'A reason is required.'}
        try:
            requested_qty = round(float(requested_qty), 4)
        except (TypeError, ValueError):
            return {'error': 'Enter a valid quantity.'}
        if requested_qty < 0:
            return {'error': 'Quantity cannot be negative.'}
        db = _db()
        try:
            row = db.execute(
                "SELECT id, name, stock FROM products WHERE id=?", (int(product_id),)
            ).fetchone()
            if not row:
                return {'error': 'Product not found'}
            day = datetime.now().strftime('%Y%m%d')
            count = db.execute(
                "SELECT COUNT(*) FROM stock_adjustment_requests WHERE request_number LIKE ?",
                (f'ADJ-{day}-%',),
            ).fetchone()[0]
            number = f"ADJ-{day}-{int(count) + 1:04d}"
            db.execute(
                "INSERT INTO stock_adjustment_requests "
                "(request_number,product_id,product_name,current_stock,requested_qty,"
                "reason,status,user_id,username) VALUES (?,?,?,?,?,?,?,?,?)",
                (number, row['id'], row['name'], float(row['stock'] or 0),
                 requested_qty, reason, 'pending', self._user_id, self._username or self._role),
            )
            request_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.commit()
            return {
                'success': True,
                'id': request_id,
                'request_number': number,
                'status': 'pending',
            }
        finally:
            db.close()

    def list_stock_adjustment_requests(self, status: str = '') -> list:
        db = _db()
        try:
            if status:
                rows = db.execute(
                    "SELECT * FROM stock_adjustment_requests WHERE status=? ORDER BY id DESC LIMIT 100",
                    (status,),
                )
            else:
                rows = db.execute(
                    "SELECT * FROM stock_adjustment_requests ORDER BY id DESC LIMIT 100"
                )
            return _rows(rows)
        except Exception:
            return []
        finally:
            db.close()

    def request_sale_void(self, sale_id: int, reason: str) -> dict:
        """Ask for a void. The sale stays completed until a manager approves it."""
        reason = (reason or '').strip()
        if not reason:
            return {'error': 'Enter a reason for the void request.', 'status': 400}
        if (self._role or '').lower() not in ('cashier', 'manager', 'admin', 'superadmin'):
            return {'error': 'You cannot request a void.', 'status': 403}
        db = _db()
        try:
            self._ensure_approval_table(db)
            sale = db.execute(
                "SELECT id, receipt_number, total, status FROM sales WHERE id=?",
                (int(sale_id),),
            ).fetchone()
            if not sale:
                return {'error': 'Sale was not found.', 'status': 404}
            if (sale['status'] or '').lower() != 'completed':
                return {'error': 'Only a completed sale can be sent for void.', 'status': 409}
            db.execute('BEGIN IMMEDIATE')
            open_rows = db.execute(
                "SELECT id, meta_json FROM cc_approvals "
                "WHERE type='void' AND status IN ('pending','escalated','executing')"
            ).fetchall()
            for open_row in open_rows:
                try:
                    open_meta = json.loads(open_row['meta_json'] or '{}')
                except json.JSONDecodeError:
                    open_meta = {}
                if not isinstance(open_meta, dict):
                    continue
                try:
                    open_sale = int(open_meta.get('sale_id') or 0)
                except (TypeError, ValueError):
                    open_sale = 0
                if open_sale == int(sale_id):
                    db.rollback()
                    return {
                        'success': True,
                        'duplicate': True,
                        'id': int(open_row['id']),
                        'sale_status': 'completed',
                    }
            now = datetime.now()
            db.execute(
                "INSERT INTO cc_approvals "
                "(type, title, details, amount, status, requested_by, requested_by_id, "
                "meta_json, created_at, expires_at) "
                "VALUES ('void', ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
                (
                    f"Void {sale['receipt_number']}",
                    reason,
                    float(sale['total'] or 0),
                    self._username or '',
                    self._user_id,
                    json.dumps({'sale_id': int(sale_id), 'receipt_number': sale['receipt_number']}),
                    now.isoformat(),
                    (now + timedelta(hours=24)).isoformat(),
                ),
            )
            approval_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.commit()
            still = db.execute(
                "SELECT status FROM sales WHERE id=?", (int(sale_id),)
            ).fetchone()['status']
            return {'success': True, 'id': approval_id, 'sale_status': still}
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error('void request failed: %s', exc, exc_info=True)
            return {'error': 'Could not save the void request.', 'status': 500}
        finally:
            db.close()

    def request_consumption_void(self, consumption_id: int, reason: str) -> dict:
        """Ask an admin to void internal consumption. Stock stays reduced until approval."""
        reason = (reason or '').strip()
        if not reason:
            return {'error': 'Enter a reason for the void request.', 'status': 400}
        if (self._role or '').lower() not in ('cashier', 'manager', 'admin', 'superadmin'):
            return {'error': 'You cannot request this void.', 'status': 403}
        db = _db()
        try:
            self._ensure_approval_table(db)
            cons = db.execute(
                "SELECT id, reference_no, total_cost, voided FROM stock_consumptions WHERE id=?",
                (int(consumption_id),),
            ).fetchone()
            if not cons:
                return {'error': 'Consumption was not found.', 'status': 404}
            if int(cons['voided'] or 0) == 1:
                return {'error': 'This consumption is already voided.', 'status': 409}
            db.execute('BEGIN IMMEDIATE')
            open_rows = db.execute(
                "SELECT id, meta_json FROM cc_approvals "
                "WHERE type='consumption_void' AND status IN ('pending','escalated','executing')"
            ).fetchall()
            for open_row in open_rows:
                try:
                    open_meta = json.loads(open_row['meta_json'] or '{}')
                except json.JSONDecodeError:
                    open_meta = {}
                if not isinstance(open_meta, dict):
                    continue
                try:
                    open_id = int(open_meta.get('consumption_id') or 0)
                except (TypeError, ValueError):
                    open_id = 0
                if open_id == int(consumption_id):
                    db.rollback()
                    return {
                        'success': True,
                        'duplicate': True,
                        'id': int(open_row['id']),
                        'status': 'pending',
                    }
            now = datetime.now().isoformat()
            db.execute(
                "INSERT INTO cc_approvals "
                "(type, title, details, amount, status, requested_by, requested_by_id, "
                "meta_json, created_at, updated_at) "
                "VALUES ('consumption_void', ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
                (
                    f"Void {cons['reference_no']}",
                    reason,
                    float(cons['total_cost'] or 0),
                    self._username or '',
                    self._user_id,
                    json.dumps({
                        'consumption_id': int(consumption_id),
                        'reference_no': cons['reference_no'],
                        'reason': reason,
                    }),
                    now,
                    now,
                ),
            )
            request_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.commit()
            return {
                'success': True,
                'id': int(request_id),
                'reference': cons['reference_no'],
                'status': 'pending',
            }
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error('consumption void request failed: %s', exc, exc_info=True)
            return {'error': 'Could not save the void request.', 'status': 500}
        finally:
            db.close()

    def _backdate_actor(self) -> dict:
        return {
            'id': self._user_id,
            'username': self._username or '',
            'full_name': self._username or '',
            'role': (self._role or '').lower(),
        }

    def _backdate(self, func, *args):
        from backend.backdate_requests import BackdateError
        db = _db()
        try:
            return func(db, self._backdate_actor(), *args)
        except BackdateError as exc:
            try:
                db.rollback()
            except Exception:
                pass
            return {'error': exc.message, 'status': exc.status}
        finally:
            db.close()

    def list_backdate_requests(self, filters=None) -> dict:
        from backend.backdate_requests import list_requests
        return self._backdate(list_requests, filters or {})

    def create_backdate_request(self, data: dict) -> dict:
        from backend.backdate_requests import create_request
        return self._backdate(create_request, data or {})

    def get_backdate_request(self, request_id: int) -> dict:
        from backend.backdate_requests import get_request
        return self._backdate(get_request, int(request_id))

    def update_backdate_request(self, request_id: int, data: dict) -> dict:
        from backend.backdate_requests import update_request
        return self._backdate(update_request, int(request_id), data or {})

    def submit_backdate_request(self, request_id: int, version=None) -> dict:
        from backend.backdate_requests import submit_request
        return self._backdate(submit_request, int(request_id), {'version': version})

    def withdraw_backdate_request(self, request_id: int, reason: str, version=None) -> dict:
        from backend.backdate_requests import withdraw_request
        return self._backdate(withdraw_request, int(request_id), {'reason': reason, 'version': version})

    def return_backdate_request(self, request_id: int, reason: str, version=None) -> dict:
        from backend.backdate_requests import return_request
        return self._backdate(return_request, int(request_id), {'reason': reason, 'version': version})

    def reject_backdate_request(self, request_id: int, reason: str, version=None) -> dict:
        from backend.backdate_requests import reject_request
        return self._backdate(reject_request, int(request_id), {'reason': reason, 'version': version})

    def approve_backdate_request(self, request_id: int, version=None, note: str = '') -> dict:
        from backend.backdate_requests import approve_request
        return self._backdate(approve_request, int(request_id), {'version': version, 'note': note})

    def list_requests_centre(self, filters=None) -> dict:
        from backend.requests_centre import list_centre
        return self._backdate(list_centre, filters or {})

    def get_requests_centre_item(self, source: str, source_id: int) -> dict:
        from backend.requests_centre import get_centre_item
        return self._backdate(get_centre_item, source, int(source_id))

    def execute_approval(self, approval_id: int, action: str, *, pin: str = '', note: str = '',
                         confirm_credit_payments: bool = False) -> dict:
        """Run a pending void or stock approval once. Reject and escalate do not."""
        action = (action or '').strip().lower()
        if action not in ('approve', 'reject', 'escalate'):
            return {'error': 'Unknown action', 'status': 400}
        if (self._role or '').lower() not in ('admin', 'superadmin', 'manager'):
            return {'error': 'Manager or admin access required', 'status': 403}
        db = _db()
        try:
            self._ensure_approval_table(db)
            preview = db.execute(
                "SELECT type, status FROM cc_approvals WHERE id=?",
                (int(approval_id),),
            ).fetchone()
            if action == 'approve' and preview:
                preview_type = (preview['type'] or '').lower()
                preview_status = (preview['status'] or '').lower()
                if (
                    preview_type in ('void', 'stock_adjust')
                    and preview_status in ('pending', 'escalated', 'executing')
                ):
                    pin_error = self._approval_pin_error(db, pin, int(approval_id))
                    if pin_error:
                        return pin_error
            db.execute('BEGIN IMMEDIATE')
            row = db.execute(
                "SELECT * FROM cc_approvals WHERE id=?", (int(approval_id),)
            ).fetchone()
            if not row:
                db.rollback()
                return {'error': 'Not found', 'status': 404}
            status = (row['status'] or '').lower()
            if action == 'approve' and status == 'approved':
                db.rollback()
                return {'success': True, 'duplicate': True, 'status': 'approved'}
            if status == 'expired':
                db.rollback()
                return {'error': 'This request has expired.', 'status': 410}
            if action == 'approve' and status in ('pending', 'escalated') and self._approval_is_expired(row):
                db.execute(
                    "UPDATE cc_approvals SET status='expired', updated_at=? "
                    "WHERE id=? AND status IN ('pending','escalated')",
                    (datetime.now().isoformat(), int(approval_id)),
                )
                db.commit()
                return {'error': 'This request has expired.', 'status': 410}
            if action != 'approve':
                if status not in ('pending', 'escalated'):
                    db.rollback()
                    return {'error': f'Already {row["status"]}', 'status': 400}
                new_status = 'rejected' if action == 'reject' else 'escalated'
                db.execute(
                    "UPDATE cc_approvals SET status=?, reviewed_by=?, reviewed_by_id=?, "
                    "review_note=?, updated_at=? WHERE id=? AND status IN ('pending','escalated')",
                    (new_status, self._username or '', self._user_id, note,
                     datetime.now().isoformat(), int(approval_id)),
                )
                db.commit()
                return {'success': True, 'status': new_status}
            if status not in ('pending', 'escalated', 'executing'):
                db.rollback()
                return {'error': f'Already {row["status"]}', 'status': 400}
            atype = (row['type'] or '').lower()
            if atype == 'consumption_void' and (self._role or '').lower() not in ('admin', 'superadmin'):
                db.rollback()
                return {'error': 'Only an admin can approve an internal-consumption void.', 'status': 403}
            try:
                requester_id = int(row['requested_by_id'] or 0)
            except (TypeError, ValueError):
                requester_id = 0
            if atype == 'consumption_void' and requester_id and requester_id == int(self._user_id or 0):
                db.rollback()
                return {'error': 'You cannot approve your own consumption void.', 'status': 403}
            if atype not in ('void', 'stock_adjust', 'consumption_void'):
                if status not in ('pending', 'escalated'):
                    db.rollback()
                    return {'error': f'Already {row["status"]}', 'status': 400}
                decided = db.execute(
                    "UPDATE cc_approvals SET status='approved', reviewed_by=?, "
                    "reviewed_by_id=?, review_note=?, updated_at=? "
                    "WHERE id=? AND status IN ('pending','escalated')",
                    (self._username or '', self._user_id, note,
                     datetime.now().isoformat(), int(approval_id)),
                )
                db.commit()
                if decided.rowcount != 1:
                    return {'error': 'Approval is already being processed.', 'status': 409}
                return {'success': True, 'status': 'approved', 'executed': False}
            if atype == 'stock_adjust' and (self._role or '').lower() != 'superadmin':
                db.rollback()
                return {'error': 'Only Super-Admin can apply a stock adjustment.', 'status': 403}
            claim = json.dumps({'claim': secrets.token_hex(8)})
            now = datetime.now().isoformat()
            if status in ('pending', 'escalated'):
                claimed = db.execute(
                    "UPDATE cc_approvals SET status='executing', reviewed_by=?, "
                    "reviewed_by_id=?, review_note=?, updated_at=?, execution_json=? "
                    "WHERE id=? AND status IN ('pending','escalated')",
                    (self._username or '', self._user_id, note, now, claim, int(approval_id)),
                )
            else:
                stale_before = (datetime.now() - timedelta(seconds=_APPROVAL_CLAIM_SECONDS)).isoformat()
                claimed = db.execute(
                    "UPDATE cc_approvals SET reviewed_by=?, reviewed_by_id=?, "
                    "updated_at=?, execution_json=? "
                    "WHERE id=? AND status='executing' AND (updated_at IS NULL OR updated_at < ?)",
                    (self._username or '', self._user_id, now, claim,
                     int(approval_id), stale_before),
                )
            if claimed.rowcount != 1:
                current = db.execute(
                    "SELECT status FROM cc_approvals WHERE id=?", (int(approval_id),)
                ).fetchone()
                db.rollback()
                if current and (current['status'] or '').lower() == 'approved':
                    return {'success': True, 'duplicate': True, 'status': 'approved'}
                return {'error': 'Approval is already being processed.', 'status': 409}
            db.commit()
            meta_raw = row['meta_json'] or '{}'
        except sqlite3.Error as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error('approval claim failed: %s', exc, exc_info=True)
            return {'error': 'Could not claim the approval.', 'status': 500}
        finally:
            db.close()
        try:
            meta = json.loads(meta_raw or '{}')
        except json.JSONDecodeError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        result = self._run_approved_action(
            atype, meta, note or row['details'] or '', pin, int(approval_id),
            confirm_credit_payments=bool(confirm_credit_payments)
            and (self._role or '').lower() == 'superadmin',
        )
        finished = self._finish_approval(int(approval_id), result)
        if finished.get('success'):
            finished['result'] = {
                'success': bool(result.get('success') or result.get('duplicate')),
                'duplicate': bool(result.get('duplicate')),
            }
        return finished

    def _ensure_approval_table(self, db) -> None:
        db.execute(
            """CREATE TABLE IF NOT EXISTS cc_approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                details TEXT DEFAULT '',
                amount REAL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_by TEXT DEFAULT '',
                requested_by_id INTEGER,
                reviewed_by TEXT DEFAULT '',
                reviewed_by_id INTEGER,
                review_note TEXT DEFAULT '',
                meta_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT,
                execution_json TEXT DEFAULT ''
            )"""
        )
        cols = {item[1] for item in db.execute("PRAGMA table_info(cc_approvals)")}
        if 'expires_at' not in cols:
            db.execute("ALTER TABLE cc_approvals ADD COLUMN expires_at TEXT")
        if 'execution_json' not in cols:
            db.execute("ALTER TABLE cc_approvals ADD COLUMN execution_json TEXT DEFAULT ''")

    def _approval_is_expired(self, row) -> bool:
        raw = ''
        try:
            raw = str(row['expires_at'] or '')
        except (KeyError, IndexError):
            raw = ''
        if not raw:
            created = str(row['created_at'] or '')
            if not created:
                return True
            try:
                start = datetime.fromisoformat(created.replace('Z', ''))
            except ValueError:
                return True
            deadline = start + timedelta(hours=24)
        else:
            try:
                deadline = datetime.fromisoformat(raw.replace('Z', ''))
            except ValueError:
                return True
        return datetime.now() > deadline

    def _approval_pin_error(self, db, pin: str, approval_id: int):
        if (self._role or '').lower() == 'superadmin':
            _audit(
                self._user_id, self._username, 'SUPERADMIN_SESSION_AUTH', 'security',
                f'approval id={approval_id} pin_skipped=session',
            )
            return None
        from desktop.utils.security import _pin_hash
        blocked, retry_after = _pin_failures_blocked(self._user_id)
        if blocked:
            return {
                'error': 'Too many PIN attempts. Wait and try again.',
                'status': 429,
                'retry_after': retry_after,
            }
        stored = db.execute(
            "SELECT value FROM system_settings WHERE key='superadmin_pin_hash'"
        ).fetchone()
        stored_hash = str(stored['value'] if stored else '')
        supplied = '' if pin is None else str(pin)
        if not supplied or not stored_hash or _pin_hash(supplied) != stored_hash:
            _pin_failure_record(self._user_id)
            _audit(
                self._user_id, self._username, 'SUPERADMIN_PIN_FAIL', 'security',
                f'approval id={approval_id} result=fail',
            )
            message = (
                'Incorrect Super-Admin PIN.'
                if supplied else
                'Super-Admin PIN is required.'
            )
            return {'error': message, 'status': 403}
        _pin_failures_clear(self._user_id)
        return None

    def _run_approved_action(self, atype: str, meta: dict, note: str, pin: str = '',
                             approval_id: int = 0, confirm_credit_payments: bool = False) -> dict:
        if atype == 'void':
            try:
                sale_id = int(meta.get('sale_id') or 0)
            except (TypeError, ValueError):
                return {'error': 'The void request has no sale.'}
            if sale_id <= 0:
                return {'error': 'The void request has no sale.'}
            outcome = self.void_sale(
                sale_id, note or meta.get('reason') or 'Approved void',
                force_with_payments=bool(confirm_credit_payments),
            )
            if outcome.get('error') == 'credit_payments_exist':
                return {
                    'error': outcome.get('message') or (
                        'This credit sale already has payments. '
                        'A superadmin must confirm before it can be voided.'
                    ),
                    'credit_payments_exist': True,
                    'status': 409,
                }
            if outcome.get('success'):
                return outcome
            if 'already voided' in str(outcome.get('error') or '').lower():
                return {'success': True, 'duplicate': True}
            return outcome
        if atype == 'consumption_void':
            try:
                consumption_id = int(meta.get('consumption_id') or 0)
            except (TypeError, ValueError):
                return {'error': 'The void request has no consumption record.'}
            if consumption_id <= 0:
                return {'error': 'The void request has no consumption record.'}
            outcome = self.void_consumption(
                consumption_id, note or meta.get('reason') or 'Approved consumption void',
            )
            if outcome.get('success'):
                return outcome
            if 'already voided' in str(outcome.get('error') or '').lower():
                return {'success': True, 'duplicate': True}
            return outcome
        if atype == 'stock_adjust':
            try:
                product_id = int(meta.get('product_id') or 0)
            except (TypeError, ValueError):
                return {'error': 'The stock request has no product.'}
            direction = str(meta.get('direction') or 'set')
            quantity = meta.get('quantity', meta.get('new_qty'))
            reason = str(meta.get('reason') or note or 'Stock Count Correction')
            expected = meta.get('expected_stock')
            outcome = self.adjust_stock(
                product_id, direction, quantity, reason,
                pin=pin,
                expected_stock=expected,
                idempotency_key=f'APPROVAL:{int(approval_id)}',
            )
            return outcome
        return {'error': 'This request type cannot be executed.'}

    def _finish_approval(self, approval_id: int, result: dict) -> dict:
        db = _db()
        try:
            ok = bool(result.get('success') or result.get('duplicate'))
            now = datetime.now().isoformat()
            if ok:
                changed = db.execute(
                    "UPDATE cc_approvals SET status='approved', execution_json=?, updated_at=? "
                    "WHERE id=? AND status IN ('executing','pending','escalated')",
                    (json.dumps({'ok': True, 'duplicate': bool(result.get('duplicate'))}),
                     now, approval_id),
                )
                db.commit()
                if changed.rowcount != 1:
                    current = db.execute(
                        "SELECT status FROM cc_approvals WHERE id=?", (approval_id,)
                    ).fetchone()
                    if current and (current['status'] or '').lower() == 'approved':
                        return {'success': True, 'duplicate': True, 'status': 'approved'}
                    return {
                        'error': 'The approval changed before the result could be saved.',
                        'status': 409,
                    }
                return {'success': True, 'status': 'approved', 'duplicate': bool(result.get('duplicate'))}
            db.execute(
                "UPDATE cc_approvals SET status='pending', review_note=?, updated_at=? "
                "WHERE id=? AND status='executing'",
                (str(result.get('error') or 'Could not complete the approval.'), now, approval_id),
            )
            db.commit()
            return {
                'error': str(result.get('error') or 'Could not complete the approval.'),
                'status': int(result.get('status') or 409),
            }
        finally:
            db.close()

    def review_stock_adjustment(self, request_id: int, decision: str, note: str = '',
                                pin: str = '') -> dict:
        """Administrator approves or rejects. Approval is the only stock write."""
        if (self._role or '').lower() != 'superadmin':
            return {'error': 'Only Super-Admin can decide a stock adjustment.', 'status': 403}
        decision = (decision or '').strip().lower()
        if decision not in ('approved', 'rejected'):
            return {'error': 'Choose approve or reject.'}
        db = _db()
        try:
            req = db.execute(
                "SELECT * FROM stock_adjustment_requests WHERE id=?", (int(request_id),)
            ).fetchone()
            if not req:
                return {'error': 'Request not found'}
            if (req['status'] or '') != 'pending':
                return {'success': True, 'status': req['status'], 'duplicate': True}
            now = datetime.now().isoformat()
            if decision == 'rejected':
                db.execute(
                    "UPDATE stock_adjustment_requests SET status='rejected', reviewer_id=?,"
                    "reviewer_name=?, review_note=?, reviewed_at=? WHERE id=? AND status='pending'",
                    (self._user_id, self._username or 'superadmin', (note or '').strip(), now, req['id']),
                )
                db.commit()
                return {'success': True, 'status': 'rejected'}
            import math
            try:
                new_qty = round(float(req['requested_qty']), 4)
            except (TypeError, ValueError):
                return {'error': 'Enter a valid stock quantity.'}
            if not math.isfinite(new_qty) or not 0 <= new_qty <= 999999:
                return {'error': 'Stock quantity is outside the allowed range.'}
            preview = db.execute(
                "SELECT stock FROM products WHERE id=?", (int(req['product_id']),)
            ).fetchone()
            if preview and new_qty < round(float(preview['stock'] or 0), 4):
                pin_error = self._approval_pin_error(db, pin, int(req['id']))
                if pin_error:
                    return pin_error
            db.execute("BEGIN IMMEDIATE")
            fresh = db.execute(
                "SELECT * FROM stock_adjustment_requests WHERE id=?", (req['id'],)
            ).fetchone()
            if not fresh or (fresh['status'] or '') != 'pending':
                db.rollback()
                return {
                    'success': True,
                    'status': (fresh['status'] if fresh else 'pending'),
                    'duplicate': True,
                }
            row = db.execute(
                "SELECT id, name, stock, cost_price FROM products WHERE id=?",
                (int(fresh['product_id']),),
            ).fetchone()
            if not row:
                db.rollback()
                return {'error': 'Product not found'}
            old_stock = round(float(row['stock'] or 0), 4)
            expected = round(float(fresh['current_stock'] or 0), 4)
            if expected != old_stock:
                db.rollback()
                return {
                    'error': 'Stock changed. Refresh and review the latest quantity.',
                    'current_stock': old_stock,
                }
            qty_change = round(new_qty - old_stock, 4)
            changed = db.execute(
                "UPDATE products SET stock=?, updated_at=? "
                "WHERE id=? AND COALESCE(stock,0)=?",
                (new_qty, now, row['id'], old_stock),
            )
            if changed.rowcount != 1:
                db.rollback()
                return {'error': 'Stock changed. Refresh and try again.'}
            reason = f"Approved {fresh['request_number']}: {fresh['reason']}"
            db.execute(
                "INSERT INTO stock_movements "
                "(product_id,product_name,movement_type,qty_before,qty_change,"
                "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (row['id'], row['name'], 'SUPERADMIN_ADJUST',
                 old_stock, qty_change, new_qty,
                 f"ADJUST_pid={row['id']}", reason,
                 self._user_id, self._username or 'superadmin'),
            )
            mov_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            from desktop.utils.stock_layers import add_layer, consume_fifo
            if qty_change > 0:
                layer = add_layer(
                    db, row['id'], qty_change, float(row['cost_price'] or 0),
                    'adjust', str(mov_id),
                )
            elif qty_change < 0:
                layer = consume_fifo(
                    db, row['id'], abs(qty_change),
                    reference=f"ADJUST_pid={row['id']}",
                )
            else:
                layer = {}
            if layer.get('error'):
                db.rollback()
                return {'error': layer['error']}
            try:
                from desktop.utils.accounting_hooks import post_stock_adjust_journal
                posted = post_stock_adjust_journal(
                    db, product_id=row['id'], product_name=row['name'],
                    qty_change=qty_change, unit_cost=float(row['cost_price'] or 0),
                    reason=reason, movement_id=mov_id, user_id=self._user_id,
                    username=self._username or 'superadmin', safe=False)
            except Exception as _je:
                logger.error('stock adjust accounting: %s', _je, exc_info=True)
                db.rollback()
                return {'error': 'Could not post the stock adjustment.'}
            if (
                isinstance(posted, dict)
                and posted.get('error')
                and not posted.get('success')
                and not posted.get('skipped')
            ):
                db.rollback()
                return {'error': 'Could not post the stock adjustment.'}
            updated = db.execute(
                "UPDATE stock_adjustment_requests SET status='approved', reviewer_id=?,"
                "reviewer_name=?, review_note=?, reviewed_at=? WHERE id=? AND status='pending'",
                (self._user_id, self._username or 'superadmin', (note or '').strip(), now, fresh['id']),
            )
            if updated.rowcount != 1:
                db.rollback()
                return {'error': 'Stock changed. Refresh and try again.'}
            db.commit()
            _audit(self._user_id, self._username,
                   'STOCK_ADJUSTED', 'inventory',
                   f"pid={row['id']} name={row['name']} {old_stock}→{new_qty} reason={reason}")
            return {'success': True, 'status': 'approved', 'new_stock': new_qty}
        finally:
            db.close()

    def delete_product(self, pid: int) -> dict:
        from desktop.utils.security import client_actor, has_permission
        role = (self._role or '').lower()
        known = ('cashier', 'viewer', 'manager', 'admin', 'superadmin')
        if role not in known or not has_permission(client_actor(self), 'inventory.delete'):
            return {'error': 'Only an administrator can remove a product.', 'status': 403}
        db = _db()
        try:
            row = db.execute("SELECT id, name, stock FROM products WHERE id=?", (pid,)).fetchone()
            if not row:
                return {'error': 'Product not found.', 'status': 404}
            name = row['name'] if isinstance(row, dict) or hasattr(row, 'keys') else row[1]
            stock = float((row['stock'] if hasattr(row, 'keys') else row[2]) or 0)
            has_history = abs(stock) > 0.0001
            if not has_history:
                for sql in (
                    "SELECT 1 FROM sale_items WHERE product_id=? LIMIT 1",
                    "SELECT 1 FROM stock_movements WHERE product_id=? LIMIT 1",
                    "SELECT 1 FROM cost_layers WHERE product_id=? LIMIT 1",
                    "SELECT 1 FROM cost_layer_uses WHERE product_id=? LIMIT 1",
                ):
                    try:
                        if db.execute(sql, (pid,)).fetchone():
                            has_history = True
                            break
                    except Exception:
                        continue
            if has_history:
                db.execute("UPDATE products SET is_active=0 WHERE id=?", (pid,))
                db.commit()
                _audit(self._user_id, self._username, 'ARCHIVE_PRODUCT', 'inventory', f'pid={pid}')
                return {
                    'success': True,
                    'mode': 'archived',
                    'message': (
                        f'{name} left the selling list. It has stock or history, '
                        'so old receipts still keep it.'
                    ),
                }
            db.execute("DELETE FROM products WHERE id=?", (pid,))
            db.commit()
            _audit(self._user_id, self._username, 'DELETE_PRODUCT', 'inventory', f'pid={pid}')
            return {
                'success': True,
                'mode': 'deleted',
                'message': f'{name} had no stock or history and was deleted.',
            }
        finally:
            db.close()

    # ── SALES ─────────────────────────────────────────────────────────────────────

    def get_sales(self, start=None, end=None) -> list:
        from desktop.utils.shop_time import shop_today
        start = start or str(shop_today())
        end   = end   or str(shop_today())
        day_expr = _sale_day_expr('s')
        db = _db()
        try:
            return _rows(db.execute(
                "SELECT s.*,GROUP_CONCAT(si.product_name||' x'||si.quantity) as items_summary"
                " FROM sales s LEFT JOIN sale_items si ON s.id=si.sale_id"
                f" WHERE {day_expr} BETWEEN ? AND ?"
                " GROUP BY s.id ORDER BY s.created_at DESC",
                (start, end)
            ))
        finally:
            db.close()

    def get_sale_items_for_range(self, start=None, end=None, *, include_voided=False) -> list:
        """
        Batch-fetch line items for a date range (avoids N+1 get_sale calls in Reports).
        Returns flat rows with sale header fields joined onto each item.
        """
        from desktop.utils.shop_time import shop_today
        start = start or str(shop_today())
        end = end or str(shop_today())
        day_expr = _sale_day_expr('s')
        db = _db()
        try:
            status_clause = "" if include_voided else " AND s.status='completed' "
            return _rows(db.execute(f"""
                SELECT si.*,
                       s.receipt_number, s.created_at AS sale_created_at,
                       s.sale_date AS sale_date,
                       s.cashier_name, s.payment_method, s.status AS sale_status,
                       s.id AS sale_id
                FROM sale_items si
                JOIN sales s ON si.sale_id = s.id
                WHERE {day_expr} BETWEEN ? AND ?
                {status_clause}
                ORDER BY s.created_at DESC, si.id ASC
            """, (start, end)))
        finally:
            db.close()

    def _resolve_sale_date(self, data: dict) -> tuple:
        """
        Resolve business day from payload.

        Returns (sale_date_iso, is_backdated, created_at_str).
        Cashiers / unauthorized roles cannot backdate.
        Future dates rejected.
        """
        from desktop.utils.shop_time import (
            shop_today, business_day_iso, parse_sale_date, sale_created_at_for_day,
        )
        today = shop_today()
        today_s = today.isoformat()
        raw = (data.get('sale_date') or data.get('business_day') or '').strip()
        requested = parse_sale_date(raw) if raw else today
        if requested is None:
            raise ValueError('Invalid sale_date — use YYYY-MM-DD.')
        if requested > today:
            raise ValueError('Sale date cannot be in the future.')
        from desktop.utils.security import client_actor, has_permission
        role = (self._role or '').strip().lower()
        can_backdate = has_permission(client_actor(self), 'sales.business_day')
        if requested != today and not can_backdate:
            _audit(
                self._user_id, self._username or 'staff',
                'BUSINESS_DAY_DENIED', 'sales',
                f"role={role} requested={requested.isoformat()} forced={today_s}",
            )
            raise ValueError(
                'Only Manager/Admin can set a business day other than today.'
            )
        sale_date_s = business_day_iso(requested)
        is_backdated = sale_date_s != today_s
        created_at = sale_created_at_for_day(sale_date_s)
        return sale_date_s, is_backdated, created_at

    def create_sale(self, data: dict) -> dict:
        from desktop.utils.security import client_actor, has_permission
        if not has_permission(client_actor(self), 'sales.create'):
            return {'error': 'You cannot take a payment.', 'status': 403}
        items = data.get('items') or []
        if not items:
            return {'error': 'Cart is empty — add at least one product before charging.'}
        try:
            sale_date_s, is_backdated, created_at_s = self._resolve_sale_date(data)
        except ValueError as e:
            return {'error': str(e)}
        db = _db()
        try:
            db.execute("BEGIN IMMEDIATE")
            # Allow sale line items even if a product was later removed from inventory.
            db.execute("PRAGMA foreign_keys=OFF")
            sale_token = (data.get('client_token') or '').strip()
            if sale_token:
                existing = db.execute(
                    "SELECT id, receipt_number, total, sale_date, created_at "
                    "FROM sales WHERE client_token=?",
                    (sale_token,),
                ).fetchone()
                if existing:
                    db.rollback()
                    return {
                        'success': True,
                        'duplicate': True,
                        'sale_id': existing['id'],
                        'receipt_number': existing['receipt_number'],
                        'total': existing['total'],
                        'sale_date': existing['sale_date'],
                        'created_at': existing['created_at'],
                    }

            rn = _next_receipt(db, business_day=sale_date_s)
            total = float(data.get('total') or 0)
            amount_paid = float(data.get('amount_paid') or 0)
            change_amount = float(data.get('change_amount') or 0)
            credit_applied = round(float(data.get('credit_applied') or 0), 2)
            customer_id = data.get('customer_id')
            variance = data.get('variance') or {}
            variance_handling = (variance.get('handling') or data.get('variance_handling') or '').strip() or None
            original_total = round(float(
                data.get('original_total') if data.get('original_total') is not None
                else (total - float(data.get('cash_rounding_adj') or 0))
            ), 2)
            cash_rounding_adj = round(float(data.get('cash_rounding_adj') or 0), 2)
            electronic_paid = round(float(data.get('electronic_paid') or 0), 2)
            # Product revenue stays at original_total; payable may include rounding
            # Persist `total` as final payable (original + rounding) for amount-due compatibility
            if abs(cash_rounding_adj) > 0.009 and abs(total - original_total) < 0.009:
                total = round(original_total + cash_rounding_adj, 2)

            notes = data.get('notes', '') or ''
            mpesa_ref = (data.get('mpesa_ref') or '').strip()
            if mpesa_ref and 'mpesa ref' not in notes.lower():
                notes = (notes + f' | M-Pesa ref: {mpesa_ref}').strip(' |')
            if variance_handling:
                notes = (notes + f' | Variance: {variance_handling}').strip(' |')
            if abs(cash_rounding_adj) > 0.009:
                notes = (notes + f' | CashRounding: {cash_rounding_adj:+.2f}').strip(' |')
            emethod = (data.get('electronic_method') or '').strip()
            cash_paid_col = round(float(data.get('cash_paid') or 0), 2)
            tenders = data.get('payment_tenders')
            if isinstance(tenders, (list, dict)):
                tenders_json = json.dumps(tenders)
            else:
                tenders_json = (tenders or '').strip() or None
            if not tenders_json and electronic_paid > 0.009:
                from desktop.utils.payment_tenders import build_tenders
                tenders_json = json.dumps(build_tenders(
                    cash_paid=cash_paid_col or round(amount_paid - electronic_paid, 2),
                    electronic_paid=electronic_paid,
                    electronic_method=emethod,
                    store_credit=credit_applied,
                ))
            if electronic_paid > 0.009 and emethod and 'split:' not in notes.lower():
                cash_bit = round(float(data.get('cash_paid') or (amount_paid - electronic_paid)), 2)
                notes = (
                    notes + f' | Split: {emethod} {electronic_paid:,.2f} + Cash {cash_bit:,.2f}'
                ).strip(' |')
            if is_backdated and 'business day' not in notes.lower():
                notes = (notes + f' | Business day: {sale_date_s}').strip(' |')

            db.execute(
                "INSERT INTO sales (receipt_number,cashier_id,cashier_name,subtotal,"
                "discount,tax,total,payment_method,amount_paid,change_amount,notes,mpesa_ref,"
                "credit_applied,customer_id,variance_handling,"
                "original_total,cash_rounding_adj,electronic_paid,"
                "electronic_method,cash_paid,payment_tenders,"
                "sale_date,created_at,client_token)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rn,
                 self._user_id,
                 self._username or 'staff',
                 float(data.get('subtotal') or 0),
                 float(data.get('discount') or 0),
                 float(data.get('tax') or 0),
                 total,
                 data.get('payment_method', 'cash'),
                 amount_paid,
                 change_amount,
                 notes,
                 mpesa_ref or None,
                 credit_applied,
                 customer_id,
                 variance_handling,
                 original_total,
                 cash_rounding_adj,
                 electronic_paid,
                 emethod or None,
                 cash_paid_col,
                 tenders_json,
                 sale_date_s,
                 created_at_s,
                 sale_token or None)
            )
            sale_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

            for item in data.get('items', []):
                from backend.sale_lines import fill_sale_line
                line = fill_sale_line(db, item)
                pid = line['product_id']
                db.execute(
                    "INSERT INTO sale_items"
                    " (sale_id,product_id,product_name,sku,quantity,unit_price,discount,total)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (sale_id, pid, line['product_name'], line['sku'], line['quantity'],
                     line['unit_price'], line['discount'], line['total'])
                )
                # Stock enforcement — block sale if insufficient stock
                if pid:
                    prod_row = db.execute(
                        "SELECT id, name, stock FROM products WHERE id=?", (pid,)
                    ).fetchone()
                    if prod_row:
                        qty_requested = float(line['quantity'])
                        current_stock = float(prod_row['stock'])
                        if current_stock < qty_requested:
                            db.rollback()
                            raise ValueError(
                                f"Insufficient stock for '{prod_row['name']}': "
                                f"requested {qty_requested}, available {current_stock}"
                            )
                        new_stock = current_stock - qty_requested
                        db.execute(
                            "UPDATE products SET stock=? WHERE id=?",
                            (new_stock, pid)
                        )
                        # Log every stock movement
                        db.execute(
                            "INSERT INTO stock_movements "
                            "(product_id,product_name,movement_type,qty_before,qty_change,"
                            "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (pid, prod_row['name'], 'SALE',
                             current_stock, -qty_requested, new_stock,
                             rn, f"Sale: {rn}",
                             self._user_id, self._username or 'staff')
                        )
                        from desktop.utils.stock_layers import consume_fifo
                        layer = consume_fifo(
                            db, pid, qty_requested, sale_id=sale_id, reference=rn,
                        )
                        if layer.get('error'):
                            db.rollback()
                            raise ValueError(layer['error'])

            # Apply store credit against this sale (reduces amount due; not product revenue)
            wallet_balance_after = None
            if credit_applied > 0:
                if not customer_id:
                    db.rollback()
                    raise ValueError('Customer required to apply store credit.')
                wallet_balance_after = self._wallet_adjust(
                    db, int(customer_id), -credit_applied, 'apply_credit',
                    sale_id=sale_id, receipt_number=rn,
                    notes=f'Applied to sale {rn}')

            # Excess payment variance — tips/transport/misc/deposit never inflate product sales
            variance_result = None
            if variance and float(variance.get('excess_amount') or 0) > 0.009:
                variance_result = self._record_payment_variance(
                    db, sale_id=sale_id, receipt_number=rn,
                    customer_id=customer_id, total=total,
                    amount_received=amount_paid, credit_applied=credit_applied,
                    payment_method=data.get('payment_method', 'cash'),
                    variance=variance)
                if variance_result.get('wallet_balance') is not None:
                    wallet_balance_after = variance_result['wallet_balance']

            # Cash rounding adjustment — separate ledger entry (not product revenue)
            if abs(cash_rounding_adj) > 0.009:
                cash_orig = round(float(data.get('cash_original') or (original_total - electronic_paid - credit_applied)), 2)
                cash_rnd = round(float(data.get('cash_rounded') or (cash_orig + cash_rounding_adj)), 2)
                db.execute(
                    "INSERT INTO cash_rounding_adjustments "
                    "(sale_id,receipt_number,original_amount,rounded_amount,adjustment,"
                    "electronic_paid,cash_original,cash_rounded,payment_method,"
                    "cashier_id,cashier_name,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sale_id, rn, original_total, total, cash_rounding_adj,
                     electronic_paid, cash_orig, cash_rnd,
                     data.get('payment_method', 'cash'),
                     self._user_id, self._username or 'staff',
                     'Cash rounding adjustment')
                )

            db.execute(
                "INSERT INTO sync_queue (action_type,payload) VALUES (?,?)",
                ('sale', json.dumps({
                    'receipt_number': rn,
                    'total':          total,
                    'original_total': original_total,
                    'cash_rounding_adj': cash_rounding_adj,
                    'cashier':        self._username or 'staff',
                    'sale_date':      sale_date_s,
                    'created_at':     created_at_s,
                }))
            )
            # Auto-post double-entry journal (never block checkout)
            try:
                from desktop.utils.accounting_hooks import post_sale_journal
                post_sale_journal(
                    db, sale_id,
                    user_id=self._user_id, username=self._username or 'staff',
                    safe=True)
            except Exception as _je:
                logger.error('sale accounting post: %s', _je, exc_info=True)

            pay_method = (data.get('payment_method') or '').strip()
            pay_l = pay_method.lower()
            credit_due = 0.0
            tender_rows = data.get('payment_tenders')
            if isinstance(tender_rows, str) and tender_rows.strip():
                try:
                    tender_rows = json.loads(tender_rows)
                except Exception:
                    tender_rows = None
            if isinstance(tender_rows, list):
                for tender in tender_rows:
                    if str((tender or {}).get('method') or '').strip().lower() in (
                        'credit', 'on account', 'customer credit', 'part credit',
                    ):
                        credit_due += float((tender or {}).get('amount') or 0)
            is_debt_sale = pay_l in (
                'credit sale', 'credit', 'credit account', 'part payment',
                'part-payment', 'on account',
            ) or credit_due > 0.009
            debt_out = None
            if is_debt_sale:
                if not customer_id:
                    db.rollback()
                    return {'error': 'Choose a customer before a credit or part payment.'}
                from desktop.utils.payment_tenders import collected_method_label
                paid_now = round(float(amount_paid or 0) + float(credit_applied or 0), 2)
                debt_total = round(float(original_total if abs(cash_rounding_adj) < 0.009 else total), 2)
                debt_out = self.create_debt_invoice({
                    'customer_id': int(customer_id),
                    'sale_id': int(sale_id),
                    'receipt_number': rn,
                    'total_amount': debt_total,
                    'amount_paid': paid_now,
                    'payment_method': collected_method_label(tender_rows, pay_method),
                    'notes': f'Auto from sale {pay_method}',
                }, conn=db)
                if debt_out.get('error') or not (debt_out.get('success') or debt_out.get('invoice_id')):
                    db.rollback()
                    return {'error': debt_out.get('error') or 'Debt invoice was not created. The sale was not saved.'}

            db.commit()
            _audit(self._user_id, self._username or 'staff',
                   'CREATE_SALE', 'sales',
                   f"receipt={rn} total={total} original={original_total} "
                   f"rounding={cash_rounding_adj} paid={amount_paid} "
                   f"credit={credit_applied} variance={variance_handling or 'none'} "
                   f"sale_date={sale_date_s}")
            if is_backdated:
                _audit(
                    self._user_id, self._username or 'staff',
                    'BACKDATE_SALE', 'sales',
                    f"receipt={rn} sale_date={sale_date_s} created_at={created_at_s} "
                    f"total={total}",
                )
            if abs(cash_rounding_adj) > 0.009:
                _audit(
                    self._user_id, self._username or 'staff', 'CASH_ROUNDING', 'sales',
                    f"receipt={rn} original={original_total} adj={cash_rounding_adj} "
                    f"final={total} electronic={electronic_paid}"
                )
            if variance_result:
                _audit(
                    self._user_id, self._username or 'staff', 'PAYMENT_VARIANCE', 'sales',
                   f"receipt={rn} excess={variance_result.get('excess_amount')} "
                   f"handling={variance_result.get('handling')} "
                   f"mgr={variance_result.get('manager_name') or '-'} "
                   f"tip={variance_result.get('tip_amount')} "
                   f"transport={variance_result.get('transport_amount')} "
                   f"deposit={variance_result.get('deposit_amount')} "
                   f"advance={variance_result.get('advance_amount')} "
                   f"change={variance_result.get('change_returned')} "
                   f"misc={variance_result.get('misc_amount')} "
                   f"additional={variance_result.get('additional_payment_amount')}"
                )
            out = {'success': True, 'receipt_number': rn, 'sale_id': sale_id,
                   'original_total': original_total,
                   'cash_rounding_adj': cash_rounding_adj,
                   'total': total,
                   'sale_date': sale_date_s,
                   'created_at': created_at_s}
            if wallet_balance_after is not None:
                out['wallet_balance'] = wallet_balance_after
            if variance_result:
                out['variance'] = variance_result
            if debt_out and (debt_out.get('success') or debt_out.get('invoice_id')):
                out['debt_invoice_id'] = debt_out.get('invoice_id')
                out['debt_invoice_number'] = debt_out.get('invoice_number')
                out['debt_balance'] = debt_out.get('balance')
                out['debt'] = debt_out
            return out

        except Exception as e:
            try: db.rollback()
            except Exception: pass
            logger.error(f"create_sale failed: {e}", exc_info=True)
            return {'error': str(e)}
        finally:
            try: db.execute("PRAGMA foreign_keys=ON")
            except Exception: pass
            db.close()

    def _wallet_row(self, db, customer_id: int):
        row = db.execute(
            "SELECT * FROM customer_wallet WHERE customer_id=?", (customer_id,)
        ).fetchone()
        if row:
            return row
        db.execute(
            "INSERT INTO customer_wallet (customer_id, balance, updated_at) VALUES (?,0,?)",
            (customer_id, datetime.now().isoformat())
        )
        return db.execute(
            "SELECT * FROM customer_wallet WHERE customer_id=?", (customer_id,)
        ).fetchone()

    def _wallet_adjust(self, db, customer_id: int, delta: float, txn_type: str,
                       sale_id=None, receipt_number=None, notes=''):
        """Adjust wallet balance by delta (+deposit / -apply). Returns new balance."""
        delta = round(float(delta), 2)
        w = self._wallet_row(db, customer_id)
        before = round(float(w['balance'] or 0), 2)
        after = round(before + delta, 2)
        if after < -0.009:
            raise ValueError(
                f'Insufficient store credit: available {before:.2f}, needed {abs(delta):.2f}')
        now = datetime.now().isoformat()
        db.execute(
            "UPDATE customer_wallet SET balance=?, updated_at=? WHERE customer_id=?",
            (after, now, customer_id)
        )
        db.execute(
            "INSERT INTO wallet_transactions "
            "(customer_id,sale_id,receipt_number,txn_type,amount,balance_before,"
            "balance_after,notes,cashier_id,cashier_name) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (customer_id, sale_id, receipt_number, txn_type, abs(delta),
             before, after, notes or '', self._user_id, self._username or 'staff')
        )
        return after

    def _record_payment_variance(self, db, sale_id, receipt_number, customer_id,
                                 total, amount_received, credit_applied,
                                 payment_method, variance: dict) -> dict:
        excess = round(float(variance.get('excess_amount') or 0), 2)
        handling = (variance.get('handling') or '').strip().lower()
        if excess <= 0 or not handling:
            return {}
        tip = transport = deposit = advance = change_ret = misc = additional = 0.0
        if handling == 'return_change':
            change_ret = excess
        elif handling == 'deposit':
            deposit = excess
        elif handling == 'transport':
            transport = excess
        elif handling == 'tip':
            tip = excess
        elif handling == 'advance':
            advance = excess
        elif handling == 'miscellaneous':
            misc = excess
        elif handling == 'additional_payment':
            # Keep full amount received as sales income; no change returned.
            # Excess is tracked for audit/reports; receipt stays clean.
            additional = excess
        else:
            raise ValueError(f'Unknown variance handling: {handling}')

        cust_name = ''
        wallet_bal = None
        if customer_id:
            crow = db.execute(
                "SELECT name FROM customers WHERE id=?", (customer_id,)
            ).fetchone()
            cust_name = (crow['name'] if crow else '') or ''
        if handling in ('deposit', 'advance'):
            if not customer_id:
                raise ValueError('Customer required for deposit / advance payment.')
            txn = 'deposit' if handling == 'deposit' else 'advance'
            wallet_bal = self._wallet_adjust(
                db, int(customer_id), excess, txn,
                sale_id=sale_id, receipt_number=receipt_number,
                notes=f'{txn} from excess on {receipt_number}')

        misc_cat = (variance.get('misc_category') or '').strip() or None
        reason = (variance.get('reason') or '').strip() or None
        if handling == 'miscellaneous' and (not misc_cat or not reason):
            raise ValueError('Miscellaneous variance requires category and reason.')

        mgr_ok = 1 if variance.get('manager_approved') else 0
        mgr_name = (variance.get('manager_name') or '').strip() or None
        now = datetime.now().isoformat()
        db.execute(
            "INSERT INTO payment_variances "
            "(sale_id,receipt_number,customer_id,customer_name,payment_method,"
            "sale_total,amount_received,excess_amount,handling,misc_category,reason,"
            "credit_applied,tip_amount,transport_amount,deposit_amount,advance_amount,"
            "change_returned,misc_amount,manager_approved,manager_name,"
            "cashier_id,cashier_name,notes,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sale_id, receipt_number, customer_id, cust_name, payment_method,
             total, amount_received, excess, handling, misc_cat, reason,
             credit_applied, tip, transport, deposit, advance,
             change_ret, misc, mgr_ok, mgr_name,
             self._user_id, self._username or 'staff',
             (variance.get('notes') or '').strip(), now)
        )
        return {
            'handling': handling,
            'excess_amount': excess,
            'tip_amount': tip,
            'transport_amount': transport,
            'deposit_amount': deposit,
            'advance_amount': advance,
            'change_returned': change_ret,
            'misc_amount': misc,
            'additional_payment_amount': additional,
            'misc_category': misc_cat,
            'wallet_balance': wallet_bal,
            'manager_approved': bool(mgr_ok),
            'manager_name': mgr_name,
        }

    def get_wallet_balance(self, customer_id: int) -> dict:
        db = _db()
        try:
            row = _row(db.execute(
                "SELECT * FROM customer_wallet WHERE customer_id=?", (customer_id,)
            ))
            bal = float((row or {}).get('balance') or 0)
            return {'customer_id': customer_id, 'balance': bal}
        finally:
            db.close()

    def get_payment_variance_report(self, start=None, end=None) -> dict:
        start = start or str(date.today())
        end = end or str(date.today())
        db = _db()
        try:
            rows = _rows(db.execute(
                "SELECT * FROM payment_variances "
                "WHERE date(created_at) BETWEEN ? AND ? "
                "ORDER BY created_at DESC",
                (start, end)
            ))
            summary = {
                'count': len(rows),
                'extra_received': round(sum(float(r.get('excess_amount') or 0) for r in rows), 2),
                'returned': round(sum(float(r.get('change_returned') or 0) for r in rows), 2),
                'deposits': round(sum(float(r.get('deposit_amount') or 0) for r in rows), 2),
                'advances': round(sum(float(r.get('advance_amount') or 0) for r in rows), 2),
                'tips': round(sum(float(r.get('tip_amount') or 0) for r in rows), 2),
                'transport': round(sum(float(r.get('transport_amount') or 0) for r in rows), 2),
                'misc': round(sum(float(r.get('misc_amount') or 0) for r in rows), 2),
                'additional_payments': round(sum(
                    float(r.get('excess_amount') or 0) for r in rows
                    if (r.get('handling') or '').lower() == 'additional_payment'
                ), 2),
            }
            return {'rows': rows, 'summary': summary, 'start': start, 'end': end}
        finally:
            db.close()

    def list_centre_receipts(self, start='', end='', kind='', status='', query='',
                             limit=200, offset=0) -> dict:
        """Receipts the signed-in role is allowed to open. Read only."""
        from backend.receipts_centre import list_receipts
        from desktop.utils.security import client_actor, has_permission, sees_management_figures
        actor = client_actor(self)
        db = _db()
        try:
            return list_receipts(
                db,
                can_sales=has_permission(actor, 'sales.view_own') or has_permission(actor, 'sales.view_all'),
                can_consumption=has_permission(actor, 'consumption.create') or has_permission(actor, 'consumption.view_report'),
                can_inventory=has_permission(actor, 'inventory.view'),
                can_adjustments=has_permission(actor, 'inventory.adjust_stock') or has_permission(actor, 'inventory.receive'),
                can_debt=has_permission(actor, 'debt.view') or has_permission(actor, 'debt.view_own'),
                can_finance=sees_management_figures(actor),
                can_approvals=has_permission(actor, 'sales.request_void') or has_permission(actor, 'sales.void'),
                username=self._username or '',
                kind=kind or '',
                status=status or '',
                query=query or '',
                start=start or '',
                end=end or '',
                limit=int(limit or 200),
                offset=int(offset or 0),
            )
        except Exception as exc:
            return {'error': str(exc), 'receipts': [], 'total': 0}
        finally:
            db.close()

    def centre_receipt(self, kind, record_id) -> dict:
        from backend.receipts_centre import receipt_detail
        from desktop.utils.security import client_actor, sees_product_cost
        db = _db()
        try:
            detail = receipt_detail(
                db, str(kind or ''), int(record_id or 0),
                show_cost=sees_product_cost(client_actor(self)),
            )
        except Exception as exc:
            return {'error': str(exc)}
        finally:
            db.close()
        if not detail:
            return {'error': 'That receipt could not be opened.'}
        return detail

    def get_sale(self, sale_id: int) -> dict:
        db = _db()
        try:
            sale  = _row(db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)))
            if not sale:
                return {}
            items = _rows(db.execute("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)))
            sale['items'] = items
            var = _row(db.execute(
                "SELECT * FROM payment_variances WHERE sale_id=? ORDER BY id DESC LIMIT 1",
                (sale_id,)
            ))
            if var:
                sale['variance'] = var
                if (var.get('handling') or '').strip().lower() == 'additional_payment':
                    # Derived field for UI/reports (no dedicated DB column)
                    sale['variance'] = dict(var)
                    sale['variance']['additional_payment_amount'] = float(
                        var.get('excess_amount') or 0)
            if sale.get('customer_id'):
                cust = _row(db.execute(
                    "SELECT name, phone FROM customers WHERE id=?", (sale['customer_id'],)
                ))
                if cust:
                    sale['customer_name'] = cust.get('name') or ''
                    sale['customer_phone'] = cust.get('phone') or ''
                w = _row(db.execute(
                    "SELECT balance FROM customer_wallet WHERE customer_id=?",
                    (sale['customer_id'],)
                ))
                if w:
                    sale['wallet_balance'] = float(w.get('balance') or 0)
            # Linked debt invoice (credit / part payment)
            debt = _row(db.execute(
                "SELECT * FROM debt_invoices WHERE sale_id=? "
                "ORDER BY id DESC LIMIT 1",
                (sale_id,)
            ))
            if debt:
                sale['debt'] = debt
                sale['debt_original'] = float(debt.get('total_amount') or 0)
                sale['debt_paid'] = float(debt.get('amount_paid') or 0)
                sale['debt_outstanding'] = float(debt.get('balance') or 0)
                sale['debt_invoice_id'] = debt.get('id')
                sale['debt_invoice_number'] = debt.get('invoice_number')
                sale['debt_status'] = debt.get('status')
            try:
                from desktop.utils.payment_tenders import parse_tenders
                parsed = parse_tenders(sale.get('payment_tenders'))
                if parsed:
                    sale['payment_tenders'] = parsed
            except Exception:
                pass
            return sale
        finally:
            db.close()

    # ── SALES EDITING / VOID ─────────────────────────────────────────────────────

    @staticmethod
    def _void_restore_ref(sale_id: int) -> str:
        return f"VOID_sale={int(sale_id)}"

    def _has_void_restore(self, db, sale_id: int) -> bool:
        """True if stock was already restored for this sale (idempotency)."""
        ref = self._void_restore_ref(sale_id)
        row = db.execute(
            "SELECT 1 FROM stock_movements WHERE movement_type='VOID_RESTORE' "
            "AND (reference=? OR reference LIKE ?) LIMIT 1",
            (ref, f"%sale={int(sale_id)}%")
        ).fetchone()
        return bool(row)

    def _restock_sale_items(
        self, db, sale_id: int, *, receipt: str = '', reason: str = '',
        movement_type: str = 'VOID_RESTORE', skip_if_restored: bool = True,
    ) -> list:
        """
        Restore product stock for every line on a sale.
        When skip_if_restored and VOID_RESTORE already logged, returns preview
        without double-applying stock.
        """
        sale_id = int(sale_id)
        items = db.execute(
            "SELECT si.*, p.name AS live_name FROM sale_items si "
            "LEFT JOIN products p ON p.id=si.product_id WHERE si.sale_id=?",
            (sale_id,)
        ).fetchall()
        preview = []
        for item in items:
            pid = item['product_id']
            if not pid:
                continue
            qty = float(item['quantity'] or 0)
            if qty <= 0:
                continue
            name = (item['live_name'] or item['product_name'] or '') or f'#{pid}'
            preview.append({
                'product_id': int(pid),
                'product_name': name,
                'quantity': qty,
            })

        if (
            skip_if_restored
            and movement_type == 'VOID_RESTORE'
            and self._has_void_restore(db, sale_id)
        ):
            for r in preview:
                r['already_restored'] = True
            return preview

        now = datetime.now().isoformat()
        ref = (
            self._void_restore_ref(sale_id)
            if movement_type == 'VOID_RESTORE'
            else f"{movement_type}_sale={sale_id}"
        )
        rn = receipt or str(sale_id)
        applied = []
        for item in items:
            pid = item['product_id']
            if not pid:
                continue
            qty = float(item['quantity'] or 0)
            if qty <= 0:
                continue
            prod = db.execute(
                "SELECT id, name, stock FROM products WHERE id=?", (pid,)
            ).fetchone()
            if not prod:
                continue
            old_stock = float(prod['stock'] or 0)
            new_stock = old_stock + qty
            db.execute(
                "UPDATE products SET stock=?, updated_at=? WHERE id=?",
                (new_stock, now, pid)
            )
            db.execute(
                "INSERT INTO stock_movements "
                "(product_id,product_name,movement_type,qty_before,qty_change,"
                "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, prod['name'], movement_type,
                 old_stock, qty, new_stock, ref,
                 reason or f"Stock restored: sale {rn}",
                 self._user_id, self._username or 'admin')
            )
            applied.append({
                'product_id': int(pid),
                'product_name': prod['name'],
                'quantity': qty,
            })
        return applied

    def _deduct_sale_items_stock(
        self, db, sale_id: int, items: list, *, receipt: str = '',
        movement_type: str = 'SALE_EDIT',
    ) -> None:
        """Deduct stock for edited/new sale lines. Raises ValueError if insufficient."""
        now = datetime.now().isoformat()
        rn = receipt or str(sale_id)
        for item in items:
            pid = item.get('product_id')
            if not pid:
                continue
            qty = float(item.get('quantity') or 0)
            if qty <= 0:
                continue
            prod = db.execute(
                "SELECT id, name, stock FROM products WHERE id=?", (pid,)
            ).fetchone()
            if not prod:
                raise ValueError(f"Product #{pid} not found for stock deduct.")
            current = float(prod['stock'] or 0)
            if current + 1e-9 < qty:
                raise ValueError(
                    f"Insufficient stock for '{prod['name']}': "
                    f"need {qty:g}, available {current:g}"
                )
            new_stock = current - qty
            db.execute(
                "UPDATE products SET stock=?, updated_at=? WHERE id=?",
                (new_stock, now, pid)
            )
            db.execute(
                "INSERT INTO stock_movements "
                "(product_id,product_name,movement_type,qty_before,qty_change,"
                "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (int(pid), prod['name'], movement_type,
                 current, -qty, new_stock, rn,
                 f"Sale edit deduct: {rn}",
                 self._user_id, self._username or 'admin')
            )

    def void_sale(self, sale_id: int, reason: str, *, force_with_payments: bool = False,
                  pin: str = '') -> dict:
        """
        Void a completed sale. Manager / admin / superadmin.
        Restores stock for all items. Full audit trail.
        Credit sales with debt payments already collected require force_with_payments=True
        (UI confirms special handling).
        """
        if self._role not in ('admin', 'superadmin', 'manager'):
            _audit(self._user_id, self._username,
                   'VOID_SALE_DENIED', 'sales',
                   f"sale_id={sale_id} role={self._role}")
            return {'error': 'Insufficient permissions to void sales.'}

        db = _db()
        try:
            db.execute("BEGIN IMMEDIATE")
            sale = db.execute(
                "SELECT * FROM sales WHERE id=?", (sale_id,)
            ).fetchone()
            if not sale:
                db.rollback()
                return {'error': 'Sale not found'}
            if sale['status'] == 'voided':
                db.rollback()
                return {'error': 'Sale already voided'}

            # Credit-sale debt payment check
            debt_paid_total = 0.0
            debt_payment_count = 0
            debt_preview = db.execute(
                "SELECT di.id, di.invoice_number, di.amount_paid, di.balance, di.status "
                "FROM debt_invoices di WHERE di.sale_id=?",
                (sale_id,)
            ).fetchall()
            for inv in debt_preview:
                paid_amt = float(inv['amount_paid'] or 0)
                if paid_amt > 0.009:
                    debt_paid_total += paid_amt
                    debt_payment_count += 1
            if debt_paid_total > 0.009 and not force_with_payments:
                db.rollback()
                return {
                    'error': 'credit_payments_exist',
                    'debt_paid_total': round(debt_paid_total, 2),
                    'debt_payment_count': debt_payment_count,
                    'message': (
                        f'This credit sale has {debt_payment_count} debt payment(s) totaling '
                        f'{debt_paid_total:,.2f} already collected. Voiding cancels the remaining '
                        f'balance but collected amounts must be refunded manually if applicable.'
                    ),
                }

            # Restore stock (idempotent — no double VOID_RESTORE)
            self._restock_sale_items(
                db, sale_id,
                receipt=sale['receipt_number'] or '',
                reason=f"Stock restored: sale {sale['receipt_number']} voided",
                movement_type='VOID_RESTORE',
                skip_if_restored=True,
            )
            from desktop.utils.stock_layers import restore_sale_layers
            restore_sale_layers(db, sale_id)

            # Cancel linked debt invoices for this sale (keep payment history)
            debt_rows = db.execute(
                "SELECT id, invoice_number, status, amount_paid, balance FROM debt_invoices "
                "WHERE sale_id=? AND status NOT IN ('cancelled')",
                (sale_id,)
            ).fetchall()
            for inv in debt_rows:
                paid_note = ''
                paid_amt = float(inv['amount_paid'] or 0)
                if paid_amt > 0.009:
                    paid_note = (
                        f' | Payments already collected: {paid_amt:,.2f} — '
                        f'refund manually if required'
                    )
                db.execute(
                    "UPDATE debt_invoices SET status='cancelled', balance=0, notes=?, updated_at=? "
                    "WHERE id=?",
                    (f"CANCELLED: sale {sale['receipt_number']} voided — {reason}{paid_note}",
                     datetime.now().isoformat(), inv['id'])
                )
                _audit(self._user_id, self._username or 'admin',
                       'CANCEL_INVOICE', 'debt',
                       f"inv={inv['invoice_number']} void_sale paid_collected={paid_amt}")

            # Reverse store-credit apply and deposit/advance from payment variance
            sale_keys = set(sale.keys()) if hasattr(sale, 'keys') else set()
            credit_applied = float(sale['credit_applied'] if 'credit_applied' in sale_keys else 0) or 0.0
            cust_id = sale['customer_id'] if 'customer_id' in sale_keys else None
            rn = sale['receipt_number']

            if cust_id and credit_applied > 0.009:
                self._wallet_adjust(
                    db, int(cust_id), credit_applied, 'void_restore_credit',
                    sale_id=sale_id, receipt_number=rn,
                    notes=f'Void restore credit applied on {rn}')

            var = db.execute(
                "SELECT * FROM payment_variances WHERE sale_id=? ORDER BY id DESC LIMIT 1",
                (sale_id,)
            ).fetchone()
            if var:
                v_cust = cust_id or (var['customer_id'] if var['customer_id'] else None)
                dep = float(var['deposit_amount'] or 0) + float(var['advance_amount'] or 0)
                if v_cust and dep > 0.009:
                    self._wallet_adjust(
                        db, int(v_cust), -dep, 'void_reverse_deposit',
                        sale_id=sale_id, receipt_number=rn,
                        notes=f'Void reverse deposit/advance from {rn}')

            # Reverse cash rounding adjustment (refund was the rounded paid amount)
            rounding_adj = 0.0
            try:
                if 'cash_rounding_adj' in sale_keys:
                    rounding_adj = float(sale['cash_rounding_adj'] or 0)
            except Exception:
                rounding_adj = 0.0
            rnd_rows = db.execute(
                "SELECT id, adjustment FROM cash_rounding_adjustments "
                "WHERE sale_id=? AND COALESCE(voided,0)=0",
                (sale_id,)
            ).fetchall()
            for rr in rnd_rows:
                db.execute(
                    "UPDATE cash_rounding_adjustments SET voided=1, notes=? WHERE id=?",
                    (f'REVERSED on void of {rn}: {reason}', rr['id'])
                )
            if abs(rounding_adj) > 0.009 or rnd_rows:
                # Insert offsetting ledger row so reports net to zero
                orig_t = float(sale['original_total'] if 'original_total' in sale_keys and sale['original_total'] is not None
                               else (float(sale['total'] or 0) - rounding_adj))
                db.execute(
                    "INSERT INTO cash_rounding_adjustments "
                    "(sale_id,receipt_number,original_amount,rounded_amount,adjustment,"
                    "payment_method,cashier_id,cashier_name,voided,notes) "
                    "VALUES (?,?,?,?,?,?,?,?,1,?)",
                    (sale_id, rn, orig_t, float(sale['total'] or 0), -rounding_adj,
                     sale['payment_method'] if 'payment_method' in sale_keys else 'cash',
                     self._user_id, self._username or 'admin',
                     f'VOID reverse cash rounding for {rn}')
                )

            # Mark sale as voided
            db.execute(
                "UPDATE sales SET status='voided', notes=? WHERE id=?",
                (f"VOIDED by {self._username}: {reason}", sale_id)
            )

            # Log the edit
            db.execute(
                "INSERT INTO sale_edits "
                "(sale_id,edited_by_id,edited_by_name,edit_type,"
                "field_name,old_value,new_value,reason) VALUES (?,?,?,?,?,?,?,?)",
                (sale_id, self._user_id, self._username or 'admin',
                 'VOID', 'status', 'completed', 'voided', reason)
            )

            # Reverse sale journal
            try:
                from desktop.utils.accounting_hooks import reverse_sale_journal
                reverse_sale_journal(
                    db, sale_id, reason=reason,
                    user_id=self._user_id, username=self._username or 'admin',
                    safe=True)
            except Exception as _je:
                logger.error('void sale accounting: %s', _je, exc_info=True)

            db.commit()
            if abs(rounding_adj) > 0.009 or rnd_rows:
                _audit(self._user_id, self._username or 'admin',
                       'CASH_ROUNDING_REVERSE', 'sales',
                       f"sale_id={sale_id} receipt={rn} reverse_adj={-rounding_adj} "
                       f"refunded_total={float(sale['total'] or 0)}")
            _audit(self._user_id, self._username,
                   'VOID_SALE', 'sales',
                   f"sale_id={sale_id} receipt={rn} reason={reason} "
                   f"debt_paid_collected={debt_paid_total}")
            out = {'success': True}
            if debt_paid_total > 0.009:
                out['debt_paid_total'] = round(debt_paid_total, 2)
                out['warning'] = (
                    f'Voided. {debt_paid_total:,.2f} already collected on linked debt — '
                    f'refund manually if required. Remaining balance cancelled.'
                )
            return out
        except Exception as e:
            db.rollback()
            logger.error(f"void_sale: {e}")
            raise
        finally:
            db.close()

    def unvoid_sale(self, sale_id: int, reason: str) -> dict:
        """Restore one voided sale. Super Admin session only. Effects apply once."""
        reason = (reason or '').strip()
        if (self._role or '').lower() != 'superadmin':
            _audit(self._user_id, self._username, 'UNVOID_SALE_DENIED', 'sales',
                   f"sale_id={sale_id} role={self._role}")
            return {'error': 'Only a signed-in Super Admin can restore a receipt.', 'status': 403}
        if not reason:
            return {'error': 'Enter a reason for restoring this receipt.', 'status': 400}

        db = _db()
        try:
            db.execute('BEGIN IMMEDIATE')
            sale = db.execute("SELECT * FROM sales WHERE id=?", (int(sale_id),)).fetchone()
            if not sale:
                db.rollback()
                return {'error': 'Sale not found.', 'status': 404}
            status = (sale['status'] or '').lower()
            if status == 'completed':
                db.rollback()
                return {'success': True, 'duplicate': True, 'status': 'completed'}
            if status != 'voided':
                db.rollback()
                return {'error': 'Only a voided sale can be restored.', 'status': 409}

            items = db.execute(
                "SELECT product_id, product_name, quantity FROM sale_items WHERE sale_id=?",
                (int(sale_id),),
            ).fetchall()
            now = datetime.now().isoformat()
            stock_changes = []
            for item in items:
                pid = item['product_id']
                qty = round(float(item['quantity'] or 0), 4)
                if not pid or qty <= 0:
                    continue
                prod = db.execute(
                    "SELECT name, COALESCE(stock,0) AS stock FROM products WHERE id=?",
                    (int(pid),),
                ).fetchone()
                if not prod:
                    db.rollback()
                    return {
                        'error': f"{item['product_name'] or 'A product'} on this receipt no longer exists.",
                        'status': 409,
                    }
                old_stock = round(float(prod['stock'] or 0), 4)
                if old_stock + 1e-9 < qty:
                    db.rollback()
                    return {
                        'error': (
                            f"Not enough {prod['name']} on hand ({old_stock:g}) to restore "
                            f"this sale ({qty:g}). Receive stock, then restore the receipt."
                        ),
                        'status': 409,
                    }
                new_stock = round(old_stock - qty, 4)
                changed = db.execute(
                    "UPDATE products SET stock=?, updated_at=? "
                    "WHERE id=? AND ROUND(COALESCE(stock,0),4)>=?",
                    (new_stock, now, int(pid), qty),
                )
                if changed.rowcount != 1:
                    db.rollback()
                    return {
                        'error': f"Stock for {prod['name']} changed before the receipt could be restored.",
                        'status': 409,
                    }
                db.execute(
                    "INSERT INTO stock_movements "
                    "(product_id,product_name,movement_type,qty_before,qty_change,"
                    "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (int(pid), prod['name'], 'UNVOID_DEDUCT', old_stock, -qty, new_stock,
                     f"UNVOID_sale={int(sale_id)}",
                     f"Restore voided sale {sale['receipt_number']}: {reason}",
                     self._user_id, self._username or 'superadmin'),
                )
                stock_changes.append(f"{prod['name']} {old_stock}->{new_stock}")

            self._reapply_voided_layers(db, int(sale_id))

            sale_keys = set(sale.keys())
            rn = sale['receipt_number']
            cust_id = sale['customer_id'] if 'customer_id' in sale_keys else None
            credit_applied = float(sale['credit_applied'] or 0) if 'credit_applied' in sale_keys else 0.0
            if cust_id and credit_applied > 0.009:
                self._wallet_adjust(
                    db, int(cust_id), -credit_applied, 'unvoid_reapply_credit',
                    sale_id=int(sale_id), receipt_number=rn,
                    notes=f'Restore credit applied on {rn}',
                )
            try:
                var = db.execute(
                    "SELECT * FROM payment_variances WHERE sale_id=? ORDER BY id DESC LIMIT 1",
                    (int(sale_id),),
                ).fetchone()
            except Exception:
                var = None
            if var:
                v_cust = cust_id or (var['customer_id'] if var['customer_id'] else None)
                dep = float(var['deposit_amount'] or 0) + float(var['advance_amount'] or 0)
                if v_cust and dep > 0.009:
                    self._wallet_adjust(
                        db, int(v_cust), dep, 'unvoid_restore_deposit',
                        sale_id=int(sale_id), receipt_number=rn,
                        notes=f'Restore deposit reversed by the void of {rn}',
                    )

            invoices = db.execute(
                "SELECT id, invoice_number, total_amount, amount_paid, notes "
                "FROM debt_invoices WHERE sale_id=? AND status='cancelled'",
                (int(sale_id),),
            ).fetchall()
            for inv in invoices:
                note = (inv['notes'] or '')
                if 'voided' not in note.lower():
                    continue
                total = float(inv['total_amount'] or 0)
                paid = float(inv['amount_paid'] or 0)
                balance = round(max(0.0, total - paid), 2)
                next_status = 'paid' if balance <= 0.009 else 'open'
                db.execute(
                    "UPDATE debt_invoices SET status=?, balance=?, notes=?, updated_at=? WHERE id=?",
                    (next_status, balance,
                     note + f" | RESTORED by {self._username or 'superadmin'}: {reason}",
                     now, inv['id']),
                )

            prior = db.execute(
                "SELECT id FROM cash_rounding_adjustments "
                "WHERE sale_id=? AND notes LIKE 'UNVOID restore%' LIMIT 1",
                (int(sale_id),),
            ).fetchone()
            if not prior:
                void_rows = db.execute(
                    "SELECT adjustment FROM cash_rounding_adjustments "
                    "WHERE sale_id=? AND notes LIKE 'VOID reverse%' ORDER BY id",
                    (int(sale_id),),
                ).fetchall()
                for row in void_rows:
                    db.execute(
                        "INSERT INTO cash_rounding_adjustments "
                        "(sale_id,receipt_number,original_amount,rounded_amount,adjustment,"
                        "payment_method,cashier_id,cashier_name,voided,notes) "
                        "VALUES (?,?,?,?,?,?,?,?,0,?)",
                        (int(sale_id), rn, float(sale['total'] or 0), float(sale['total'] or 0),
                         -float(row['adjustment'] or 0),
                         sale['payment_method'] if 'payment_method' in sale_keys else 'cash',
                         self._user_id, self._username or 'superadmin',
                         f'UNVOID restore cash rounding for {rn}'),
                    )

            previous_notes = sale['notes'] if 'notes' in sale_keys and sale['notes'] else ''
            db.execute(
                "UPDATE sales SET status='completed', notes=? WHERE id=? AND status='voided'",
                (f"{previous_notes} | RESTORED by {self._username or 'superadmin'}: {reason}".strip(' |'),
                 int(sale_id)),
            )
            db.execute(
                "INSERT INTO sale_edits "
                "(sale_id,edited_by_id,edited_by_name,edit_type,"
                "field_name,old_value,new_value,reason) VALUES (?,?,?,?,?,?,?,?)",
                (int(sale_id), self._user_id, self._username or 'superadmin',
                 'UNVOID', 'status', 'voided', 'completed', reason),
            )
            self._reverse_void_journal(db, int(sale_id), reason)
            db.commit()
            _audit(
                self._user_id, self._username, 'UNVOID_SALE', 'sales',
                f"sale_id={sale_id} receipt={rn} reason={reason} "
                f"before=voided after=completed stock={'; '.join(stock_changes)}",
            )
            return {'success': True, 'status': 'completed', 'receipt_number': rn}
        except ValueError as exc:
            try:
                db.rollback()
            except Exception:
                pass
            return {'error': str(exc), 'status': 409}
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.exception('unvoid_sale failed')
            return {'error': str(exc), 'status': 500}
        finally:
            db.close()

    def _reapply_voided_layers(self, db, sale_id: int) -> None:
        try:
            uses = db.execute(
                "SELECT id, layer_id, quantity FROM cost_layer_uses "
                "WHERE sale_id=? AND reversed=1",
                (int(sale_id),),
            ).fetchall()
        except Exception:
            return
        for use in uses:
            layer = db.execute(
                "SELECT remaining_qty FROM cost_layers WHERE id=?", (use['layer_id'],)
            ).fetchone()
            if not layer or float(layer['remaining_qty'] or 0) + 1e-9 < float(use['quantity'] or 0):
                raise ValueError(
                    'A later stock movement used the quantity this void returned. '
                    'The receipt was not restored.'
                )
        for use in uses:
            changed = db.execute(
                "UPDATE cost_layers SET remaining_qty=remaining_qty-? "
                "WHERE id=? AND remaining_qty>=?",
                (float(use['quantity'] or 0), use['layer_id'], float(use['quantity'] or 0)),
            )
            if changed.rowcount != 1:
                raise ValueError(
                    'A later stock movement used the quantity this void returned. '
                    'The receipt was not restored.'
                )
            db.execute("UPDATE cost_layer_uses SET reversed=0 WHERE id=?", (use['id'],))

    def _reverse_void_journal(self, db, sale_id: int, reason: str) -> None:
        try:
            row = db.execute(
                "SELECT id FROM journal_entries WHERE source_module='sales' AND source_id=? "
                "AND entry_type='sale_void' AND status='posted' AND deleted_at IS NULL "
                "AND reversed_by_id IS NULL ORDER BY id DESC LIMIT 1",
                (str(int(sale_id)),),
            ).fetchone()
        except Exception:
            return
        if not row:
            return
        from desktop.utils.accounting_engine import reverse_journal
        result = reverse_journal(
            db, row['id'], reason=f'Unvoid: {reason}',
            user_id=self._user_id, username=self._username or 'superadmin',
            source_module='sales', source_id=str(int(sale_id)),
            entry_type='sale_unvoid',
        )
        if result.get('error') and 'already reversed' not in str(result.get('error')).lower():
            raise ValueError(result['error'])

    def get_sale_for_return(self, receipt: str) -> dict:
        """Lookup a completed sale with returnable line quantities."""
        receipt = (receipt or '').strip()
        if not receipt:
            return {'error': 'Receipt number is required.'}
        db = _db()
        try:
            sale = _row(db.execute(
                "SELECT * FROM sales WHERE receipt_number=?", (receipt,)
            ))
            if not sale:
                return {'error': f'No sale found with receipt: {receipt}'}
            status = (sale.get('status') or '').lower()
            if status != 'completed':
                return {'error': f'Cannot return a sale with status "{sale.get("status")}".'}
            items = _rows(db.execute(
                "SELECT * FROM sale_items WHERE sale_id=? ORDER BY id",
                (sale['id'],)
            ))
            out_items = []
            for it in items:
                sold = float(it.get('quantity') or 0)
                already = float(it.get('returned_qty') or 0)
                remaining = round(max(0.0, sold - already), 4)
                out_items.append({
                    **dict(it),
                    'sold_qty': sold,
                    'returned_qty': already,
                    'remaining_qty': remaining,
                })
            return {'success': True, 'sale': dict(sale), 'items': out_items}
        finally:
            db.close()

    def return_sale(self, sale_id: int, items: list, reason: str,
                    *, refund_method: str = 'cash', client_token: str = '') -> dict:
        """
        Partial product return against a completed sale.
        Restocks inventory, records a status='return' sale (negative totals),
        and bumps sale_items.returned_qty on the original.
        """
        if self._role not in ('admin', 'superadmin', 'manager'):
            return {'error': 'Insufficient permissions to process returns.'}
        reason = (reason or '').strip()
        if not reason:
            return {'error': 'A return reason is required.'}
        if not items:
            return {'error': 'Select at least one item to return.'}
        method = (refund_method or 'cash').strip() or 'cash'
        token = (client_token or '').strip()
        norm_items = []
        seen_lines = set()
        for spec in items:
            try:
                si_id = int(spec.get('sale_item_id') or 0)
                qty = round(float(spec.get('quantity')), 4)
            except (TypeError, ValueError):
                return {'error': 'Enter a valid return quantity.', 'status': 400}
            if si_id <= 0 or qty <= 0:
                return {'error': 'Enter a valid return quantity.', 'status': 400}
            if si_id in seen_lines:
                return {'error': 'Enter each sale line once on this return.', 'status': 400}
            seen_lines.add(si_id)
            norm_items.append({'sale_item_id': si_id, 'quantity': qty})
        norm_items.sort(key=lambda row: row['sale_item_id'])
        request_body = {
            'sale_id': int(sale_id),
            'items': norm_items,
            'reason': reason,
            'refund_method': method,
        }

        db = _db()
        try:
            db.execute("BEGIN IMMEDIATE")
            claim = _read_request_receipt(db, token, 'return_sale', request_body)
            if claim and claim.get('error'):
                db.rollback()
                return claim
            if claim and claim.get('duplicate'):
                db.rollback()
                return claim
            digest = (claim or {}).get('hash') or ''
            sale = db.execute(
                "SELECT * FROM sales WHERE id=?", (sale_id,)
            ).fetchone()
            if not sale:
                db.rollback()
                return {'error': 'Sale not found'}
            if (sale['status'] or '').lower() != 'completed':
                db.rollback()
                return {'error': f'Cannot return sale with status "{sale["status"]}".'}

            orig_rn = sale['receipt_number'] or str(sale_id)
            refund_total = 0.0
            restock_lines = []
            from desktop.utils.shop_time import business_day_iso, sale_created_at_for_day
            orig_day = ''
            try:
                orig_day = (sale['sale_date'] or '') if 'sale_date' in sale.keys() else ''
            except Exception:
                orig_day = ''
            if not orig_day:
                try:
                    orig_day = str(sale['created_at'] or '')[:10]
                except Exception:
                    orig_day = ''
            sale_date_s = business_day_iso(orig_day or None)
            created_at_s = sale_created_at_for_day(sale_date_s)
            now = created_at_s

            for spec in norm_items:
                si_id = int(spec['sale_item_id'])
                qty = float(spec['quantity'])
                line = db.execute(
                    "SELECT * FROM sale_items WHERE id=? AND sale_id=?",
                    (si_id, sale_id),
                ).fetchone()
                if not line:
                    db.rollback()
                    return {'error': f'Sale line #{si_id} not found on this receipt.'}
                sold = float(line['quantity'] or 0)
                already = float(line['returned_qty'] or 0) if 'returned_qty' in line.keys() else 0.0
                remaining = round(sold - already, 4)
                if qty > remaining + 0.0001:
                    db.rollback()
                    return {
                        'error': (
                            f'Cannot return {qty} of {line["product_name"]} — '
                            f'only {remaining} remaining.'
                        )
                    }
                unit = float(line['unit_price'] or 0)
                line_disc = float(line['discount'] or 0)
                # Pro-rate line discount
                disc_share = round(line_disc * (qty / sold), 2) if sold > 0 else 0.0
                line_total = round(qty * unit - disc_share, 2)
                refund_total = round(refund_total + line_total, 2)
                restock_lines.append({
                    'sale_item_id': si_id,
                    'product_id': line['product_id'],
                    'product_name': line['product_name'],
                    'sku': line['sku'] or '',
                    'quantity': qty,
                    'unit_price': unit,
                    'discount': disc_share,
                    'total': line_total,
                    'already': already,
                })

            if not restock_lines:
                db.rollback()
                return {'error': 'No valid return quantities.'}

            # Restock
            for rl in restock_lines:
                pid = rl['product_id']
                qty = rl['quantity']
                if not pid:
                    continue
                prod = db.execute(
                    "SELECT id, name, stock FROM products WHERE id=?", (pid,)
                ).fetchone()
                if not prod:
                    continue
                old_stock = float(prod['stock'] or 0)
                new_stock = round(old_stock + qty, 4)
                db.execute(
                    "UPDATE products SET stock=?, updated_at=? WHERE id=?",
                    (new_stock, now, pid),
                )
                db.execute(
                    "INSERT INTO stock_movements "
                    "(product_id,product_name,movement_type,qty_before,qty_change,"
                    "qty_after,reference,reason,user_id,username) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (pid, prod['name'], 'RETURN_RESTORE',
                     old_stock, qty, new_stock,
                     f"RETURN_sale={sale_id}_item={rl['sale_item_id']}",
                     f"Return from {orig_rn}: {reason}",
                     self._user_id, self._username or 'staff'),
                )
                from desktop.utils.stock_layers import restore_sale_product_qty
                restored = restore_sale_product_qty(db, sale_id, pid, qty)
                if restored.get('error'):
                    db.rollback()
                    return {'error': restored['error']}
                db.execute(
                    "UPDATE sale_items SET returned_qty=? WHERE id=?",
                    (round(rl['already'] + qty, 4), rl['sale_item_id']),
                )

            debt_applied = 0.0
            inv = db.execute(
                "SELECT id, balance, total_amount FROM debt_invoices WHERE sale_id=? "
                "AND COALESCE(status, '') NOT IN ('void', 'cancelled') "
                "ORDER BY id DESC LIMIT 1",
                (sale_id,),
            ).fetchone()
            if inv and float(inv['balance'] or 0) > 0.009:
                debt_applied = round(min(float(inv['balance']), refund_total), 2)
                new_bal = round(float(inv['balance']) - debt_applied, 2)
                new_total = round(max(0.0, float(inv['total_amount'] or 0) - debt_applied), 2)
                db.execute(
                    "UPDATE debt_invoices SET balance=?, total_amount=?, status=?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (new_bal, new_total, 'paid' if new_bal <= 0.009 else 'partial', inv['id']),
                )
            cash_refund = round(refund_total - debt_applied, 2)
            ret_rn = f"RET-{datetime.now().strftime('%Y%m%d%H%M%S%f')}-{sale_id}"
            db.execute(
                "INSERT INTO sales (receipt_number,cashier_id,cashier_name,subtotal,"
                "discount,tax,total,payment_method,amount_paid,change_amount,notes,"
                "status,original_sale_id,customer_id,sale_date,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ret_rn, self._user_id, self._username or 'staff',
                 -refund_total, 0, 0, -refund_total, method,
                 -cash_refund, 0,
                 f"RETURN of {orig_rn}: {reason}"
                 + (f" | debt reduced {debt_applied:.2f}" if debt_applied else ""),
                 'return', sale_id, sale['customer_id'] if 'customer_id' in sale.keys() else None,
                 sale_date_s, created_at_s),
            )
            ret_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            for rl in restock_lines:
                db.execute(
                    "INSERT INTO sale_items "
                    "(sale_id,product_id,product_name,sku,quantity,unit_price,discount,total)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (ret_id, rl['product_id'], rl['product_name'], rl['sku'],
                     -rl['quantity'], rl['unit_price'], rl['discount'], -rl['total']),
                )

            db.execute(
                "INSERT INTO sale_edits "
                "(sale_id,edited_by_id,edited_by_name,edit_type,"
                "field_name,old_value,new_value,reason) VALUES (?,?,?,?,?,?,?,?)",
                (sale_id, self._user_id, self._username or 'staff',
                 'RETURN', 'return', orig_rn, ret_rn, reason),
            )
            try:
                from desktop.utils.accounting_hooks import reverse_sale_journal
                # Soft: reverse journal against original is wrong for partial —
                # log only; full journal optional
                pass
            except Exception:
                pass

            result = {
                'success': True,
                'return_sale_id': ret_id,
                'receipt_number': ret_rn,
                'refund_total': refund_total,
                'cash_refund': cash_refund,
                'debt_reduced': debt_applied,
                'original_receipt': orig_rn,
            }
            _save_request_receipt(db, token, 'return_sale', digest, result)
            db.commit()
            _audit(self._user_id, self._username, 'RETURN_SALE', 'sales',
                   f"sale_id={sale_id} return_id={ret_id} receipt={ret_rn} "
                   f"refund={refund_total} reason={reason}")
            return result
        except Exception as e:
            db.rollback()
            logger.error(f"return_sale: {e}", exc_info=True)
            return {'error': str(e)}
        finally:
            db.close()

    def edit_sale(self, sale_id: int, data: dict) -> dict:
        """
        Super Admin only — full receipt edit.
        Updates quantities, prices, discounts, payment method, customer,
        add/remove lines; recalculates totals; adjusts inventory and debt;
        reverses/reposts accounting; logs sale_edits + audit.
        """
        if self._role != 'superadmin':
            _audit(self._user_id, self._username,
                   'EDIT_SALE_DENIED', 'sales',
                   f"sale_id={sale_id} role={self._role}")
            return {'error': 'Only Super Admin can edit sales.'}

        reason = (data.get('reason') or '').strip()
        if not reason:
            return {'error': 'An edit reason is required.'}
        token = str(data.get('client_token') or '').strip()
        edit_body = {
            'sale_id': int(sale_id),
            'reason': reason,
            'items': data.get('items'),
            'discount': data.get('discount'),
            'tax': data.get('tax'),
            'total': data.get('total'),
            'payment_method': data.get('payment_method'),
            'customer_id': data.get('customer_id'),
            'amount_paid': data.get('amount_paid'),
        }

        new_items = data.get('items')
        if new_items is not None:
            if not isinstance(new_items, list) or not new_items:
                return {'error': 'Sale must have at least one line item.'}

        db = _db()
        try:
            db.execute("BEGIN IMMEDIATE")
            claim = _read_request_receipt(db, token, 'edit_sale', edit_body)
            if claim and claim.get('error'):
                db.rollback()
                return claim
            if claim and claim.get('duplicate'):
                db.rollback()
                return claim
            digest = (claim or {}).get('hash') or ''
            sale = db.execute(
                "SELECT * FROM sales WHERE id=?", (sale_id,)
            ).fetchone()
            if not sale:
                db.rollback()
                return {'error': 'Sale not found'}
            status_l = (sale['status'] or '').lower()
            reinstate = status_l in ('void', 'voided')
            if status_l not in ('completed', 'void', 'voided'):
                db.rollback()
                return {'error': f'Cannot edit sale with status "{sale["status"]}".'}
            if reinstate and self._role != 'superadmin':
                db.rollback()
                return {'error': 'Only Super Admin can reinstate and edit voided sales.'}

            rn = sale['receipt_number'] or str(sale_id)
            old_items = _rows(db.execute(
                "SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)
            ))

            # Snapshot header for audit
            old_snap = {
                'status': sale['status'] or '',
                'subtotal': float(sale['subtotal'] or 0),
                'discount': float(sale['discount'] or 0),
                'tax': float(sale['tax'] or 0),
                'total': float(sale['total'] or 0),
                'payment_method': sale['payment_method'] or '',
                'amount_paid': float(sale['amount_paid'] or 0),
                'customer_id': sale['customer_id'],
                'items': [
                    {
                        'product_id': it.get('product_id'),
                        'product_name': it.get('product_name'),
                        'quantity': float(it.get('quantity') or 0),
                        'unit_price': float(it.get('unit_price') or 0),
                        'discount': float(it.get('discount') or 0),
                        'total': float(it.get('total') or 0),
                    }
                    for it in old_items
                ],
            }

            # Normalize new items
            if new_items is None:
                new_items = old_snap['items']
            normalized = []
            for raw in new_items:
                pid = raw.get('product_id')
                qty = round(float(raw.get('quantity') or 0), 4)
                price = round(float(raw.get('unit_price') or 0), 4)
                disc = round(float(raw.get('discount') or 0), 4)
                if qty <= 0:
                    continue
                name = (raw.get('product_name') or '').strip()
                sku = (raw.get('sku') or '').strip()
                if pid:
                    prod = db.execute(
                        "SELECT name, sku FROM products WHERE id=?", (pid,)
                    ).fetchone()
                    if prod:
                        name = name or (prod['name'] or '')
                        sku = sku or (prod['sku'] or '')
                line_total = round(max(0.0, qty * price - disc), 2)
                normalized.append({
                    'product_id': int(pid) if pid else None,
                    'product_name': name or 'Item',
                    'sku': sku,
                    'quantity': qty,
                    'unit_price': price,
                    'discount': disc,
                    'total': line_total,
                })
            if not normalized:
                db.rollback()
                return {'error': 'Sale must have at least one line item.'}

            subtotal = round(sum(i['quantity'] * i['unit_price'] for i in normalized), 2)
            item_disc = round(sum(i['discount'] for i in normalized), 2)
            header_disc = data.get('discount')
            if header_disc is None:
                header_disc = float(sale['discount'] or 0)
            else:
                header_disc = round(float(header_disc or 0), 2)
            # Prefer explicit header discount; if only line discounts, keep sale.discount
            # as header and keep line discounts in items (same as create_sale pattern).
            tax = data.get('tax')
            if tax is None:
                tax = float(sale['tax'] or 0)
            else:
                tax = round(float(tax or 0), 2)
            total = round(
                float(data['total']) if data.get('total') is not None
                else max(0.0, subtotal - header_disc - item_disc + tax),
                2
            )

            payment_method = data.get('payment_method')
            if payment_method is None:
                payment_method = sale['payment_method'] or 'cash'
            payment_method = str(payment_method).strip() or 'cash'

            customer_id = data.get('customer_id') if 'customer_id' in data else sale['customer_id']
            if customer_id is not None and customer_id != '':
                customer_id = int(customer_id)
            else:
                customer_id = None

            amount_paid = data.get('amount_paid')
            method_l = payment_method.lower()
            is_credit = method_l in ('credit sale', 'credit', 'part payment')
            if amount_paid is None:
                if is_credit and method_l != 'part payment':
                    amount_paid = 0.0
                else:
                    amount_paid = float(sale['amount_paid'] or 0)
            amount_paid = round(float(amount_paid or 0), 2)
            if not is_credit and amount_paid < 0.009:
                amount_paid = total

            # Inventory:
            # - Completed edits: restore old lines then deduct new.
            # - Voided reinstate: stock was already restored on void — only deduct new lines.
            if not reinstate:
                self._restock_sale_items(
                    db, sale_id, receipt=rn,
                    reason=f"Sale edit reverse stock: {rn} — {reason}",
                    movement_type='SALE_EDIT_RESTORE',
                    skip_if_restored=False,
                )
            db.execute("DELETE FROM sale_items WHERE sale_id=?", (sale_id,))
            for it in normalized:
                db.execute(
                    "INSERT INTO sale_items "
                    "(sale_id,product_id,product_name,sku,quantity,unit_price,discount,total) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (sale_id, it['product_id'], it['product_name'], it['sku'],
                     it['quantity'], it['unit_price'], it['discount'], it['total'])
                )
            self._deduct_sale_items_stock(
                db, sale_id, normalized, receipt=rn,
                movement_type='SALE_REINSTATE' if reinstate else 'SALE_EDIT',
            )

            now = datetime.now().isoformat()
            reinstate_note = (
                f' | REINSTATED from voided & edited: {reason}' if reinstate
                else f' | EDITED: {reason}'
            )
            db.execute(
                "UPDATE sales SET subtotal=?, discount=?, tax=?, total=?, "
                "payment_method=?, amount_paid=?, customer_id=?, "
                "original_total=?, notes=?, change_amount=?, status='completed' WHERE id=?",
                (
                    subtotal, header_disc, tax, total, payment_method, amount_paid,
                    customer_id, total,
                    ((sale['notes'] or '') + reinstate_note).strip(' |'),
                    max(0.0, amount_paid - total) if not is_credit else float(sale['change_amount'] or 0),
                    sale_id,
                )
            )

            # Linked debt invoice sync (include cancelled invoices when reinstating)
            debt = db.execute(
                "SELECT * FROM debt_invoices WHERE sale_id=? "
                "AND LOWER(COALESCE(status,'')) NOT IN ('written_off') "
                "ORDER BY CASE WHEN LOWER(COALESCE(status,''))='cancelled' THEN 1 ELSE 0 END, id DESC "
                "LIMIT 1",
                (sale_id,)
            ).fetchone()
            if is_credit and customer_id:
                paid = float(debt['amount_paid'] or 0) if debt else 0.0
                if paid > total + 0.009:
                    db.rollback()
                    return {
                        'error': (
                            f'Debt payments ({paid:,.2f}) exceed new sale total '
                            f'({total:,.2f}). Reduce payments first.'
                        )
                    }
                bal = round(max(0.0, total - paid), 2)
                status = 'paid' if bal <= 0.009 else ('partial' if paid > 0.009 else 'unpaid')
                if debt:
                    db.execute(
                        "UPDATE debt_invoices SET customer_id=?, total_amount=?, "
                        "balance=?, status=?, updated_at=?, notes=? WHERE id=?",
                        (
                            customer_id, total, bal, status, now,
                            f"{(debt['notes'] or '').strip()}\n"
                            f"{'REINSTATED' if reinstate else 'EDITED'}: {reason}".strip(),
                            debt['id'],
                        )
                    )
                else:
                    inv_num = f"INV-EDIT-{sale_id}-{datetime.now().strftime('%H%M%S')}"
                    cust_name = ''
                    if customer_id:
                        crow = db.execute(
                            "SELECT name FROM customers WHERE id=?", (customer_id,)
                        ).fetchone()
                        if crow:
                            cust_name = crow['name'] or ''
                    db.execute(
                        "INSERT INTO debt_invoices "
                        "(invoice_number,sale_id,receipt_number,customer_id,customer_name,"
                        "total_amount,amount_paid,balance,status,notes,created_at,updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (inv_num, sale_id, rn, customer_id, cust_name or 'Customer',
                         total, 0.0, total, 'unpaid',
                         f'Created on sale {"reinstate" if reinstate else "edit"}: {reason}',
                         now, now)
                    )
            elif debt and not is_credit:
                # Switched off credit — cancel open debt if unpaid
                paid = float(debt['amount_paid'] or 0)
                if paid > 0.009:
                    db.rollback()
                    return {
                        'error': (
                            'Cannot remove credit payment method while debt '
                            f'payments ({paid:,.2f}) exist.'
                        )
                    }
                db.execute(
                    "UPDATE debt_invoices SET status='cancelled', balance=0, "
                    "notes=?, updated_at=? WHERE id=?",
                    (f"CANCELLED on sale edit (no longer credit): {reason}",
                     now, debt['id'])
                )

            # Field-level sale_edits
            def _log_edit(edit_type, field, old_v, new_v):
                if str(old_v) == str(new_v):
                    return
                db.execute(
                    "INSERT INTO sale_edits "
                    "(sale_id,edited_by_id,edited_by_name,edit_type,"
                    "field_name,old_value,new_value,reason) VALUES (?,?,?,?,?,?,?,?)",
                    (sale_id, self._user_id, self._username or 'admin',
                     edit_type, field, str(old_v), str(new_v), reason)
                )

            _log_edit('EDIT', 'status', old_snap.get('status'), 'completed')
            _log_edit('EDIT', 'total', old_snap['total'], total)
            _log_edit('EDIT', 'discount', old_snap['discount'], header_disc)
            _log_edit('EDIT', 'payment_method', old_snap['payment_method'], payment_method)
            _log_edit('EDIT', 'customer_id', old_snap['customer_id'], customer_id)
            _log_edit('EDIT', 'amount_paid', old_snap['amount_paid'], amount_paid)
            _log_edit(
                'EDIT_ITEMS', 'items',
                json.dumps(old_snap['items'], default=str),
                json.dumps(normalized, default=str),
            )

            try:
                from desktop.utils.accounting_hooks import (
                    reverse_sale_journal, post_sale_journal,
                )
                reverse_sale_journal(
                    db, sale_id, reason=f'Sale edit: {reason}',
                    user_id=self._user_id, username=self._username or 'admin',
                    safe=True)
                post_sale_journal(
                    db, sale_id,
                    user_id=self._user_id, username=self._username or 'admin',
                    safe=True)
            except Exception as _je:
                logger.error('edit_sale accounting: %s', _je, exc_info=True)

            result = {
                'success': True,
                'sale_id': sale_id,
                'receipt_number': rn,
                'total': total,
                'items': normalized,
                'reinstated': reinstate,
            }
            _save_request_receipt(db, token, 'edit_sale', digest, result)
            db.commit()
            action = 'REINSTATE_EDIT_SALE' if reinstate else 'EDIT_SALE'
            _audit(
                self._user_id, self._username, action, 'sales',
                f"sale_id={sale_id} receipt={rn} total={old_snap['total']}→{total} "
                f"method={payment_method} reinstate={reinstate} reason={reason}"
            )
            return result
        except ValueError as e:
            db.rollback()
            return {'error': str(e)}
        except Exception as e:
            db.rollback()
            logger.error(f"edit_sale: {e}", exc_info=True)
            return {'error': str(e)}
        finally:
            db.close()

    def get_stock_movements(self, product_id=None, limit=200) -> list:
        db = _db()
        try:
            if product_id:
                return _rows(db.execute(
                    "SELECT * FROM stock_movements WHERE product_id=? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (product_id, limit)
                ))
            return _rows(db.execute(
                "SELECT * FROM stock_movements ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ))
        finally:
            db.close()

    def inventory_value(self) -> dict:
        db = _db()
        try:
            from desktop.utils.stock_layers import inventory_valuation
            return inventory_valuation(db)
        finally:
            db.close()

    def get_product_history(self, product_id: int, limit: int = 300) -> dict:
        """Full product timeline: profile + stock adjustments + sales lines."""
        db = _db()
        try:
            prod = _row(db.execute("SELECT * FROM products WHERE id=?", (product_id,)))
            if not prod:
                return {'product': None, 'movements': [], 'sales': []}
            movements = _rows(db.execute(
                "SELECT * FROM stock_movements WHERE product_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (product_id, limit)
            ))
            sales = _rows(db.execute("""
                SELECT si.id as line_id, si.quantity, si.unit_price, si.discount, si.total,
                       s.id as sale_id, s.receipt_number, s.created_at, s.cashier_name,
                       s.payment_method, s.status
                FROM sale_items si
                JOIN sales s ON s.id = si.sale_id
                WHERE si.product_id=?
                ORDER BY s.created_at DESC
                LIMIT ?
            """, (product_id, limit)))
            from desktop.utils.security import client_actor, sees_product_cost
            from desktop.utils.stock_layers import product_batch_view
            see_cost = sees_product_cost(client_actor(self))
            if not see_cost:
                prod.pop('cost_price', None)
            view = product_batch_view(db, int(product_id), see_cost)
            return {
                'product': prod,
                'movements': movements,
                'sales': sales,
                'batches': view['batches'],
                'batch_summary': view['batch_summary'],
                'see_cost': see_cost,
            }
        finally:
            db.close()

    def get_sale_edits(self, sale_id=None) -> list:
        db = _db()
        try:
            if sale_id:
                return _rows(db.execute(
                    "SELECT * FROM sale_edits WHERE sale_id=? ORDER BY created_at DESC",
                    (sale_id,)
                ))
            return _rows(db.execute(
                "SELECT * FROM sale_edits ORDER BY created_at DESC LIMIT 500"
            ))
        finally:
            db.close()

    # ── REPORTS ───────────────────────────────────────────────────────────────────

    def get_report_summary(self, start: str, end: str) -> dict:
        db = _db()
        try:
            summary = _row(db.execute(f"""
                SELECT COUNT(*) as total_transactions,
                       COALESCE(SUM(total),0) as total_revenue,
                       COALESCE(SUM(
                           CASE WHEN COALESCE(original_total,0) > 0 THEN original_total
                                ELSE total - COALESCE(cash_rounding_adj,0) END
                       ),0) as original_total,
                       COALESCE(SUM(COALESCE(cash_rounding_adj,0)),0) as total_cash_rounding,
                       COALESCE(AVG(total),0) as avg_transaction,
                       COALESCE(SUM(discount),0) as total_discounts,
                       COALESCE(SUM(tax),0) as total_tax,
                       COALESCE(SUM(CASE WHEN LOWER(COALESCE(payment_method,''))='cash'
                                         THEN amount_paid ELSE 0 END),0) as cash_received,
                       /* Money actually received on sales (excludes unpaid credit totals) */
                       COALESCE(SUM(
                           CASE
                             WHEN LOWER(COALESCE(payment_method,'')) IN
                                  ('credit sale','credit')
                                  AND COALESCE(amount_paid,0) < 0.01
                             THEN 0
                             /* amount_paid is money kept. Change is extra cash
                                handed back. Subtract change only when the stored
                                amount still includes that extra cash. */
                             WHEN COALESCE(amount_paid,0) > COALESCE(total,0) + 0.02
                             THEN COALESCE(amount_paid,0) - COALESCE(change_amount,0)
                             ELSE COALESCE(amount_paid,0)
                           END
                       ),0) as collected_from_sales,
                       COALESCE(SUM(CASE
                         WHEN LOWER(COALESCE(payment_method,'')) IN
                              ('credit sale','credit','part payment')
                         THEN total ELSE 0 END),0) as credit_sales_total,
                       COALESCE(SUM(CASE
                         WHEN LOWER(COALESCE(payment_method,'')) IN
                              ('credit sale','credit')
                              AND COALESCE(amount_paid,0) < 0.01
                         THEN total ELSE 0 END),0) as credit_sales_outstanding,
                       COALESCE(SUM(CASE
                         WHEN LOWER(COALESCE(payment_method,''))='cash'
                          AND COALESCE(amount_paid,0) > COALESCE(total,0) + 0.02
                         THEN COALESCE(amount_paid,0) - COALESCE(change_amount,0)
                         WHEN LOWER(COALESCE(payment_method,''))='cash'
                         THEN COALESCE(amount_paid,0)
                         ELSE 0 END),0) as cash_sales_collected,
                       COALESCE(SUM(CASE
                         WHEN LOWER(COALESCE(payment_method,'')) IN
                              ('m-pesa','mpesa','mobile money')
                         THEN COALESCE(amount_paid,0) ELSE 0 END),0) as mpesa_collected,
                       COALESCE(SUM(CASE
                         WHEN LOWER(COALESCE(payment_method,''))='card'
                         THEN COALESCE(amount_paid,0) ELSE 0 END),0) as card_collected,
                       COALESCE(SUM(CASE
                         WHEN LOWER(COALESCE(payment_method,'')) IN
                              ('bank transfer','bank','bank payment')
                         THEN COALESCE(amount_paid,0) ELSE 0 END),0) as bank_collected
                FROM sales WHERE {_sale_day_expr()} BETWEEN ? AND ?
                AND status IN ('completed','return')
            """, (start, end)))

            debt_collected_row = _row(db.execute("""
                SELECT COALESCE(SUM(amount),0) as debt_collected,
                       COALESCE(SUM(CASE
                         WHEN COALESCE(notes,'') LIKE 'Initial payment%' THEN 0
                         ELSE amount END),0) as later_collected
                FROM debt_payments
                WHERE date(created_at) BETWEEN ? AND ?
                  AND COALESCE(reversed,0)=0
            """, (start, end)))
            debt_collected = float((debt_collected_row or {}).get('debt_collected') or 0)
            later_collected = float((debt_collected_row or {}).get('later_collected') or 0)

            summary = dict(summary or {})
            # One formula for the till and the dashboard. A mixed sale's cash
            # is not in the cash-only SQL total, and its change must not be
            # counted as money kept.
            from desktop.utils.payment_tenders import collected_from_sales
            rolled_rows = _rows(db.execute(f"""
                SELECT payment_method, total, amount_paid, change_amount, payment_tenders
                FROM sales
                WHERE {_sale_day_expr()} BETWEEN ? AND ?
                  AND status IN ('completed','return')
            """, (start, end)))
            rolled = collected_from_sales(rolled_rows)
            summary['cash_sales_collected'] = rolled['cash_collected']
            summary['mpesa_collected'] = rolled['mpesa_collected']
            summary['card_collected'] = rolled['card_collected']
            summary['bank_collected'] = rolled['bank_collected']
            summary['other_collected'] = rolled['other_collected']
            collected_sales = float(summary.get('collected_from_sales') or 0)
            # Opening tender is already in the sale's amount_paid. Add only later collections.
            summary['debt_collected'] = debt_collected
            from desktop.utils.financials import compute_financials, public_financials
            figures = compute_financials(db, start, end)
            summary['collected_revenue'] = figures['total_collected']
            summary['total_sales'] = figures['total_sales']
            summary['total_revenue'] = figures['total_sales']
            summary['paid_sales'] = figures['paid_sales']
            summary['new_credit'] = figures['new_credit']
            summary['debt_repayments'] = figures['debt_repayments']
            summary['gross_profit'] = figures['gross_profit']
            summary['realized_gross_profit'] = figures['realized_gross_profit']
            summary['unrealized_gross_profit'] = figures['unrealized_gross_profit']
            summary['cogs'] = figures['cogs']
            summary['uncosted_lines'] = figures['uncosted_lines']
            summary['profit_note'] = figures['profit_note']
            summary['expenses'] = figures['expenses']
            summary['net_operating_result'] = figures['net_operating_result']
            summary['outstanding_debt'] = figures['outstanding_debt']
            summary['supplier_outstanding'] = figures['supplier_outstanding']
            summary['supplier_paid'] = figures['supplier_paid']
            summary['supplier_invoiced'] = figures['supplier_invoiced']
            summary['supplier_overdue'] = figures['supplier_overdue']
            summary['inventory_cost_value'] = figures['inventory_cost_value']
            summary['finance'] = figures
            role = (getattr(self, '_role', '') or '').lower()
            if role == 'cashier':
                if str(start)[:10] != str(end)[:10]:
                    return {
                        'error': 'A cashier can open one day, not a date range.',
                        'status': 403,
                    }
                safe = public_financials(figures, 'cashier')
                return {
                    'summary': {
                        'total_transactions': figures['completed_sale_count'],
                        'total_revenue': figures['total_sales'],
                        'total_sales': figures['total_sales'],
                    },
                    'top_products': [],
                    'by_payment': [],
                    'finance': safe,
                }

            top_products = _rows(db.execute(f"""
                SELECT si.product_name,
                       SUM(si.quantity) as qty_sold,
                       SUM(si.total)    as revenue,
                       COUNT(si.id)     as transactions
                FROM sale_items si JOIN sales s ON si.sale_id=s.id
                WHERE {_sale_day_expr('s')} BETWEEN ? AND ?
                  AND s.status IN ('completed','return')
                GROUP BY si.product_name ORDER BY revenue DESC LIMIT 20
            """, (start, end)))

            by_payment = _rows(db.execute(f"""
                SELECT payment_method,COUNT(*) as count,SUM(total) as total
                FROM sales WHERE {_sale_day_expr()} BETWEEN ? AND ?
                AND status IN ('completed','return') GROUP BY payment_method
            """, (start, end)))

            return {
                'summary':      summary or {},
                'top_products': top_products,
                'by_payment':   by_payment,
            }
        finally:
            db.close()

    def get_sales_trend(self, days: int = 7, start=None, end=None) -> list:
        """Daily completed revenue. Pass start and end for a chosen range."""
        from datetime import date, timedelta
        if start and end:
            start = date.fromisoformat(str(start)[:10])
            end = date.fromisoformat(str(end)[:10])
            if end < start:
                start, end = end, start
            if (end - start).days > 92:
                start = end - timedelta(days=92)
        else:
            days = max(1, min(int(days or 7), 62))
            end = date.today()
            start = end - timedelta(days=days - 1)
        db = _db()
        try:
            from desktop.utils.financials import sale_day_sql
            day = sale_day_sql()
            rows = _rows(db.execute(f"""
                SELECT {day} as d,
                       COUNT(*) as txn_count,
                       COALESCE(SUM(total), 0) as revenue
                FROM sales
                WHERE {day} BETWEEN ? AND ?
                  AND status IN ('completed','return')
                GROUP BY {day}
            """, (start.isoformat(), end.isoformat())))
            by_day = {r['d']: r for r in rows}
            out = []
            cur = start
            while cur <= end:
                key = cur.isoformat()
                r = by_day.get(key) or {}
                out.append({
                    'date': key,
                    'label': cur.strftime('%a'),
                    'revenue': float(r.get('revenue') or 0),
                    'count': int(r.get('txn_count') or 0),
                })
                cur += timedelta(days=1)
            return out
        except Exception:
            return []
        finally:
            db.close()

    # ── NOTES ─────────────────────────────────────────────────────────────────────

    def get_notes(self) -> list:
        db = _db()
        try:
            return _rows(db.execute(
                "SELECT * FROM notes ORDER BY COALESCE(pinned,0) DESC, updated_at DESC"
            ))
        finally:
            db.close()

    def create_note(self, data: dict) -> dict:
        db = _db()
        try:
            pinned = 1 if data.get('pinned') else 0
            cur = db.execute(
                "INSERT INTO notes (user_id,title,content,pinned) VALUES (?,?,?,?)",
                (self._user_id, data.get('title', ''), data.get('content', ''), pinned)
            )
            db.commit()
            return {'success': True, 'id': cur.lastrowid}
        finally:
            db.close()

    def update_note(self, nid: int, data: dict) -> dict:
        db = _db()
        try:
            if 'pinned' in data:
                db.execute(
                    "UPDATE notes SET title=?,content=?,pinned=?,updated_at=? WHERE id=?",
                    (data.get('title', ''), data.get('content', ''),
                     1 if data.get('pinned') else 0,
                     datetime.now().isoformat(), nid)
                )
            else:
                db.execute(
                    "UPDATE notes SET title=?,content=?,updated_at=? WHERE id=?",
                    (data.get('title', ''), data.get('content', ''),
                     datetime.now().isoformat(), nid)
                )
            db.commit()
            return {'success': True}
        finally:
            db.close()

    def delete_note(self, nid: int) -> dict:
        db = _db()
        try:
            db.execute("DELETE FROM notes WHERE id=?", (nid,))
            db.commit()
            return {'success': True}
        finally:
            db.close()

    # ── AUDIT LOG ─────────────────────────────────────────────────────────────────

    def get_audit_log(self) -> list:
        db = _db()
        try:
            return _rows(db.execute(
                "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 500"
            ))
        finally:
            db.close()

    # ── CUSTOMERS ─────────────────────────────────────────────────────────────

    def get_customers(self) -> list:
        db = _db()
        try:
            return _rows(db.execute(
                "SELECT c.*, "
                "COALESCE(SUM(di.balance),0) as total_outstanding, "
                "COUNT(di.id) as open_invoices, "
                "COALESCE((SELECT balance FROM customer_wallet cw WHERE cw.customer_id=c.id),0) "
                "as wallet_balance "
                "FROM customers c "
                "LEFT JOIN debt_invoices di ON c.id=di.customer_id AND di.status NOT IN ('paid','cancelled') "
                "WHERE c.is_active=1 GROUP BY c.id ORDER BY c.name"
            ))
        finally:
            db.close()

    def create_customer(self, data: dict) -> dict:
        db = _db()
        try:
            name = (data.get('name') or '').strip()
            phone = (data.get('phone') or '').strip()
            if not name:
                return {'error': 'Customer name is required.'}
            # Phone is optional; when provided, soft-check digit length
            if phone:
                digits = ''.join(ch for ch in phone if ch.isdigit())
                if len(digits) < 9 or len(digits) > 15:
                    return {'error': 'Enter a valid phone number or leave it blank.'}
            cust_cols = {r[1] for r in db.execute("PRAGMA table_info(customers)").fetchall()}
            if 'customer_type' in cust_cols and 'national_id' in cust_cols:
                db.execute(
                    "INSERT INTO customers (name,phone,email,address,credit_limit,notes,national_id,customer_type) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (name, phone, data.get('email', ''),
                     data.get('address', ''), data.get('credit_limit', 0),
                     data.get('notes', ''), data.get('national_id', '') or '',
                     data.get('customer_type', 'Retail') or 'Retail')
                )
            elif 'customer_type' in cust_cols:
                db.execute(
                    "INSERT INTO customers (name,phone,email,address,credit_limit,notes,customer_type) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (name, phone, data.get('email', ''),
                     data.get('address', ''), data.get('credit_limit', 0),
                     data.get('notes', ''),
                     data.get('customer_type', 'Retail') or 'Retail')
                )
            elif 'national_id' in cust_cols:
                db.execute(
                    "INSERT INTO customers (name,phone,email,address,credit_limit,notes,national_id) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (name, phone, data.get('email', ''),
                     data.get('address', ''), data.get('credit_limit', 0),
                     data.get('notes', ''), data.get('national_id', '') or '')
                )
            else:
                db.execute(
                    "INSERT INTO customers (name,phone,email,address,credit_limit,notes) "
                    "VALUES (?,?,?,?,?,?)",
                    (name, phone, data.get('email', ''),
                     data.get('address', ''), data.get('credit_limit', 0),
                     data.get('notes', ''))
                )
            db.commit()
            cid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            _audit(self._user_id, self._username, 'CREATE_CUSTOMER', 'debt',
                   f"name={name} phone={phone}")
            return {'success': True, 'customer_id': cid}
        except sqlite3.IntegrityError:
            return {'error': 'Customer already exists'}
        finally:
            db.close()

    def update_customer(self, cid: int, data: dict) -> dict:
        db = _db()
        try:
            fields, values = [], []
            for f in ('name', 'phone', 'email', 'address', 'credit_limit',
                      'notes', 'is_active', 'national_id', 'customer_type'):
                if f in data:
                    fields.append(f"{f}=?")
                    values.append(data[f])
            if fields:
                # Skip columns that may not exist yet
                cust_cols = {r[1] for r in db.execute("PRAGMA table_info(customers)").fetchall()}
                filtered = []
                filtered_vals = []
                for fld, val in zip(fields, values):
                    col = fld.split('=')[0]
                    if col not in cust_cols:
                        continue
                    filtered.append(fld)
                    filtered_vals.append(val)
                if filtered:
                    filtered_vals.append(cid)
                    db.execute(
                        f"UPDATE customers SET {','.join(filtered)} WHERE id=?",
                        filtered_vals)
                    db.commit()
            return {'success': True}
        finally:
            db.close()

    def get_customer(self, cid: int) -> dict:
        db = _db()
        try:
            c = _row(db.execute("SELECT * FROM customers WHERE id=?", (cid,)))
            if not c:
                return {}
            invoices = _rows(db.execute(
                "SELECT * FROM debt_invoices WHERE customer_id=? ORDER BY created_at DESC", (cid,)
            ))
            payments = _rows(db.execute(
                "SELECT dp.*, di.invoice_number, di.receipt_number FROM debt_payments dp "
                "JOIN debt_invoices di ON dp.invoice_id=di.id "
                "WHERE di.customer_id=? ORDER BY dp.created_at DESC", (cid,)
            ))
            total_owed = sum(i['balance'] for i in invoices if i['status'] not in ('paid','cancelled'))
            total_paid = sum(
                float(p['amount'] or 0) for p in payments if int(p.get('reversed') or 0) != 1
            )
            wallet = db.execute(
                "SELECT balance FROM customer_wallet WHERE customer_id=?", (cid,)
            ).fetchone()
            c['invoices'] = invoices
            c['payments'] = payments
            c['total_outstanding'] = round(float(total_owed or 0), 2)
            c['total_paid'] = round(total_paid, 2)
            c['unapplied_credit'] = round(float(wallet[0] or 0), 2) if wallet else 0.0
            c['open_invoices'] = len([i for i in invoices if i['status'] not in ('paid', 'cancelled')])
            return c
        finally:
            db.close()

    def search_customers(self, q: str) -> list:
        db = _db()
        try:
            q2 = f"%{q}%"
            return _rows(db.execute(
                "SELECT * FROM customers WHERE is_active=1 AND (name LIKE ? OR phone LIKE ? OR email LIKE ?) ORDER BY name LIMIT 20",
                (q2, q2, q2)
            ))
        finally:
            db.close()

    # ── DEBT INVOICES ──────────────────────────────────────────────────────────

    def _next_invoice_number(self, db) -> str:
        today = datetime.now().strftime('%Y%m%d')
        count = db.execute(
            "SELECT COUNT(*) FROM debt_invoices WHERE date(created_at)=date('now')"
        ).fetchone()[0]
        return f"INV-{today}-{count+1:04d}"

    def _next_payment_receipt(self, db) -> str:
        today = datetime.now().strftime('%Y%m%d')
        count = db.execute(
            "SELECT COUNT(*) FROM debt_payments WHERE date(created_at)=date('now')"
        ).fetchone()[0]
        return f"PAY-{today}-{count+1:04d}"

    def create_debt_invoice(self, data: dict, conn=None) -> dict:
        """
        Create a debt invoice linked to a completed sale.
        Required: customer_id, sale_id, receipt_number, total_amount.
        Orphan debts (no sale / no invoice) are rejected.

        Pass ``conn`` to write inside the caller's open transaction. The caller
        commits or rolls back. A standalone call commits its own connection.
        """
        own = conn is None
        db = conn if conn is not None else _db()
        try:
            customer_id = data.get('customer_id')
            sale_id = data.get('sale_id')
            receipt_number = (data.get('receipt_number') or '').strip()

            if not customer_id:
                return {'error': 'Customer is required — cannot create debt without a customer.'}
            if not sale_id:
                return {
                    'error': 'Sale is required — debts must link to a completed POS sale. '
                             'Use Credit Sale / Part Payment on the POS screen.'
                }
            if not receipt_number:
                return {
                    'error': 'Invoice/receipt number is required — debts must link to a completed sale.'
                }

            cust = _row(db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)))
            if not cust:
                return {'error': 'Customer not found'}

            sale = _row(db.execute("SELECT * FROM sales WHERE id=?", (int(sale_id),)))
            if not sale:
                return {'error': 'Linked sale not found — cannot create orphan debt.'}
            if (sale.get('status') or 'completed') == 'voided':
                return {'error': 'Cannot create debt for a voided sale.'}
            sale_rn = (sale.get('receipt_number') or '').strip()
            if sale_rn and sale_rn != receipt_number:
                return {
                    'error': f'Receipt mismatch: sale has {sale_rn}, got {receipt_number}.'
                }
            # Prefer canonical receipt from sale
            receipt_number = sale_rn or receipt_number

            # Prevent duplicate debt for same sale (idempotent success)
            existing = _row(db.execute(
                "SELECT id, invoice_number, balance, amount_paid, status FROM debt_invoices "
                "WHERE sale_id=? AND status NOT IN ('cancelled')",
                (int(sale_id),)
            ))
            if existing:
                return {
                    'success': True,
                    'already_existed': True,
                    'invoice_id': existing.get('id'),
                    'invoice_number': existing.get('invoice_number'),
                    'balance': existing.get('balance'),
                    'amount_paid': existing.get('amount_paid'),
                    'sale_id': int(sale_id),
                    'receipt_number': receipt_number,
                }

            total = float(data['total_amount'])
            paid = float(data.get('amount_paid', 0) or 0)
            if total <= 0:
                return {'error': 'Debt amount must be greater than zero.'}
            balance = round(total - paid, 2)

            if balance < 0:
                return {'error': 'Amount paid exceeds total — no debt to record.'}
            if balance == 0 and paid > 0:
                # Fully paid at sale — still record as paid invoice for history
                pass

            inv_num = self._next_invoice_number(db)
            status = 'paid' if balance == 0 else ('partial' if paid > 0 else 'pending')
            if getattr(APIClient, '_test_fault', None) == 'debt-insert':
                raise RuntimeError('injected debt failure')

            db.execute(
                "INSERT INTO debt_invoices (invoice_number,sale_id,receipt_number,"
                "customer_id,customer_name,customer_phone,total_amount,amount_paid,"
                "balance,status,due_date,cashier_id,cashier_name,notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (inv_num, int(sale_id), receipt_number,
                 int(customer_id), cust['name'], cust.get('phone', ''),
                 total, paid, balance, status,
                 data.get('due_date'), self._user_id,
                 self._username or data.get('cashier_name', 'staff'),
                 data.get('notes', ''))
            )
            inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

            if paid > 0:
                pay_receipt = self._next_payment_receipt(db)
                dp_cols = {r[1] for r in db.execute("PRAGMA table_info(debt_payments)").fetchall()}
                if 'payment_reference' in dp_cols:
                    db.execute(
                        "INSERT INTO debt_payments (payment_receipt,invoice_id,customer_id,"
                        "amount,payment_method,payment_reference,balance_before,balance_after,"
                        "cashier_id,cashier_name,notes) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (pay_receipt, inv_id, int(customer_id),
                         paid, data.get('payment_method', 'cash'),
                         data.get('payment_reference', '') or receipt_number,
                         total, balance,
                         self._user_id, self._username or 'staff',
                         f"Initial payment on invoice {inv_num}")
                    )
                else:
                    db.execute(
                        "INSERT INTO debt_payments (payment_receipt,invoice_id,customer_id,"
                        "amount,payment_method,balance_before,balance_after,cashier_id,cashier_name,notes) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (pay_receipt, inv_id, int(customer_id),
                         paid, data.get('payment_method', 'cash'),
                         total, balance,
                         self._user_id, self._username or 'staff',
                         f"Initial payment on invoice {inv_num}")
                    )

            if own:
                db.commit()
                _audit(self._user_id, self._username, 'CREATE_INVOICE', 'debt',
                       f"inv={inv_num} sale={sale_id} receipt={receipt_number} "
                       f"customer={cust['name']} total={total} paid={paid} balance={balance}")
            else:
                _audit(self._user_id, self._username, 'CREATE_INVOICE', 'debt',
                       f"inv={inv_num} sale={sale_id} receipt={receipt_number} "
                       f"customer={cust['name']} total={total} paid={paid} balance={balance}",
                       conn=db)
            return {
                'success': True,
                'invoice_number': inv_num,
                'invoice_id': inv_id,
                'balance': balance,
                'sale_id': int(sale_id),
                'receipt_number': receipt_number,
            }
        except Exception as e:
            if own:
                db.rollback()
                logger.error(f"create_debt_invoice: {e}", exc_info=True)
                return {'error': str(e)}
            raise
        finally:
            if own:
                db.close()

    def get_debt_invoice(self, invoice_id: int) -> dict:
        db = _db()
        try:
            inv = _row(db.execute(
                "SELECT di.*, c.phone as c_phone, c.email as c_email, "
                "s.created_at as sale_date, s.status as sale_status "
                "FROM debt_invoices di "
                "JOIN customers c ON di.customer_id=c.id "
                "LEFT JOIN sales s ON di.sale_id=s.id "
                "WHERE di.id=?", (invoice_id,)
            ))
            return inv or {}
        finally:
            db.close()

    def get_debt_invoices(self, status=None, customer_id=None,
                          start=None, end=None) -> list:
        db = _db()
        try:
            clauses = []
            params = []
            if status:
                if isinstance(status, list):
                    ph = ','.join('?' * len(status))
                    clauses.append(f"di.status IN ({ph})")
                    params.extend(status)
                else:
                    clauses.append("di.status=?")
                    params.append(status)
            if customer_id:
                clauses.append("di.customer_id=?")
                params.append(customer_id)
            if start:
                clauses.append("date(di.created_at)>=?")
                params.append(start)
            if end:
                clauses.append("date(di.created_at)<=?")
                params.append(end)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            return _rows(db.execute(
                f"SELECT di.*, c.phone as c_phone, c.email as c_email, "
                f"s.created_at as sale_date, s.status as sale_status "
                f"FROM debt_invoices di "
                f"JOIN customers c ON di.customer_id=c.id "
                f"LEFT JOIN sales s ON di.sale_id=s.id "
                f"{where} ORDER BY di.created_at DESC", params
            ))
        finally:
            db.close()

    def get_overdue_invoices(self) -> list:
        db = _db()
        try:
            return _rows(db.execute(
                "SELECT di.*, c.phone, c.email, s.created_at as sale_date "
                "FROM debt_invoices di "
                "JOIN customers c ON di.customer_id=c.id "
                "LEFT JOIN sales s ON di.sale_id=s.id "
                "WHERE di.status NOT IN ('paid','cancelled') "
                "AND di.due_date IS NOT NULL AND di.due_date < date('now') "
                "ORDER BY di.due_date ASC"
            ))
        finally:
            db.close()

    def record_debt_payment(self, invoice_id: int, amount: float,
                            payment_method: str = 'cash', notes: str = '',
                            payment_reference: str = '') -> dict:
        """Collect a payment against an existing invoice. Rejects invalid / orphan debts."""
        db = _db()
        try:
            if not invoice_id:
                return {'error': 'Invoice is required — cannot record payment without an invoice.'}

            inv = _row(db.execute("SELECT * FROM debt_invoices WHERE id=?", (invoice_id,)))
            if not inv:
                return {'error': 'Invoice not found'}
            if inv['status'] == 'cancelled':
                return {'error': 'Invoice is cancelled — cannot collect payment.'}
            if inv['status'] == 'paid' or float(inv.get('balance') or 0) <= 0.009:
                return {'error': 'Invoice is already fully paid.'}

            if not inv.get('sale_id'):
                return {
                    'error': 'This debt has no linked sale (orphan). '
                             'Cannot mark paid — create credit sales from POS only.'
                }
            if not (inv.get('receipt_number') or '').strip():
                return {
                    'error': 'This debt has no invoice/receipt number. Cannot mark paid.'
                }

            sale = _row(db.execute(
                "SELECT id, status, receipt_number FROM sales WHERE id=?",
                (inv['sale_id'],)
            ))
            if not sale:
                return {'error': 'Linked sale is missing — cannot mark this debt paid.'}
            if (sale.get('status') or 'completed') == 'voided':
                return {'error': 'Linked sale was voided — cannot collect payment on this debt.'}

            amount = round(float(amount or 0), 2)
            if amount <= 0:
                return {'error': 'Payment amount must be greater than zero.'}

            ref = (payment_reference or '').strip()
            dp_cols = {r[1] for r in db.execute("PRAGMA table_info(debt_payments)").fetchall()}
            if ref and 'payment_reference' in dp_cols:
                prev = db.execute(
                    "SELECT payment_receipt, balance_before, balance_after "
                    "FROM debt_payments WHERE invoice_id=? AND payment_reference=?",
                    (invoice_id, ref),
                ).fetchone()
                if prev:
                    return {
                        'success': True,
                        'duplicate': True,
                        'payment_receipt': prev['payment_receipt'],
                        'balance_before': prev['balance_before'],
                        'balance_after': prev['balance_after'],
                        'status': inv['status'],
                        'invoice_number': inv['invoice_number'],
                        'customer_id': inv['customer_id'],
                    }

            db.execute("BEGIN IMMEDIATE")
            inv = _row(db.execute("SELECT * FROM debt_invoices WHERE id=?", (invoice_id,)))
            if not inv or inv['status'] in ('paid', 'cancelled') or float(inv.get('balance') or 0) <= 0.009:
                db.rollback()
                return {'error': 'Invoice is already fully paid.'}
            if ref and 'payment_reference' in dp_cols:
                prev = db.execute(
                    "SELECT payment_receipt, balance_before, balance_after "
                    "FROM debt_payments WHERE invoice_id=? AND payment_reference=?",
                    (invoice_id, ref),
                ).fetchone()
                if prev:
                    db.rollback()
                    return {
                        'success': True,
                        'duplicate': True,
                        'payment_receipt': prev['payment_receipt'],
                        'balance_before': prev['balance_before'],
                        'balance_after': prev['balance_after'],
                        'status': inv['status'],
                        'invoice_number': inv['invoice_number'],
                        'customer_id': inv['customer_id'],
                    }
            balance_before = round(float(inv['balance']), 2)
            if amount > balance_before + 0.009:
                db.rollback()
                return {
                    'error': f"Payment ({amount:,.2f}) exceeds outstanding balance "
                             f"({balance_before:,.2f})"
                }

            balance_after = round(balance_before - amount, 2)
            new_paid = round(float(inv['amount_paid']) + amount, 2)
            new_status = 'paid' if balance_after <= 0.009 else 'partial'
            if balance_after < 0.009:
                balance_after = 0.0

            pay_receipt = self._next_payment_receipt(db)

            if 'payment_reference' in dp_cols:
                db.execute(
                    "INSERT INTO debt_payments (payment_receipt,invoice_id,customer_id,"
                    "amount,payment_method,payment_reference,balance_before,balance_after,"
                    "cashier_id,cashier_name,notes) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (pay_receipt, invoice_id, inv['customer_id'],
                     amount, payment_method, ref, balance_before, balance_after,
                     self._user_id, self._username or 'staff', notes)
                )
            else:
                db.execute(
                    "INSERT INTO debt_payments (payment_receipt,invoice_id,customer_id,"
                    "amount,payment_method,balance_before,balance_after,cashier_id,cashier_name,notes) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (pay_receipt, invoice_id, inv['customer_id'],
                     amount, payment_method, balance_before, balance_after,
                     self._user_id, self._username or 'staff', notes)
                )
            claimed = db.execute(
                "UPDATE debt_invoices SET amount_paid=?, balance=?, status=?, updated_at=? "
                "WHERE id=? AND status NOT IN ('paid','cancelled') AND balance + 0.009 >= ?",
                (new_paid, balance_after, new_status, datetime.now().isoformat(), invoice_id, amount)
            )
            if claimed.rowcount != 1:
                db.rollback()
                return {'error': 'That balance changed. Refresh and try the payment again.'}
            if getattr(APIClient, '_test_fault', None) == 'payment-commit':
                raise RuntimeError('injected payment failure')
            try:
                from desktop.utils.accounting_hooks import post_debt_payment_journal
                pay_row = db.execute(
                    "SELECT id FROM debt_payments WHERE payment_receipt=?",
                    (pay_receipt,)
                ).fetchone()
                post_debt_payment_journal(
                    db,
                    payment_id=pay_row[0] if pay_row else None,
                    invoice_id=invoice_id,
                    amount=amount,
                    payment_method=payment_method,
                    payment_receipt=pay_receipt,
                    user_id=self._user_id,
                    username=self._username or 'staff',
                    safe=True)
            except Exception as _je:
                logger.error('debt payment accounting: %s', _je, exc_info=True)
            db.commit()
            _audit(self._user_id, self._username, 'DEBT_PAYMENT', 'debt',
                   f"inv={inv['invoice_number']} sale={inv.get('sale_id')} "
                   f"amount={amount} method={payment_method} ref={ref} "
                   f"balance_after={balance_after}")
            return {
                'success': True,
                'payment_receipt': pay_receipt,
                'balance_before': balance_before,
                'balance_after': balance_after,
                'status': new_status,
                'invoice_number': inv['invoice_number'],
                'customer_id': inv['customer_id'],
            }
        except Exception as e:
            db.rollback()
            logger.error(f"record_debt_payment: {e}", exc_info=True)
            return {'error': str(e)}
        finally:
            db.close()

    def _ensure_collection_tables(self, db):
        db.execute(
            """CREATE TABLE IF NOT EXISTS debt_collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_receipt TEXT UNIQUE NOT NULL,
                customer_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                allocated REAL NOT NULL,
                unapplied REAL NOT NULL DEFAULT 0,
                payment_method TEXT,
                methods_json TEXT,
                allocation_mode TEXT,
                client_token TEXT,
                reversed INTEGER DEFAULT 0,
                reversed_at TEXT,
                reversal_reason TEXT,
                cashier_id INTEGER,
                cashier_name TEXT,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_debt_collection_token "
            "ON debt_collections(client_token) WHERE client_token IS NOT NULL AND client_token != ''"
        )
        cols = {r[1] for r in db.execute("PRAGMA table_info(debt_payments)").fetchall()}
        if 'collection_id' not in cols:
            db.execute("ALTER TABLE debt_payments ADD COLUMN collection_id INTEGER")

    def _eligible_customer_debts(self, db, customer_id: int) -> list:
        rows = _rows(db.execute(
            "SELECT * FROM debt_invoices "
            "WHERE customer_id=? AND status NOT IN ('paid','cancelled') AND balance > 0.009 "
            "ORDER BY created_at ASC, id ASC",
            (int(customer_id),),
        ))
        eligible = []
        for inv in rows:
            if not inv.get('sale_id') or not (inv.get('receipt_number') or '').strip():
                continue
            sale = _row(db.execute(
                "SELECT id, status FROM sales WHERE id=?", (inv['sale_id'],),
            ))
            if not sale or (sale.get('status') or 'completed') == 'voided':
                continue
            eligible.append(inv)
        return eligible

    def _plan_debt_allocation(self, debts: list, amount: float, mode: str, requested: list):
        """Oldest debt first, or the cashier's chosen receipts. Extra money is unapplied credit."""
        amount = round(float(amount or 0), 2)
        mode = (mode or 'auto').strip().lower()
        if mode not in ('auto', 'manual'):
            return None, None, 'Choose automatic or manual allocation.'
        if amount <= 0:
            return None, None, 'Payment amount must be greater than zero.'
        by_id = {int(inv['id']): inv for inv in debts}
        planned = []
        if mode == 'auto':
            left = amount
            for inv in debts:
                if left <= 0.009:
                    break
                room = round(float(inv['balance'] or 0), 2)
                take = round(min(left, room), 2)
                if take <= 0:
                    continue
                planned.append({'invoice_id': int(inv['id']), 'amount': take, 'invoice': inv})
                left = round(left - take, 2)
            return planned, left, None
        seen = set()
        for item in requested or []:
            try:
                invoice_id = int(item.get('invoice_id') or 0)
                take = round(float(item.get('amount') or 0), 2)
            except (TypeError, ValueError):
                return None, None, 'Each allocation needs a receipt and an amount.'
            if take <= 0:
                continue
            if invoice_id in seen:
                return None, None, 'A receipt can only appear once in this payment.'
            seen.add(invoice_id)
            inv = by_id.get(invoice_id)
            if not inv:
                return None, None, 'One of the selected receipts is not an open debt for this customer.'
            room = round(float(inv['balance'] or 0), 2)
            if take > room + 0.009:
                return None, None, (
                    f"Allocation of {take:,.2f} is more than {inv.get('invoice_number') or 'that receipt'} "
                    f"still owes ({room:,.2f})."
                )
            planned.append({'invoice_id': invoice_id, 'amount': take, 'invoice': inv})
        allocated = round(sum(item['amount'] for item in planned), 2)
        if allocated > amount + 0.009:
            return None, None, 'The allocations add up to more than the money received.'
        unapplied = round(amount - allocated, 2)
        if unapplied > 0.009:
            remaining_room = 0.0
            for inv in debts:
                used = next((item['amount'] for item in planned if item['invoice_id'] == int(inv['id'])), 0.0)
                remaining_room += max(0.0, round(float(inv['balance'] or 0) - used, 2))
            if remaining_room > 0.009:
                return None, None, (
                    f"{unapplied:,.2f} is not allocated, and {remaining_room:,.2f} of debt is still open. "
                    "Allocate the full payment, or reduce the amount."
                )
        return planned, unapplied, None

    def preview_customer_payment(self, customer_id: int, amount: float, mode: str = 'auto',
                                 allocations: list = None, methods: list = None) -> dict:
        db = _db()
        try:
            cust = _row(db.execute("SELECT id, name, phone FROM customers WHERE id=?", (int(customer_id),)))
            if not cust:
                return {'error': 'Customer not found'}
            debts = self._eligible_customer_debts(db, int(customer_id))
            planned, unapplied, err = self._plan_debt_allocation(debts, amount, mode, allocations or [])
            if err:
                return {'error': err}
            wallet = db.execute(
                "SELECT balance FROM customer_wallet WHERE customer_id=?", (int(customer_id),),
            ).fetchone()
            lines = []
            for inv in debts:
                take = next((item['amount'] for item in planned if item['invoice_id'] == int(inv['id'])), 0.0)
                before = round(float(inv['balance'] or 0), 2)
                lines.append({
                    'invoice_id': inv['id'],
                    'invoice_number': inv.get('invoice_number'),
                    'receipt_number': inv.get('receipt_number'),
                    'created_at': inv.get('created_at'),
                    'original': round(float(inv.get('total_amount') or 0), 2),
                    'paid': round(float(inv.get('amount_paid') or 0), 2),
                    'outstanding': before,
                    'allocate': round(float(take), 2),
                    'remaining': round(before - float(take), 2),
                    'status': 'paid' if before - float(take) <= 0.009 else ('partial' if take > 0 or float(inv.get('amount_paid') or 0) > 0 else 'pending'),
                })
            method_rows = self._normalise_tenders(amount, methods)
            if isinstance(method_rows, dict):
                return method_rows
            return {
                'customer': cust,
                'amount': round(float(amount or 0), 2),
                'allocated': round(sum(item['amount'] for item in planned), 2),
                'unapplied': round(float(unapplied or 0), 2),
                'outstanding_before': round(sum(float(inv['balance'] or 0) for inv in debts), 2),
                'outstanding_after': round(
                    sum(float(inv['balance'] or 0) for inv in debts) - sum(item['amount'] for item in planned), 2
                ),
                'unapplied_credit_before': round(float(wallet[0] or 0), 2) if wallet else 0.0,
                'lines': lines,
                'methods': method_rows,
                'mode': (mode or 'auto').strip().lower(),
            }
        finally:
            db.close()

    def _normalise_tenders(self, amount: float, methods: list):
        amount = round(float(amount or 0), 2)
        rows = []
        for item in methods or []:
            if isinstance(item, str):
                rows.append({'method': item.strip().lower() or 'cash', 'amount': amount})
                continue
            try:
                part = round(float(item.get('amount') or 0), 2)
            except (TypeError, ValueError):
                return {'error': 'Each payment method needs an amount.'}
            name = str(item.get('method') or 'cash').strip().lower() or 'cash'
            if part <= 0:
                continue
            rows.append({'method': name, 'amount': part})
        if not rows:
            rows = [{'method': 'cash', 'amount': amount}]
        total = round(sum(item['amount'] for item in rows), 2)
        if abs(total - amount) > 0.009:
            return {'error': f"Payment methods add up to {total:,.2f}, not the {amount:,.2f} received."}
        return rows

    def collect_customer_payment(self, customer_id: int, amount: float, *,
                                 mode: str = 'auto', allocations: list = None,
                                 methods: list = None, notes: str = '',
                                 client_token: str = '',
                                 from_credit: bool = False) -> dict:
        """One collection. Oldest-debt-first or the chosen receipts. Extra becomes store credit."""
        db = _db()
        try:
            self._ensure_collection_tables(db)
            cust = _row(db.execute("SELECT id, name FROM customers WHERE id=?", (int(customer_id),)))
            if not cust:
                return {'error': 'Customer not found'}
            amount = round(float(amount or 0), 2)
            tenders = self._normalise_tenders(amount, methods)
            if isinstance(tenders, dict):
                return tenders
            token = (client_token or '').strip()
            db.execute("BEGIN IMMEDIATE")
            if token:
                prior = _row(db.execute(
                    "SELECT * FROM debt_collections WHERE client_token=?", (token,),
                ))
                if prior:
                    saved = self._collection_payload(db, prior)
                    db.commit()
                    saved['duplicate'] = True
                    saved['success'] = True
                    return saved
            if from_credit:
                wallet = db.execute(
                    "SELECT balance FROM customer_wallet WHERE customer_id=?", (int(customer_id),),
                ).fetchone()
                available = round(float(wallet[0] or 0), 2) if wallet else 0.0
                if amount > available + 0.009:
                    db.rollback()
                    return {'error': f"Only {available:,.2f} of customer credit is available."}
            debts = self._eligible_customer_debts(db, int(customer_id))
            planned, unapplied, err = self._plan_debt_allocation(debts, amount, mode, allocations or [])
            if err:
                db.rollback()
                return {'error': err}
            if from_credit and unapplied > 0.009:
                db.rollback()
                return {'error': 'Customer credit can only be applied to open debts.'}
            method_label = tenders[0]['method'] if len(tenders) == 1 else 'split'
            if from_credit:
                method_label = 'customer_credit'
                tenders = [{'method': 'customer_credit', 'amount': amount}]
            now = datetime.now().isoformat()
            today = datetime.now().strftime('%Y%m%d')
            prefix = f"COL-{today}-"
            collection_id = None
            collection_receipt = ''
            for _attempt in range(5):
                last = db.execute(
                    "SELECT collection_receipt FROM debt_collections "
                    "WHERE collection_receipt LIKE ? ORDER BY collection_receipt DESC LIMIT 1",
                    (prefix + '%',),
                ).fetchone()
                seq = 1
                if last and last[0]:
                    try:
                        seq = int(str(last[0]).rsplit('-', 1)[-1]) + 1
                    except ValueError:
                        seq = 1
                collection_receipt = f"{prefix}{seq:04d}"
                try:
                    cur = db.execute(
                        "INSERT INTO debt_collections (collection_receipt, customer_id, amount, allocated, "
                        "unapplied, payment_method, methods_json, allocation_mode, client_token, "
                        "cashier_id, cashier_name, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (collection_receipt, int(customer_id), amount,
                         round(sum(item['amount'] for item in planned), 2), round(float(unapplied or 0), 2),
                         method_label, json.dumps(tenders), (mode or 'auto').strip().lower(), token or None,
                         self._user_id, self._username or 'staff', notes or '', now),
                    )
                    collection_id = cur.lastrowid
                    break
                except sqlite3.IntegrityError:
                    collection_id = None
            if not collection_id:
                db.rollback()
                return {'error': 'Could not assign a payment receipt. Try again.'}
            applied = []
            for item in planned:
                result = self._apply_collection_allocation(
                    db, item['invoice'], item['amount'], method_label, notes,
                    collection_receipt, collection_id,
                )
                if result.get('error'):
                    db.rollback()
                    return result
                applied.append(result)
            if unapplied > 0.009 and not from_credit:
                self._wallet_adjust(
                    db, int(customer_id), unapplied, 'unapplied_credit',
                    receipt_number=collection_receipt,
                    notes=f"Overpayment on {collection_receipt}",
                )
            if from_credit:
                self._wallet_adjust(
                    db, int(customer_id), -amount, 'apply_credit',
                    receipt_number=collection_receipt,
                    notes=f"Applied to debts on {collection_receipt}",
                )
            db.commit()
            _audit(self._user_id, self._username, 'DEBT_COLLECTION', 'debt',
                   f"customer={customer_id} receipt={collection_receipt} amount={amount} "
                   f"allocated={sum(item['amount'] for item in planned)} unapplied={unapplied} mode={mode}")
            payload = self._collection_payload(db, _row(db.execute(
                "SELECT * FROM debt_collections WHERE id=?", (collection_id,),
            )))
            payload['success'] = True
            payload['allocations'] = applied
            return payload
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error("collect_customer_payment: %s", e, exc_info=True)
            return {'error': str(e)}
        finally:
            db.close()

    def _apply_collection_allocation(self, db, inv, amount, payment_method, notes,
                                     collection_receipt, collection_id) -> dict:
        invoice_id = int(inv['id'])
        fresh = _row(db.execute("SELECT * FROM debt_invoices WHERE id=?", (invoice_id,)))
        if not fresh or fresh['status'] in ('paid', 'cancelled'):
            return {'error': 'A receipt was paid or cancelled while this payment was being saved.'}
        balance_before = round(float(fresh['balance'] or 0), 2)
        amount = round(float(amount), 2)
        if amount > balance_before + 0.009:
            return {'error': 'That balance changed. Refresh and try the payment again.'}
        balance_after = round(max(0.0, balance_before - amount), 2)
        new_paid = round(float(fresh['amount_paid'] or 0) + amount, 2)
        new_status = 'paid' if balance_after <= 0.009 else 'partial'
        pay_receipt = self._next_payment_receipt(db)
        cols = {r[1] for r in db.execute("PRAGMA table_info(debt_payments)").fetchall()}
        fields = [
            "payment_receipt", "invoice_id", "customer_id", "amount", "payment_method",
            "balance_before", "balance_after", "cashier_id", "cashier_name", "notes",
        ]
        values = [
            pay_receipt, invoice_id, fresh['customer_id'], amount, payment_method,
            balance_before, balance_after, self._user_id, self._username or 'staff',
            notes or '',
        ]
        if 'payment_reference' in cols:
            fields.append("payment_reference")
            values.append(collection_receipt)
        if 'collection_id' in cols:
            fields.append("collection_id")
            values.append(int(collection_id))
        db.execute(
            f"INSERT INTO debt_payments ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
            values,
        )
        claimed = db.execute(
            "UPDATE debt_invoices SET amount_paid=?, balance=?, status=?, updated_at=? "
            "WHERE id=? AND status NOT IN ('paid','cancelled') AND balance + 0.009 >= ?",
            (new_paid, balance_after, new_status, datetime.now().isoformat(), invoice_id, amount),
        )
        if claimed.rowcount != 1:
            return {'error': 'That balance changed. Refresh and try the payment again.'}
        return {
            'payment_receipt': pay_receipt,
            'invoice_id': invoice_id,
            'invoice_number': fresh.get('invoice_number'),
            'receipt_number': fresh.get('receipt_number'),
            'amount': amount,
            'balance_before': balance_before,
            'balance_after': balance_after,
            'status': new_status,
        }

    def _collection_payload(self, db, row) -> dict:
        if not row:
            return {}
        allocations = _rows(db.execute(
            "SELECT dp.*, di.invoice_number, di.receipt_number, di.balance, di.status "
            "FROM debt_payments dp JOIN debt_invoices di ON di.id=dp.invoice_id "
            "WHERE dp.collection_id=? ORDER BY dp.id",
            (row['id'],),
        ))
        try:
            methods = json.loads(row.get('methods_json') or '[]')
        except Exception:
            methods = []
        return {
            'collection_id': row['id'],
            'collection_receipt': row.get('collection_receipt'),
            'customer_id': row.get('customer_id'),
            'amount': row.get('amount'),
            'allocated': row.get('allocated'),
            'unapplied': row.get('unapplied'),
            'payment_method': row.get('payment_method'),
            'methods': methods,
            'allocation_mode': row.get('allocation_mode'),
            'reversed': int(row.get('reversed') or 0),
            'created_at': row.get('created_at'),
            'allocations': allocations,
        }

    def reverse_debt_collection(self, collection_id: int, reason: str, *,
                                client_token: str = '') -> dict:
        """Reverse one collection and every allocation it made. The sales stay."""
        if (self._role or '').lower() not in ('admin', 'superadmin'):
            return {'error': 'Only an admin can reverse a debt payment.', 'status': 403}
        reason = (reason or '').strip()
        if len(reason) < 3:
            return {'error': 'Enter why this payment is being reversed.', 'status': 400}
        db = _db()
        try:
            self._ensure_collection_tables(db)
            self._ensure_resolution_tables(db)
            db.execute('BEGIN IMMEDIATE')
            col = _row(db.execute(
                "SELECT * FROM debt_collections WHERE id=?", (int(collection_id),),
            ))
            if not col:
                db.rollback()
                return {'error': 'Payment was not found.', 'status': 404}
            if int(col.get('reversed') or 0) == 1:
                db.rollback()
                return {'error': 'This payment is already reversed.', 'status': 409, 'already': True}
            payments = _rows(db.execute(
                "SELECT * FROM debt_payments WHERE collection_id=? AND COALESCE(reversed,0)=0 ORDER BY id DESC",
                (int(collection_id),),
            ))
            restored = []
            for pay in payments:
                outcome = self._restore_payment_balance(db, pay, reason, client_token='')
                if outcome.get('error'):
                    db.rollback()
                    return outcome
                restored.append(outcome)
            unapplied = round(float(col.get('unapplied') or 0), 2)
            if unapplied > 0.009:
                self._wallet_adjust(
                    db, int(col['customer_id']), -unapplied, 'unapplied_reversal',
                    receipt_number=col.get('collection_receipt'),
                    notes=reason,
                )
            claimed = db.execute(
                "UPDATE debt_collections SET reversed=1, reversed_at=?, reversal_reason=? "
                "WHERE id=? AND COALESCE(reversed,0)=0",
                (datetime.now().isoformat(), reason, int(collection_id)),
            )
            if claimed.rowcount != 1:
                db.rollback()
                return {'error': 'This payment is already reversed.', 'status': 409, 'already': True}
            db.commit()
            _audit(self._user_id, self._username, 'DEBT_COLLECTION_REVERSAL', 'debt',
                   f"collection={col.get('collection_receipt')} reason={reason}")
            return {
                'success': True,
                'collection_receipt': col.get('collection_receipt'),
                'restored': restored,
                'unapplied_reversed': unapplied,
            }
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error("reverse_debt_collection: %s", e, exc_info=True)
            return {'error': str(e)}
        finally:
            db.close()

    def _restore_payment_balance(self, db, pay, reason: str, client_token: str = '') -> dict:
        if int(pay.get('reversed') or 0) == 1:
            return {'error': 'This payment is already reversed.', 'status': 409, 'already': True}
        inv = _row(db.execute("SELECT * FROM debt_invoices WHERE id=?", (pay['invoice_id'],)))
        if not inv or inv['status'] == 'cancelled':
            return {'error': 'That debt is cancelled. Reverse the sale separately.', 'status': 409}
        amount = round(float(pay['amount'] or 0), 2)
        balance = round(float(inv['balance'] or 0), 2)
        paid = round(float(inv['amount_paid'] or 0), 2)
        new_balance = round(balance + amount, 2)
        new_paid = round(max(0.0, paid - amount), 2)
        due = str(inv.get('due_date') or '')[:10]
        today = datetime.now().strftime('%Y-%m-%d')
        if new_paid > 0.009:
            new_status = 'overdue' if due and due < today else 'partial'
        else:
            new_status = 'overdue' if due and due < today else 'pending'
        claimed = db.execute(
            "UPDATE debt_payments SET reversed=1, reversed_at=?, reversal_reason=? "
            "WHERE id=? AND COALESCE(reversed,0)=0",
            (datetime.now().isoformat(), reason, int(pay['id'])),
        )
        if claimed.rowcount != 1:
            return {'error': 'This payment is already reversed.', 'status': 409, 'already': True}
        updated = db.execute(
            "UPDATE debt_invoices SET amount_paid=?, balance=?, status=?, updated_at=? "
            "WHERE id=? AND balance=?",
            (new_paid, new_balance, new_status, datetime.now().isoformat(), int(inv['id']), balance),
        )
        if updated.rowcount != 1:
            return {'error': 'The balance changed. Reload and try again.', 'status': 409}
        db.execute(
            "INSERT INTO debt_payment_reversals "
            "(payment_id, invoice_id, amount, reason, money_outcome, client_token, user_id, username) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (int(pay['id']), int(inv['id']), amount, reason, 'never_received',
             client_token or None, self._user_id, self._username or 'staff'),
        )
        return {
            'invoice_id': inv['id'],
            'invoice_number': inv.get('invoice_number'),
            'amount': amount,
            'balance': new_balance,
            'status': new_status,
        }

    def get_customer_statement(self, customer_id: int) -> dict:
        db = _db()
        try:
            self._ensure_collection_tables(db)
            customer = self.get_customer(int(customer_id))
            if not customer:
                return {'error': 'Customer not found'}
            collections = _rows(db.execute(
                "SELECT * FROM debt_collections WHERE customer_id=? ORDER BY id",
                (int(customer_id),),
            ))
            detailed = [self._collection_payload(db, row) for row in collections]
            wallet_txns = _rows(db.execute(
                "SELECT * FROM wallet_transactions WHERE customer_id=? ORDER BY id",
                (int(customer_id),),
            ))
            return {
                'customer': {
                    'id': customer.get('id'),
                    'name': customer.get('name'),
                    'phone': customer.get('phone'),
                },
                'outstanding': customer.get('total_outstanding'),
                'total_paid': customer.get('total_paid'),
                'unapplied_credit': customer.get('unapplied_credit'),
                'invoices': customer.get('invoices') or [],
                'collections': detailed,
                'wallet_transactions': wallet_txns,
            }
        finally:
            db.close()

    def get_debt_payments(self, invoice_id=None, customer_id=None,
                          start=None, end=None) -> list:
        db = _db()
        try:
            clauses, params = [], []
            if invoice_id:
                clauses.append("dp.invoice_id=?")
                params.append(invoice_id)
            if customer_id:
                clauses.append("dp.customer_id=?")
                params.append(customer_id)
            if start:
                clauses.append("date(dp.created_at)>=?")
                params.append(start)
            if end:
                clauses.append("date(dp.created_at)<=?")
                params.append(end)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            return _rows(db.execute(
                f"SELECT dp.*, di.invoice_number, di.receipt_number, "
                f"c.name as customer_name, c.phone "
                f"FROM debt_payments dp "
                f"JOIN debt_invoices di ON dp.invoice_id=di.id "
                f"JOIN customers c ON dp.customer_id=c.id "
                f"{where} ORDER BY dp.created_at DESC", params
            ))
        finally:
            db.close()

    def get_debt_summary(self, start=None, end=None) -> dict:
        """Dashboard widget data for debt management."""
        db = _db()
        try:
            today = str(date.today())
            range_start = str(start or today)[:10]
            range_end = str(end or today)[:10]
            outstanding = _row(db.execute(
                "SELECT COALESCE(SUM(balance),0) as total, COUNT(*) as count "
                "FROM debt_invoices WHERE status NOT IN ('paid','cancelled','written_off')"
            ))
            overdue = _row(db.execute(
                "SELECT COALESCE(SUM(balance),0) as total, COUNT(*) as count "
                "FROM debt_invoices WHERE status NOT IN ('paid','cancelled','written_off') "
                "AND due_date IS NOT NULL AND due_date < date('now')"
            ))
            today_collected = _row(db.execute(
                "SELECT COALESCE(SUM(amount),0) as total, COUNT(*) as count "
                "FROM debt_payments WHERE date(created_at) BETWEEN ? AND ? "
                "AND COALESCE(reversed,0)=0",
                (range_start, range_end),
            ))
            credit_today = _row(db.execute(
                "SELECT COALESCE(SUM(balance),0) as total, COUNT(*) as count "
                "FROM debt_invoices WHERE date(created_at) BETWEEN ? AND ?",
                (range_start, range_end),
            ))
            customers_with_debt = db.execute(
                "SELECT COUNT(DISTINCT customer_id) FROM debt_invoices "
                "WHERE status NOT IN ('paid','cancelled','written_off')"
            ).fetchone()[0]
            top_debtors = _rows(db.execute(
                "SELECT customer_name, COALESCE(SUM(balance),0) as total_balance "
                "FROM debt_invoices WHERE status NOT IN ('paid','cancelled','written_off') "
                "GROUP BY customer_id ORDER BY total_balance DESC LIMIT 5"
            ))
            return {
                'outstanding': dict(outstanding) if outstanding else {},
                'overdue': dict(overdue) if overdue else {},
                'today_collected': dict(today_collected) if today_collected else {},
                'credit_today': dict(credit_today) if credit_today else {},
                'customers_with_debt': customers_with_debt,
                'top_debtors': top_debtors,
            }
        finally:
            db.close()

    def _ensure_resolution_tables(self, db):
        db.execute(
            """CREATE TABLE IF NOT EXISTS debt_payment_reversals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id INTEGER NOT NULL UNIQUE,
                invoice_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                reason TEXT NOT NULL,
                money_outcome TEXT NOT NULL,
                client_token TEXT UNIQUE,
                user_id INTEGER,
                username TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS debt_refunds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id INTEGER,
                invoice_id INTEGER,
                sale_id INTEGER,
                amount REAL NOT NULL,
                method TEXT,
                reference TEXT,
                reason TEXT NOT NULL,
                client_token TEXT UNIQUE,
                user_id INTEGER,
                username TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS debt_allocation_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id INTEGER NOT NULL,
                from_invoice_id INTEGER NOT NULL,
                to_invoice_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                reason TEXT NOT NULL,
                client_token TEXT UNIQUE,
                user_id INTEGER,
                username TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        cols = {r[1] for r in db.execute("PRAGMA table_info(debt_payments)").fetchall()}
        if 'reversed' not in cols:
            db.execute("ALTER TABLE debt_payments ADD COLUMN reversed INTEGER DEFAULT 0")
        refund_cols = {r[1] for r in db.execute("PRAGMA table_info(debt_refunds)").fetchall()}
        if 'status' not in refund_cols:
            db.execute("ALTER TABLE debt_refunds ADD COLUMN status TEXT DEFAULT 'completed'")
        db.execute(
            """CREATE TABLE IF NOT EXISTS debt_sale_cancellations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER NOT NULL UNIQUE,
                invoice_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                refund_status TEXT NOT NULL,
                client_token TEXT UNIQUE,
                user_id INTEGER,
                username TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )

    def _sale_stock_lines(self, db, sale_id) -> list:
        """Sold quantity, earlier returns, and what can still go back to stock."""
        if not sale_id:
            return []
        items = _rows(db.execute(
            "SELECT product_id, product_name, quantity, COALESCE(returned_qty,0) AS returned_qty "
            "FROM sale_items WHERE sale_id=?",
            (int(sale_id),),
        ))
        restored = {
            int(row['product_id']): float(row['qty'] or 0)
            for row in db.execute(
                "SELECT product_id, SUM(qty_change) AS qty FROM stock_movements "
                "WHERE movement_type='VOID_RESTORE' AND (reference=? OR reference LIKE ?) "
                "GROUP BY product_id",
                (f"VOID_sale={int(sale_id)}", f"VOID_sale={int(sale_id)}:%"),
            ).fetchall()
            if row['product_id']
        }
        lines = []
        for item in items:
            pid = item.get('product_id')
            sold = float(item.get('quantity') or 0)
            returned = float(item.get('returned_qty') or 0)
            already = restored.get(int(pid), 0.0) if pid else 0.0
            lines.append({
                'product_id': int(pid) if pid else None,
                'product_name': item.get('product_name') or '',
                'sold': sold,
                'returned': returned,
                'already_restored': already,
                'eligible': round(max(0.0, sold - returned - already), 3),
            })
        return lines

    def debt_resolution_preview(self, invoice_id: int) -> dict:
        """One invoice: sale, repayments, write-offs, and what a reversal would change."""
        db = _db()
        try:
            self._ensure_resolution_tables(db)
            inv = _row(db.execute(
                "SELECT di.*, c.name AS customer_name, c.phone AS customer_phone "
                "FROM debt_invoices di JOIN customers c ON c.id=di.customer_id WHERE di.id=?",
                (int(invoice_id),),
            ))
            if not inv:
                return {'error': 'Invoice was not found.', 'status': 404}
            payments = _rows(db.execute(
                "SELECT id, payment_receipt, amount, payment_method, payment_reference, "
                "balance_before, balance_after, notes, created_at, "
                "COALESCE(reversed,0) AS reversed, reversal_reason "
                "FROM debt_payments WHERE invoice_id=? ORDER BY id",
                (int(invoice_id),),
            ))
            write_offs = _rows(db.execute(
                "SELECT id, amount, reason, username, created_at FROM debt_write_offs "
                "WHERE invoice_id=? ORDER BY id",
                (int(invoice_id),),
            )) if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='debt_write_offs'"
            ).fetchone() else []
            sale = None
            if inv.get('sale_id'):
                sale = _row(db.execute(
                    "SELECT id, receipt_number, total, amount_paid, status, payment_method "
                    "FROM sales WHERE id=?",
                    (inv['sale_id'],),
                ))
            valid_paid = round(sum(
                float(row['amount'] or 0) for row in payments if int(row.get('reversed') or 0) != 1
            ), 2)
            lines = self._sale_stock_lines(db, inv.get('sale_id'))
            refunds = _rows(db.execute(
                "SELECT id, amount, method, reference, reason, COALESCE(status,'completed') AS status, created_at "
                "FROM debt_refunds WHERE invoice_id=? OR sale_id=? ORDER BY id",
                (int(invoice_id), inv.get('sale_id')),
            )) if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='debt_refunds'"
            ).fetchone() else []
            return {
                'invoice': inv,
                'sale': sale,
                'payments': payments,
                'write_offs': write_offs,
                'refunds': refunds,
                'lines': lines,
                'valid_repayments': valid_paid,
                'money_received': valid_paid,
                'outstanding': round(float(inv.get('balance') or 0), 2),
                'sale_remains_valid_on_reversal': True,
                'stock_changes_on_reversal': False,
            }
        finally:
            db.close()

    def reverse_debt_payment(self, payment_id: int, reason: str,
                             *, money_outcome: str = 'never_received',
                             client_token: str = '') -> dict:
        """Undo one repayment. The sale stays. Stock stays. The payment row stays."""
        if (self._role or '').lower() not in ('admin', 'superadmin'):
            return {'error': 'Only an admin can reverse a debt payment.', 'status': 403}
        reason = (reason or '').strip()
        if len(reason) < 3:
            return {'error': 'Enter why this payment is being reversed.', 'status': 400}
        outcome = (money_outcome or 'never_received').strip()
        if outcome not in ('never_received', 'refunded'):
            return {'error': 'Say whether the money was never received or was refunded.', 'status': 400}
        token = (client_token or '').strip()
        db = _db()
        try:
            self._ensure_resolution_tables(db)
            db.execute('BEGIN IMMEDIATE')
            if token:
                prior = _row(db.execute(
                    "SELECT id, amount, invoice_id FROM debt_payment_reversals WHERE client_token=?",
                    (token,),
                ))
                if prior:
                    inv = _row(db.execute(
                        "SELECT balance, status FROM debt_invoices WHERE id=?",
                        (prior['invoice_id'],),
                    ))
                    db.commit()
                    return {
                        'success': True, 'duplicate': True, 'id': prior['id'],
                        'balance': inv['balance'] if inv else None,
                        'status': inv['status'] if inv else None,
                    }
            pay = _row(db.execute("SELECT * FROM debt_payments WHERE id=?", (int(payment_id),)))
            if not pay:
                db.rollback()
                return {'error': 'Payment was not found.', 'status': 404}
            if int(pay.get('reversed') or 0) == 1:
                inv = _row(db.execute(
                    "SELECT balance FROM debt_invoices WHERE id=?", (pay['invoice_id'],),
                ))
                db.rollback()
                return {
                    'error': 'This payment is already reversed.',
                    'status': 409,
                    'balance': inv['balance'] if inv else None,
                    'already': True,
                }
            inv = _row(db.execute("SELECT * FROM debt_invoices WHERE id=?", (pay['invoice_id'],)))
            if not inv or inv['status'] == 'cancelled':
                db.rollback()
                return {'error': 'That debt is cancelled. Reverse the sale separately.', 'status': 409}
            sale = None
            if inv.get('sale_id'):
                sale = _row(db.execute("SELECT id, status FROM sales WHERE id=?", (inv['sale_id'],)))
            if sale and (sale.get('status') or '') == 'voided':
                db.rollback()
                return {'error': 'The sale is already cancelled.', 'status': 409}
            amount = round(float(pay['amount'] or 0), 2)
            balance = round(float(inv['balance'] or 0), 2)
            paid = round(float(inv['amount_paid'] or 0), 2)
            new_balance = round(balance + amount, 2)
            new_paid = round(max(0.0, paid - amount), 2)
            due = str(inv.get('due_date') or '')[:10]
            today = datetime.now().strftime('%Y-%m-%d')
            if new_paid > 0.009:
                new_status = 'overdue' if due and due < today else 'partial'
            else:
                new_status = 'overdue' if due and due < today else 'pending'
            claimed = db.execute(
                "UPDATE debt_payments SET reversed=1, reversed_at=?, reversal_reason=? "
                "WHERE id=? AND COALESCE(reversed,0)=0",
                (datetime.now().isoformat(), reason, int(payment_id)),
            )
            if claimed.rowcount != 1:
                db.rollback()
                return {'error': 'This payment is already reversed.', 'status': 409, 'already': True}
            updated = db.execute(
                "UPDATE debt_invoices SET amount_paid=?, balance=?, status=?, updated_at=? "
                "WHERE id=? AND balance=?",
                (new_paid, new_balance, new_status, datetime.now().isoformat(),
                 int(inv['id']), balance),
            )
            if updated.rowcount != 1:
                db.rollback()
                return {'error': 'The balance changed. Reload and try again.', 'status': 409}
            db.execute(
                "INSERT INTO debt_payment_reversals "
                "(payment_id, invoice_id, amount, reason, money_outcome, client_token, user_id, username) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (int(payment_id), int(inv['id']), amount, reason, outcome, token or None,
                 self._user_id, self._username or ''),
            )
            if outcome == 'refunded':
                db.execute(
                    "INSERT INTO debt_refunds "
                    "(payment_id, invoice_id, sale_id, amount, method, reference, reason, user_id, username) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (int(payment_id), int(inv['id']), inv.get('sale_id'), amount,
                     pay.get('payment_method') or '', pay.get('payment_reference') or '',
                     reason, self._user_id, self._username or ''),
                )
            db.commit()
            return {
                'success': True,
                'balance': new_balance,
                'previous_balance': balance,
                'amount': amount,
                'status': new_status,
                'sale_status': sale.get('status') if sale else None,
                'money_outcome': outcome,
                'stock_changed': False,
            }
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            return {'error': str(exc), 'status': 500}
        finally:
            db.close()

    def reallocate_debt_payment(self, payment_id: int, target_invoice_id: int, reason: str,
                                *, client_token: str = '') -> dict:
        """Move one repayment onto another debt of the same customer. No refund."""
        if (self._role or '').lower() not in ('admin', 'superadmin'):
            return {'error': 'Only an admin can correct a payment allocation.', 'status': 403}
        reason = (reason or '').strip()
        if len(reason) < 3:
            return {'error': 'Enter why this payment is moving.', 'status': 400}
        token = (client_token or '').strip()
        db = _db()
        try:
            self._ensure_resolution_tables(db)
            db.execute('BEGIN IMMEDIATE')
            if token:
                prior = _row(db.execute(
                    "SELECT id FROM debt_allocation_changes WHERE client_token=?", (token,),
                ))
                if prior:
                    db.commit()
                    return {'success': True, 'duplicate': True, 'id': prior['id']}
            pay = _row(db.execute("SELECT * FROM debt_payments WHERE id=?", (int(payment_id),)))
            if not pay or int(pay.get('reversed') or 0) == 1:
                db.rollback()
                return {'error': 'That payment cannot be moved.', 'status': 409}
            source = _row(db.execute("SELECT * FROM debt_invoices WHERE id=?", (pay['invoice_id'],)))
            target = _row(db.execute("SELECT * FROM debt_invoices WHERE id=?", (int(target_invoice_id),)))
            if not source or not target:
                db.rollback()
                return {'error': 'Invoice was not found.', 'status': 404}
            if int(source['id']) == int(target['id']):
                db.rollback()
                return {'error': 'Choose a different debt.', 'status': 400}
            if int(source['customer_id']) != int(target['customer_id']):
                db.rollback()
                return {'error': 'The payment can only move to a debt of the same customer.', 'status': 400}
            if target['status'] in ('paid', 'cancelled', 'written_off'):
                db.rollback()
                return {'error': 'The other debt is not open.', 'status': 409}
            amount = round(float(pay['amount'] or 0), 2)
            target_balance = round(float(target['balance'] or 0), 2)
            if amount > target_balance + 0.001:
                db.rollback()
                return {'error': 'That debt cannot take the whole payment.', 'status': 400}
            source_balance = round(float(source['balance'] or 0), 2)
            source_paid = round(float(source['amount_paid'] or 0), 2)
            moved = db.execute(
                "UPDATE debt_payments SET invoice_id=? WHERE id=? AND invoice_id=? AND COALESCE(reversed,0)=0",
                (int(target['id']), int(payment_id), int(source['id'])),
            )
            if moved.rowcount != 1:
                db.rollback()
                return {'error': 'That payment changed. Reload and try again.', 'status': 409}
            src_ok = db.execute(
                "UPDATE debt_invoices SET amount_paid=?, balance=?, status=?, updated_at=? WHERE id=? AND balance=?",
                (round(max(0.0, source_paid - amount), 2), round(source_balance + amount, 2),
                 'partial' if source_paid - amount > 0.009 else 'pending',
                 datetime.now().isoformat(), int(source['id']), source_balance),
            )
            tgt_paid = round(float(target['amount_paid'] or 0) + amount, 2)
            tgt_balance = round(target_balance - amount, 2)
            tgt_status = 'paid' if tgt_balance <= 0.009 else 'partial'
            tgt_ok = db.execute(
                "UPDATE debt_invoices SET amount_paid=?, balance=?, status=?, updated_at=? WHERE id=? AND balance=?",
                (tgt_paid, max(0.0, tgt_balance), tgt_status, datetime.now().isoformat(),
                 int(target['id']), target_balance),
            )
            if src_ok.rowcount != 1 or tgt_ok.rowcount != 1:
                db.rollback()
                return {'error': 'A balance changed. Reload and try again.', 'status': 409}
            db.execute(
                "INSERT INTO debt_allocation_changes "
                "(payment_id, from_invoice_id, to_invoice_id, amount, reason, client_token, user_id, username) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (int(payment_id), int(source['id']), int(target['id']), amount, reason,
                 token or None, self._user_id, self._username or ''),
            )
            db.commit()
            return {
                'success': True,
                'amount': amount,
                'from_balance': round(source_balance + amount, 2),
                'to_balance': max(0.0, tgt_balance),
                'refund': False,
            }
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            return {'error': str(exc), 'status': 500}
        finally:
            db.close()

    def cancel_sale_resolve_debt(self, invoice_id: int, reason: str,
                                 *, refund_status: str = 'none',
                                 refund_method: str = '', refund_reference: str = '',
                                 refund_amount: float | None = None,
                                 restore: list | None = None,
                                 client_token: str = '') -> dict:
        """Cancel the original sale and clear its debt. Stock returns only for the quantities given."""
        if (self._role or '').lower() not in ('admin', 'superadmin', 'manager'):
            return {'error': 'Only a manager or admin can cancel a sale.', 'status': 403}
        reason = (reason or '').strip()
        if len(reason) < 3:
            return {'error': 'Enter why this sale is being cancelled.', 'status': 400}
        refund_status = (refund_status or 'none').strip()
        if refund_status not in ('none', 'pending', 'completed'):
            return {'error': 'Choose whether a refund is due, pending, or already completed.', 'status': 400}
        token = (client_token or '').strip()
        db = _db()
        try:
            self._ensure_resolution_tables(db)
            db.execute('BEGIN IMMEDIATE')
            if token:
                prior = _row(db.execute(
                    "SELECT id, sale_id FROM debt_sale_cancellations WHERE client_token=?",
                    (token,),
                ))
                if prior:
                    db.commit()
                    return {'success': True, 'duplicate': True, 'id': prior['id'], 'sale_id': prior['sale_id']}
            inv = _row(db.execute("SELECT * FROM debt_invoices WHERE id=?", (int(invoice_id),)))
            if not inv or not inv.get('sale_id'):
                db.rollback()
                return {'error': 'That debt is not linked to a sale.', 'status': 404}
            sale = _row(db.execute("SELECT * FROM sales WHERE id=?", (int(inv['sale_id']),)))
            if not sale:
                db.rollback()
                return {'error': 'Sale was not found.', 'status': 404}
            if (sale.get('status') or '') == 'voided':
                db.rollback()
                return {'error': 'This sale is already cancelled.', 'status': 409, 'already': True}
            payments = _rows(db.execute(
                "SELECT amount, COALESCE(reversed,0) AS reversed, payment_method, payment_reference "
                "FROM debt_payments WHERE invoice_id=?",
                (int(invoice_id),),
            ))
            money = round(sum(
                float(row['amount'] or 0) for row in payments if int(row.get('reversed') or 0) != 1
            ), 2)
            if money <= 0.009 and refund_status != 'none':
                db.rollback()
                return {'error': 'No money was received, so there is nothing to refund.', 'status': 400}
            if money > 0.009 and refund_status == 'none':
                db.rollback()
                return {
                    'error': 'Money was received. Record a completed refund or leave it pending.',
                    'status': 400,
                    'money_received': money,
                }
            lines = self._sale_stock_lines(db, sale['id'])
            wanted = {}
            if restore is None:
                for line in lines:
                    if line.get('product_id'):
                        wanted[int(line['product_id'])] = float(line['eligible'] or 0)
            else:
                for line in restore:
                    pid = int(line.get('product_id') or 0)
                    qty = float(line.get('quantity') or 0)
                    if pid and qty > 0:
                        wanted[pid] = wanted.get(pid, 0.0) + qty
            eligible = {int(line['product_id']): float(line['eligible'] or 0) for line in lines if line.get('product_id')}
            for pid, qty in wanted.items():
                if qty - eligible.get(pid, 0.0) > 0.001:
                    db.rollback()
                    return {'error': 'A product is being restored for more than was sold.', 'status': 400}
            now = datetime.now().isoformat()
            restored = []
            for pid, qty in wanted.items():
                if qty <= 0:
                    continue
                prod = _row(db.execute("SELECT id, name, stock FROM products WHERE id=?", (pid,)))
                if not prod:
                    continue
                old_stock = float(prod['stock'] or 0)
                new_stock = old_stock + qty
                db.execute(
                    "UPDATE products SET stock=?, updated_at=? WHERE id=?",
                    (new_stock, now, pid),
                )
                db.execute(
                    "INSERT INTO stock_movements "
                    "(product_id,product_name,movement_type,qty_before,qty_change,"
                    "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (pid, prod['name'], 'VOID_RESTORE', old_stock, qty, new_stock,
                     f"VOID_sale={int(sale['id'])}:p={pid}",
                     f"Sale {sale.get('receipt_number') or sale['id']} cancelled: {reason}",
                     self._user_id, self._username or ''),
                )
                restored.append({'product_id': pid, 'quantity': qty, 'stock_after': new_stock})
            if refund_status == 'completed':
                try:
                    paid_back = round(float(refund_amount if refund_amount is not None else money), 2)
                except (TypeError, ValueError):
                    db.rollback()
                    return {'error': 'Enter the refund amount.', 'status': 400}
                method = (refund_method or '').strip()
                if paid_back <= 0 or not method:
                    db.rollback()
                    return {'error': 'A completed refund needs an amount and a method.', 'status': 400}
                if paid_back - money > 0.001:
                    db.rollback()
                    return {'error': 'The refund is larger than the money received.', 'status': 400}
                db.execute(
                    "INSERT INTO debt_refunds "
                    "(invoice_id, sale_id, amount, method, reference, reason, status, client_token, user_id, username) "
                    "VALUES (?,?,?,?,?,?, 'completed', ?,?,?)",
                    (int(inv['id']), int(sale['id']), paid_back, method,
                     (refund_reference or '').strip(), reason, (token + ':refund') if token else None,
                     self._user_id, self._username or ''),
                )
                leftover = round(money - paid_back, 2)
                if leftover > 0.009:
                    db.execute(
                        "INSERT INTO debt_refunds "
                        "(invoice_id, sale_id, amount, method, reference, reason, status, user_id, username) "
                        "VALUES (?,?,?,?,?,?, 'pending', ?,?)",
                        (int(inv['id']), int(sale['id']), leftover, '', '',
                         'Remainder still to be refunded after ' + reason,
                         self._user_id, self._username or ''),
                    )
            elif refund_status == 'pending':
                db.execute(
                    "INSERT INTO debt_refunds "
                    "(invoice_id, sale_id, amount, method, reference, reason, status, client_token, user_id, username) "
                    "VALUES (?,?,?,?,?,?, 'pending', ?,?,?)",
                    (int(inv['id']), int(sale['id']), money, '', '', reason,
                     (token + ':pending') if token else None,
                     self._user_id, self._username or ''),
                )
            db.execute(
                "UPDATE debt_invoices SET status='cancelled', balance=0, notes=?, updated_at=? WHERE id=?",
                (f"CANCELLED with sale {sale.get('receipt_number') or sale['id']}: {reason}. "
                 f"Money still recorded: {money:.2f}. Refund: {refund_status}.",
                 now, int(inv['id'])),
            )
            db.execute(
                "UPDATE sales SET status='voided', notes=? WHERE id=? AND status!='voided'",
                (f"VOIDED by {self._username}: {reason}", int(sale['id'])),
            )
            db.execute(
                "INSERT INTO sale_edits "
                "(sale_id,edited_by_id,edited_by_name,edit_type,field_name,old_value,new_value,reason) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (int(sale['id']), self._user_id, self._username or 'admin',
                 'VOID', 'status', sale.get('status') or 'completed', 'voided', reason),
            )
            db.execute(
                "INSERT INTO debt_sale_cancellations "
                "(sale_id, invoice_id, reason, refund_status, client_token, user_id, username) "
                "VALUES (?,?,?,?,?,?,?)",
                (int(sale['id']), int(inv['id']), reason, refund_status, token or None,
                 self._user_id, self._username or ''),
            )
            db.commit()
            return {
                'success': True,
                'sale_status': 'voided',
                'debt_status': 'cancelled',
                'outstanding': 0,
                'money_received': money,
                'refund_status': refund_status,
                'stock_restored': restored,
            }
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            return {'error': str(exc), 'status': 500}
        finally:
            db.close()

    def write_off_debt(self, invoice_id: int, amount: float, reason: str = '',
                       *, pin: str = '', client_token: str = '') -> dict:
        """Reduce a debt without recording a cash receipt. The invoice row stays."""
        if (self._role or '').lower() != 'superadmin':
            return {'error': 'Only a Super-Admin can write off a debt.', 'status': 403}
        reason = (reason or '').strip()
        if not reason:
            return {'error': 'Enter a reason for the write-off.', 'status': 400}
        try:
            amount = round(float(amount), 2)
        except (TypeError, ValueError):
            return {'error': 'Enter the amount to write off.', 'status': 400}
        if amount <= 0:
            return {'error': 'Amount must be greater than zero.', 'status': 400}
        token = (client_token or '').strip()
        db = _db()
        try:
            from desktop.utils.security import _pin_hash
            stored = db.execute(
                "SELECT value FROM system_settings WHERE key='superadmin_pin_hash'"
            ).fetchone()
            stored_hash = str(stored['value'] if stored else '')
            supplied = '' if pin is None else str(pin)
            if not supplied or not stored_hash or _pin_hash(supplied) != stored_hash:
                return {'error': 'Super-Admin PIN is required.', 'status': 403}
            db.execute(
                """CREATE TABLE IF NOT EXISTS debt_write_offs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    reason TEXT NOT NULL,
                    client_token TEXT UNIQUE,
                    user_id INTEGER,
                    username TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            db.execute('BEGIN IMMEDIATE')
            if token:
                prior = _row(db.execute(
                    "SELECT id, amount FROM debt_write_offs WHERE client_token=?",
                    (token,),
                ))
                if prior:
                    db.commit()
                    return {'success': True, 'duplicate': True, 'id': prior['id'],
                            'amount': prior['amount']}
            inv = _row(db.execute(
                "SELECT id, balance, status, total_amount FROM debt_invoices WHERE id=?",
                (int(invoice_id),),
            ))
            if not inv:
                db.rollback()
                return {'error': 'Invoice was not found.', 'status': 404}
            balance = round(float(inv['balance'] or 0), 2)
            if inv['status'] in ('paid', 'cancelled', 'written_off') or balance <= 0:
                db.rollback()
                return {'error': 'This invoice has no balance to write off.', 'status': 409}
            if amount > balance + 0.001:
                db.rollback()
                return {'error': 'Write-off is larger than the balance.', 'status': 400}
            new_balance = round(balance - amount, 2)
            status = 'written_off' if new_balance <= 0.009 else inv['status']
            cur = db.execute(
                "UPDATE debt_invoices SET balance=?, status=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND balance=?",
                (new_balance, status, int(invoice_id), balance),
            )
            if cur.rowcount != 1:
                db.rollback()
                return {'error': 'The balance changed. Reload and try again.', 'status': 409}
            db.execute(
                "INSERT INTO debt_write_offs "
                "(invoice_id, amount, reason, client_token, user_id, username) "
                "VALUES (?,?,?,?,?,?)",
                (int(invoice_id), amount, reason, token or None,
                 self._user_id, self._username or ''),
            )
            db.commit()
            return {'success': True, 'balance': new_balance, 'status': status,
                    'cash_receipt': False}
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            return {'error': str(exc), 'status': 500}
        finally:
            db.close()

    def record_print_attempt(self, sale_id: int, outcome: str, message: str = '') -> dict:
        """Store a print result on its own. This never creates a sale."""
        outcome = (outcome or '').strip().lower()
        if outcome not in ('queued', 'printed', 'failed'):
            return {'error': 'Print outcome must be queued, printed, or failed.', 'status': 400}
        db = _db()
        try:
            db.execute(
                """CREATE TABLE IF NOT EXISTS print_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER,
                    outcome TEXT NOT NULL,
                    message TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            before = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            db.execute(
                "INSERT INTO print_attempts (sale_id, outcome, message) VALUES (?,?,?)",
                (int(sale_id) if sale_id else None, outcome, message or ''),
            )
            after = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            db.commit()
            attempt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            return {'success': True, 'id': attempt_id, 'sales_unchanged': before == after}
        except Exception as exc:
            return {'error': str(exc), 'status': 500}
        finally:
            db.close()

    def print_history(self, sale_id: int) -> list:
        db = _db()
        try:
            db.execute(
                """CREATE TABLE IF NOT EXISTS print_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER,
                    outcome TEXT NOT NULL,
                    message TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            return _rows(db.execute(
                "SELECT id, sale_id, outcome, message, created_at "
                "FROM print_attempts WHERE sale_id=? ORDER BY id",
                (int(sale_id),),
            ))
        finally:
            db.close()

    def get_aging_report(self) -> dict:
        """Debt aging: 0-30, 31-60, 61-90, 90+ days."""
        db = _db()
        try:
            bands = [
                ('current',   "due_date IS NULL OR due_date >= date('now')"),
                ('1_30',      "due_date < date('now') AND due_date >= date('now','-30 days')"),
                ('31_60',     "due_date < date('now','-30 days') AND due_date >= date('now','-60 days')"),
                ('61_90',     "due_date < date('now','-60 days') AND due_date >= date('now','-90 days')"),
                ('over_90',   "due_date < date('now','-90 days')"),
            ]
            result = {}
            for key, clause in bands:
                row = _row(db.execute(
                    f"SELECT COALESCE(SUM(balance),0) as total, COUNT(*) as count "
                    f"FROM debt_invoices WHERE status NOT IN ('paid','cancelled') AND ({clause})"
                ))
                result[key] = dict(row) if row else {'total': 0, 'count': 0}
            return result
        finally:
            db.close()

    def cancel_invoice(self, invoice_id: int, reason: str) -> dict:
        if self._role not in ('admin', 'superadmin'):
            return {'error': 'Insufficient permissions'}
        db = _db()
        try:
            inv = _row(db.execute("SELECT * FROM debt_invoices WHERE id=?", (invoice_id,)))
            if not inv:
                return {'error': 'Invoice not found'}
            db.execute(
                "UPDATE debt_invoices SET status='cancelled', notes=?, updated_at=? WHERE id=?",
                (f"CANCELLED: {reason}", datetime.now().isoformat(), invoice_id)
            )
            db.commit()
            _audit(self._user_id, self._username, 'CANCEL_INVOICE', 'debt',
                   f"inv={inv['invoice_number']} reason={reason}")
            return {'success': True}
        except Exception as e:
            db.rollback()
            return {'error': str(e)}
        finally:
            db.close()

    def delete_debt_invoice(self, invoice_id: int, reason: str) -> dict:
        """
        Clear an open debt invoice. Superadmin only.

        Paths:
          - Unpaid (amount_paid ≈ 0): void linked POS sale (full restock), or
            cancel orphan / already-voided sale invoice and recover stock if
            VOID_RESTORE was never applied.
          - Partial (amount_paid > 0, balance > 0): write off remaining balance
            only — keep sale, sale_items, payments, and products. No restock
            (goods were delivered; unpaid share is a receivable write-off).

        Blocked: fully paid, already cancelled/written_off.
        Entire unpaid void/restock path is transactional (void_sale BEGIN/COMMIT).
        """
        if self._role != 'superadmin':
            _audit(self._user_id, self._username,
                   'DELETE_DEBT_DENIED', 'debt',
                   f"invoice_id={invoice_id} role={self._role}")
            return {'error': 'Only superadmin can delete debts.'}

        reason = (reason or '').strip()
        if not reason:
            return {'error': 'A deletion reason is required.'}

        db = _db()
        try:
            inv = _row(db.execute(
                "SELECT * FROM debt_invoices WHERE id=?", (invoice_id,)
            ))
            if not inv:
                return {'error': 'Invoice not found'}

            status = (inv.get('status') or '').lower()
            if status in ('cancelled', 'written_off'):
                return {'error': 'Debt is already cancelled.'}
            if status == 'paid':
                return {'error': 'Fully paid debts cannot be deleted.'}

            paid_amt = round(float(inv.get('amount_paid') or 0), 2)
            balance = round(float(inv.get('balance') or 0), 2)
            total_amt = round(float(inv.get('total_amount') or 0), 2)
            if balance <= 0.009:
                return {'error': 'Fully paid debts cannot be deleted.'}

            sale_id = inv.get('sale_id')
            inv_num = inv.get('invoice_number') or ''
            receipt_hint = (inv.get('receipt_number') or '').strip()
            now = datetime.now().isoformat()

            # Resolve sale_id from receipt when missing
            if not sale_id and receipt_hint:
                linked = db.execute(
                    "SELECT id, status, receipt_number FROM sales WHERE receipt_number=?",
                    (receipt_hint,)
                ).fetchone()
                if linked:
                    sale_id = linked['id']
                    db.execute(
                        "UPDATE debt_invoices SET sale_id=? WHERE id=? AND sale_id IS NULL",
                        (sale_id, invoice_id)
                    )

            # ── Partial debt: write off remaining balance only ──────────────
            if paid_amt > 0.009:
                note = (
                    f"WRITTEN_OFF remaining {balance:,.2f} "
                    f"(paid {paid_amt:,.2f} of {total_amt:,.2f} kept): {reason}"
                )
                prev_notes = (inv.get('notes') or '').strip()
                if prev_notes:
                    note = f"{prev_notes}\n{note}"
                db.execute(
                    "UPDATE debt_invoices SET status='cancelled', balance=0, notes=?, "
                    "updated_at=? WHERE id=?",
                    (note, now, invoice_id)
                )
                db.commit()
                _audit(
                    self._user_id, self._username, 'WRITE_OFF_DEBT', 'debt',
                    f"inv={inv_num} invoice_id={invoice_id} sale_id={sale_id} "
                    f"paid={paid_amt} written_off={balance} total={total_amt} "
                    f"restock=none reason={reason}"
                )
                return {
                    'success': True,
                    'invoice_id': invoice_id,
                    'sale_id': int(sale_id) if sale_id else None,
                    'mode': 'write_off',
                    'amount_paid': paid_amt,
                    'written_off': balance,
                    'restocked': False,
                    'restock': [],
                    'message': (
                        'Remaining balance written off. Payments and sale history '
                        'kept. Stock not restocked for partial debts.'
                    ),
                }

            # ── Unpaid: orphan / missing / already-voided ───────────────────
            if not sale_id:
                db.execute(
                    "UPDATE debt_invoices SET status='cancelled', balance=0, notes=?, "
                    "updated_at=? WHERE id=?",
                    (f"DELETED (orphan, no linked sale): {reason}",
                     now, invoice_id)
                )
                db.commit()
                _audit(self._user_id, self._username, 'DELETE_DEBT', 'debt',
                       f"inv={inv_num} invoice_id={invoice_id} sale_id=none "
                       f"restock=none reason={reason}")
                return {
                    'success': True,
                    'invoice_id': invoice_id,
                    'sale_id': None,
                    'mode': 'delete_unpaid',
                    'restocked': False,
                    'restock': [],
                    'message': 'Orphan debt cancelled (no linked sale to restock).',
                }

            sale = db.execute(
                "SELECT id, status, receipt_number FROM sales WHERE id=?",
                (sale_id,)
            ).fetchone()

            if not sale:
                db.execute(
                    "UPDATE debt_invoices SET status='cancelled', balance=0, notes=?, "
                    "updated_at=? WHERE id=?",
                    (f"DELETED (sale missing): {reason}", now, invoice_id)
                )
                db.commit()
                _audit(self._user_id, self._username, 'DELETE_DEBT', 'debt',
                       f"inv={inv_num} invoice_id={invoice_id} sale_id={sale_id} "
                       f"restock=none reason={reason}")
                return {
                    'success': True,
                    'invoice_id': invoice_id,
                    'sale_id': sale_id,
                    'mode': 'delete_unpaid',
                    'restocked': False,
                    'restock': [],
                    'message': 'Debt cancelled (linked sale missing).',
                }

            if sale['status'] == 'voided':
                # Recover stock if void never restored inventory
                db.execute("BEGIN IMMEDIATE")
                had_restore = self._has_void_restore(db, int(sale_id))
                restock = self._restock_sale_items(
                    db, int(sale_id),
                    receipt=sale['receipt_number'] or '',
                    reason=(
                        f"DELETE_DEBT recover stock inv={inv_num}: {reason}"
                    ),
                    movement_type='VOID_RESTORE',
                    skip_if_restored=True,
                )
                applied = [r for r in restock if not r.get('already_restored')]
                already = had_restore or (
                    bool(restock) and all(r.get('already_restored') for r in restock)
                )
                db.execute(
                    "UPDATE debt_invoices SET status='cancelled', balance=0, notes=?, "
                    "updated_at=? WHERE id=?",
                    (f"DELETED (sale already voided): {reason}", now, invoice_id)
                )
                db.commit()
                did_restock = bool(applied)
                restock_summary = '; '.join(
                    f"{r['product_name'] or ('#' + str(r['product_id']))} +{r['quantity']:g}"
                    for r in (applied or restock)
                ) or 'none'
                _audit(
                    self._user_id, self._username, 'DELETE_DEBT', 'debt',
                    f"inv={inv_num} invoice_id={invoice_id} sale_id={sale_id} "
                    f"restock=[{restock_summary}] "
                    f"recover={'yes' if did_restock else ('already' if already else 'none')} "
                    f"reason={reason}"
                )
                return {
                    'success': True,
                    'invoice_id': invoice_id,
                    'sale_id': int(sale_id),
                    'mode': 'delete_unpaid',
                    'restocked': did_restock or already,
                    'restock': applied or restock,
                    'message': (
                        'Debt cancelled; stock recovered for voided sale.'
                        if did_restock else
                        'Debt cancelled (linked sale was already voided; stock already restored).'
                        if already else
                        'Debt cancelled (linked sale was already voided).'
                    ),
                }

            # Preview restock list for response (live completed sale)
            restock = []
            items = db.execute(
                "SELECT si.product_id, si.quantity, p.name as product_name "
                "FROM sale_items si "
                "LEFT JOIN products p ON p.id=si.product_id "
                "WHERE si.sale_id=?",
                (sale_id,)
            ).fetchall()
            for it in items:
                if it['product_id']:
                    restock.append({
                        'product_id': it['product_id'],
                        'product_name': it['product_name'] or '',
                        'quantity': float(it['quantity'] or 0),
                    })
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error(f"delete_debt_invoice preview: {e}", exc_info=True)
            return {'error': str(e)}
        finally:
            db.close()

        # Linked live unpaid sale — void_sale (transactional restock + cancel debt)
        void_reason = f"DELETE_DEBT inv={inv_num}: {reason}"
        res = self.void_sale(int(sale_id), void_reason, force_with_payments=False)
        if res.get('error'):
            return res

        # Ensure invoice cancelled even if void's debt cancel missed this id
        db2 = _db()
        try:
            row = db2.execute(
                "SELECT status FROM debt_invoices WHERE id=?", (invoice_id,)
            ).fetchone()
            if row and (row['status'] or '').lower() not in ('cancelled', 'written_off'):
                db2.execute(
                    "UPDATE debt_invoices SET status='cancelled', balance=0, notes=?, "
                    "updated_at=? WHERE id=?",
                    (f"DELETED via void sale: {reason}",
                     datetime.now().isoformat(), invoice_id)
                )
                db2.commit()
        finally:
            db2.close()

        restock_summary = '; '.join(
            f"{r['product_name'] or ('#' + str(r['product_id']))} +{r['quantity']:g}"
            for r in restock
        ) or 'none'
        _audit(self._user_id, self._username, 'DELETE_DEBT', 'debt',
               f"inv={inv_num} invoice_id={invoice_id} sale_id={sale_id} "
               f"restock=[{restock_summary}] reason={reason}")
        return {
            'success': True,
            'invoice_id': invoice_id,
            'sale_id': int(sale_id),
            'mode': 'delete_unpaid',
            'restocked': True,
            'restock': restock,
            'message': 'Debt deleted and stock restored via void sale.',
            'void': res,
        }

    # ── INTERNAL STOCK CONSUMPTION ──────────────────────────────────────────────

    CONSUMPTION_REASONS = (
        'Production', 'Staff Consumption', 'Office Use', 'Cleaning', 'Sampling',
        'Damaged During Production', 'Donation', 'Promotion', 'Other',
    )

    def _device_name(self) -> str:
        try:
            # Prefer env — socket.gethostname() can stall on broken DNS/NetBIOS
            name = (os.environ.get('COMPUTERNAME') or os.environ.get('HOSTNAME') or '').strip()
            if name:
                return name
            import socket
            socket.setdefaulttimeout(2.0)
            return socket.gethostname() or 'unknown'
        except Exception:
            return 'unknown'

    def _next_consumption_ref(self, db) -> str:
        row = db.execute(
            "SELECT reference_no FROM stock_consumptions "
            "WHERE reference_no LIKE 'AUTO-%' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        n = 0
        if row and row[0]:
            try:
                n = int(str(row[0]).split('-', 1)[1])
            except (IndexError, ValueError):
                n = db.execute("SELECT COUNT(*) FROM stock_consumptions").fetchone()[0]
        return f"AUTO-{n + 1:06d}"

    def save_department(self, name: str) -> dict:
        name = (name or '').strip()
        if not name:
            return {'error': 'Enter a department name.', 'status': 400}
        if (self._role or '').lower() not in ('manager', 'admin', 'superadmin'):
            return {'error': 'You cannot change departments.', 'status': 403}
        db = _db()
        try:
            existing = db.execute(
                "SELECT id, active FROM departments WHERE name=?", (name,)
            ).fetchone()
            if existing:
                db.execute("UPDATE departments SET active=1 WHERE id=?", (existing['id'],))
                db.commit()
                return {'success': True, 'id': existing['id'], 'duplicate': True}
            db.execute("INSERT INTO departments (name, active) VALUES (?, 1)", (name,))
            db.commit()
            return {'success': True, 'id': db.execute('SELECT last_insert_rowid()').fetchone()[0]}
        finally:
            db.close()

    def get_departments(self, active_only: bool = True) -> list:
        db = _db()
        try:
            if active_only:
                return _rows(db.execute(
                    "SELECT * FROM departments WHERE active=1 ORDER BY name"
                ))
            return _rows(db.execute("SELECT * FROM departments ORDER BY name"))
        finally:
            db.close()

    def peek_next_consumption_ref(self) -> str:
        db = _db()
        try:
            return self._next_consumption_ref(db)
        finally:
            db.close()

    def create_consumption(self, data: dict) -> dict:
        """
        Record internal stock consumption. Decrements stock, writes INTERNAL_USE
        ledger rows, and full audit. No customer / payment / receipt.
        data: date, department_id, reason, notes, taken_by, items[{product_id, quantity, unit_cost?}]
        """
        items = data.get('items') or []
        if not items:
            return {'error': 'Add at least one product line.'}
        if (self._role or '').lower() not in ('cashier', 'manager', 'admin', 'superadmin'):
            return {
                'error': 'You cannot record internal consumption.',
                'status': 403,
            }
        reason = (data.get('reason') or '').strip()
        if not reason:
            return {'error': 'Reason is required.'}
        dept_id = data.get('department_id')
        if not dept_id:
            return {'error': 'Department is required.'}

        db = _db()
        device = self._device_name()
        try:
            db.execute("BEGIN IMMEDIATE")
            token = (data.get('client_token') or '').strip()
            canonical = {
                'date': (data.get('date') or str(date.today())).strip(),
                'department_id': int(dept_id),
                'reason': reason,
                'notes': (data.get('notes') or '').strip(),
                'taken_by': (data.get('taken_by') or '').strip(),
                'items': sorted(
                    (
                        {
                            'product_id': int(item.get('product_id') or 0),
                            'quantity': round(float(item.get('quantity') or 0), 4),
                        }
                        for item in items
                    ),
                    key=lambda row: row['product_id'],
                ),
            }
            receipt = _read_request_receipt(db, token, 'create_consumption', canonical)
            if receipt and receipt.get('error'):
                db.rollback()
                return receipt
            if receipt and not receipt.get('new'):
                db.rollback()
                return receipt
            dept = db.execute(
                "SELECT id, name FROM departments WHERE id=? AND active=1",
                (dept_id,)
            ).fetchone()
            if not dept:
                db.rollback()
                return {'error': 'Invalid department.'}

            ref = self._next_consumption_ref(db)
            cons_date = (data.get('date') or str(date.today())).strip()
            notes = (data.get('notes') or '').strip()
            taken_by = (data.get('taken_by') or '').strip()
            created_name = self._username or 'staff'
            now = datetime.now().isoformat()

            line_rows = []
            total_cost = 0.0
            seen_products = set()
            for item in items:
                pid = item.get('product_id')
                qty = round(float(item.get('quantity') or 0), 4)
                if not pid or qty <= 0:
                    db.rollback()
                    return {'error': 'Each line needs a product and quantity > 0.'}
                if int(pid) in seen_products:
                    db.rollback()
                    return {'error': 'Enter each product once on this consumption.'}
                seen_products.add(int(pid))
                prod = db.execute(
                    "SELECT id, name, sku, unit, stock, cost_price, price FROM products WHERE id=? AND is_active=1",
                    (pid,)
                ).fetchone()
                if not prod:
                    db.rollback()
                    return {'error': f'Product id {pid} not found.'}
                stock = round(float(prod['stock'] or 0), 4)
                if stock < qty:
                    db.rollback()
                    return {
                        'error': (
                            f"Insufficient stock for '{prod['name']}': "
                            f"requested {qty}, available {stock}"
                        )
                    }
                unit_cost = item.get('unit_cost')
                if unit_cost is None or unit_cost == '':
                    unit_cost = float(prod['cost_price'] or 0)
                else:
                    unit_cost = float(unit_cost)
                unit_cost = round(unit_cost, 4)
                line_total = round(qty * unit_cost, 2)
                selling = round(float(prod['price'] or 0), 4)
                opportunity = round(qty * selling, 2)
                foregone = round(opportunity - line_total, 2)
                total_cost += line_total
                line_rows.append((prod, qty, unit_cost, line_total, stock, selling, opportunity, foregone))

            db.execute(
                "INSERT INTO stock_consumptions "
                "(reference_no, date, department_id, reason, notes, taken_by, total_cost,"
                " created_by, created_by_name, created_at, voided) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,0)",
                (ref, cons_date, dept_id, reason, notes, taken_by, round(total_cost, 2),
                 self._user_id, created_name, now)
            )
            cons_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            audit_lines = []
            from desktop.utils.stock_layers import consume_fifo
            priced_rows = []
            total_cost = 0.0
            for prod, qty, unit_cost, line_total, old_stock, selling, opportunity, foregone in line_rows:
                layer = consume_fifo(
                    db, int(prod['id']), qty,
                    reference=f"CONSUMPTION:{cons_id}:{prod['id']}",
                )
                if layer.get('error'):
                    db.rollback()
                    return {'error': layer['error']}
                if layer.get('success'):
                    unit_cost = round(float(layer['cogs']) / qty, 4)
                    line_total = round(qty * unit_cost, 2)
                    opportunity = round(qty * selling, 2)
                    foregone = round(opportunity - line_total, 2)
                total_cost += line_total
                priced_rows.append(
                    (prod, qty, unit_cost, line_total, old_stock, selling, opportunity, foregone)
                )
            db.execute(
                "UPDATE stock_consumptions SET total_cost=? WHERE id=?",
                (round(total_cost, 2), cons_id),
            )

            for prod, qty, unit_cost, line_total, old_stock, selling, opportunity, foregone in priced_rows:
                new_stock = round(old_stock - qty, 4)
                db.execute(
                    "INSERT INTO stock_consumption_items "
                    "(consumption_id, product_id, product_name, quantity, unit_cost, total_cost,"
                    " selling_price, retail_opportunity, foregone_profit, unit, stock_before, stock_after) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (cons_id, prod['id'], prod['name'], qty, unit_cost, line_total,
                     selling, opportunity, foregone, prod['unit'] or 'pcs',
                     old_stock, round(old_stock - qty, 4))
                )
                changed = db.execute(
                    "UPDATE products SET stock=?, updated_at=? "
                    "WHERE id=? AND ROUND(COALESCE(stock,0),4)=?",
                    (new_stock, now, prod['id'], old_stock),
                )
                if changed.rowcount != 1:
                    db.rollback()
                    return {'error': 'Stock changed before the consumption could be saved.'}
                mov_reason = (
                    f"{reason} | Dept: {dept['name']}"
                    + (f" | Taken by: {taken_by}" if taken_by else "")
                    + (f" | {notes}" if notes else "")
                    + f" | Device: {device}"
                )
                db.execute(
                    "INSERT INTO stock_movements "
                    "(product_id,product_name,movement_type,qty_before,qty_change,"
                    "qty_after,reference,reason,user_id,username,device_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (prod['id'], prod['name'], 'INTERNAL_USE',
                     old_stock, -qty, new_stock,
                     ref, mov_reason,
                     self._user_id, created_name, device)
                )
                audit_lines.append(
                    f"{prod['name']} {old_stock}->{new_stock} qty={qty}"
                )
                _audit(
                    self._user_id, created_name, 'INTERNAL_USE', 'inventory',
                    f"ref={ref} product={prod['name']} prev={old_stock} new={new_stock} "
                    f"qty={qty} reason={reason} notes={notes} device={device}",
                    conn=db,
                )

            try:
                from desktop.utils.accounting_hooks import post_consumption_journal
                posted = post_consumption_journal(
                    db, cons_id,
                    user_id=self._user_id, username=created_name, safe=False)
            except Exception as journal_error:
                db.rollback()
                return {'error': f'Consumption was not saved: {journal_error}'}
            if posted.get('error'):
                db.rollback()
                return {'error': posted['error']}

            result = {
                'success': True,
                'id': cons_id,
                'reference_no': ref,
                'total_cost': round(total_cost, 2),
            }
            if receipt and receipt.get('new'):
                _save_request_receipt(
                    db, token, 'create_consumption', receipt['hash'], result,
                )
            db.commit()
            _audit(
                self._user_id, created_name, 'CREATE_CONSUMPTION', 'consumption',
                f"ref={ref} dept={dept['name']} total={total_cost:.2f} lines={len(line_rows)} "
                f"reason={reason} notes={notes} device={device} | "
                + '; '.join(audit_lines)
            )
            return result
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.exception('create_consumption failed')
            return {'error': str(e)}
        finally:
            db.close()

    def edit_consumption(self, consumption_id: int, data: dict) -> dict:
        """Correct a posted consumption by the quantity difference only."""
        if (self._role or '').lower() not in ('admin', 'superadmin'):
            return {'error': 'Only an admin can correct internal consumption.', 'status': 403}
        edit_reason = (data.get('edit_reason') or data.get('reason_for_change') or '').strip()
        if len(edit_reason) < 3:
            return {'error': 'Enter why this consumption is being corrected.', 'status': 400}
        items = data.get('items') or []
        if not items:
            return {'error': 'Keep at least one product, or void the consumption.', 'status': 400}
        db = _db()
        device = self._device_name()
        now = datetime.now().isoformat()
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS stock_consumption_revisions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, consumption_id INTEGER NOT NULL,"
                "reason TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL,"
                "edited_by INTEGER, edited_by_name TEXT, created_at TEXT)"
            )
            db.execute("BEGIN IMMEDIATE")
            token = (data.get('client_token') or '').strip()
            canonical = {
                'consumption_id': int(consumption_id),
                'edit_reason': edit_reason,
                'items': sorted(
                    (
                        {
                            'product_id': int(item.get('product_id') or 0),
                            'quantity': round(float(item.get('quantity') or 0), 4),
                        }
                        for item in items
                    ),
                    key=lambda row: row['product_id'],
                ),
            }
            receipt = _read_request_receipt(db, token, 'edit_consumption', canonical)
            if receipt and receipt.get('error'):
                db.rollback()
                return receipt
            if receipt and not receipt.get('new'):
                db.rollback()
                return receipt
            cons = db.execute(
                "SELECT * FROM stock_consumptions WHERE id=?", (int(consumption_id),)
            ).fetchone()
            if not cons:
                db.rollback()
                return {'error': 'Consumption not found.', 'status': 404}
            if int(cons['voided'] or 0) == 1:
                db.rollback()
                return {'error': 'A voided consumption cannot be edited.', 'status': 409}
            self._ensure_approval_table(db)
            open_rows = db.execute(
                "SELECT meta_json FROM cc_approvals "
                "WHERE type='consumption_void' AND status IN ('pending','escalated','executing')"
            ).fetchall()
            for open_row in open_rows:
                try:
                    open_meta = json.loads(open_row['meta_json'] or '{}')
                except json.JSONDecodeError:
                    open_meta = {}
                if int((open_meta or {}).get('consumption_id') or 0) == int(consumption_id):
                    db.rollback()
                    return {
                        'error': 'A void request is open. Finish that request before correcting this consumption.',
                        'status': 409,
                    }
            old_items = db.execute(
                "SELECT * FROM stock_consumption_items WHERE consumption_id=?",
                (int(consumption_id),),
            ).fetchall()
            old_by_id = {int(item['product_id']): item for item in old_items if item['product_id']}
            cleaned = []
            seen = set()
            for item in items:
                try:
                    pid = int(item.get('product_id') or 0)
                    qty = round(float(item.get('quantity') or 0), 4)
                except (TypeError, ValueError):
                    db.rollback()
                    return {'error': 'Each line needs a product and a quantity.', 'status': 400}
                if pid <= 0 or qty <= 0:
                    db.rollback()
                    return {'error': 'Each line needs a product and quantity > 0.', 'status': 400}
                if pid in seen:
                    db.rollback()
                    return {'error': 'Enter each product once on this consumption.', 'status': 400}
                seen.add(pid)
                cleaned.append({'product_id': pid, 'quantity': qty})
            from desktop.utils.stock_layers import consume_fifo, restore_reference_quantity
            created_name = self._username or 'admin'
            before = [
                {
                    'product_id': int(item['product_id']),
                    'product_name': item['product_name'],
                    'quantity': float(item['quantity'] or 0),
                    'unit_cost': float(item['unit_cost'] or 0),
                }
                for item in old_items
            ]
            after = []
            total_cost = 0.0
            movements = []
            for item in cleaned:
                pid = item['product_id']
                qty = item['quantity']
                prod = db.execute(
                    "SELECT id, name, sku, unit, stock, cost_price, price "
                    "FROM products WHERE id=? AND is_active=1",
                    (pid,),
                ).fetchone()
                if not prod:
                    db.rollback()
                    return {'error': f'Product id {pid} not found.', 'status': 404}
                old = old_by_id.get(pid)
                old_qty = round(float(old['quantity'] or 0), 4) if old else 0.0
                old_cost = round(float(old['unit_cost'] or 0), 4) if old else round(float(prod['cost_price'] or 0), 4)
                delta = round(qty - old_qty, 4)
                stock = round(float(prod['stock'] or 0), 4)
                unit_cost = old_cost
                if delta > 0:
                    if stock + 1e-9 < delta:
                        db.rollback()
                        return {
                            'error': (
                                f"Insufficient stock for '{prod['name']}': "
                                f"additional {delta}, available {stock}"
                            ),
                            'status': 400,
                        }
                    layer = consume_fifo(
                        db, pid, delta,
                        reference=f"CONSUMPTION:{int(consumption_id)}:{pid}:REV:{now}",
                    )
                    if layer.get('error'):
                        db.rollback()
                        return {'error': layer['error'], 'status': 400}
                    extra = round(float(layer.get('cogs') or 0), 4) if layer.get('success') else round(delta * old_cost, 4)
                    unit_cost = round(((old_qty * old_cost) + extra) / qty, 4)
                elif delta < 0:
                    restored = restore_reference_quantity(
                        db, f"CONSUMPTION:{int(consumption_id)}:{pid}", abs(delta),
                    )
                    if restored.get('error'):
                        db.rollback()
                        return {'error': restored['error'], 'status': 409}
                    if not restored.get('skipped') and float(restored.get('restored') or 0) + 1e-9 < abs(delta):
                        db.rollback()
                        return {'error': 'The reduced quantity could not be restored.', 'status': 409}
                if abs(delta) > 1e-9:
                    new_stock = round(stock - delta, 4)
                    changed = db.execute(
                        "UPDATE products SET stock=?, updated_at=? "
                        "WHERE id=? AND ROUND(COALESCE(stock,0),4)=?",
                        (new_stock, now, pid, stock),
                    )
                    if changed.rowcount != 1:
                        db.rollback()
                        return {'error': 'Stock changed before the correction could be saved.', 'status': 409}
                    movements.append((prod, stock, -delta, new_stock))
                line_total = round(qty * unit_cost, 2)
                total_cost += line_total
                selling = round(float(prod['price'] or 0), 4)
                stored_before = None
                if old is not None and 'stock_before' in old.keys() and old['stock_before'] is not None:
                    stored_before = round(float(old['stock_before']), 4)
                elif old is not None:
                    first_move = db.execute(
                        "SELECT qty_before FROM stock_movements "
                        "WHERE reference=? AND product_id=? AND movement_type='INTERNAL_USE' "
                        "ORDER BY id LIMIT 1",
                        (cons['reference_no'], pid),
                    ).fetchone()
                    if first_move and first_move['qty_before'] is not None:
                        stored_before = round(float(first_move['qty_before']), 4)
                if old is None:
                    stock_before = stock
                    stock_after = round(stock - qty, 4)
                elif stored_before is None:
                    stock_before = None
                    stock_after = None
                else:
                    stock_before = stored_before
                    stock_after = round(stored_before - qty, 4)
                kept_unit = ''
                if old is not None and 'unit' in old.keys() and old['unit']:
                    kept_unit = old['unit']
                after.append({
                    'product_id': pid,
                    'product_name': prod['name'],
                    'sku': prod['sku'] or '',
                    'unit': kept_unit or prod['unit'] or 'pcs',
                    'quantity': qty,
                    'unit_cost': unit_cost,
                    'total_cost': line_total,
                    'selling_price': selling,
                    'retail_opportunity': round(qty * selling, 2),
                    'foregone_profit': round(qty * selling - line_total, 2),
                    'stock_before': stock_before,
                    'stock_after': stock_after,
                })
            removed = [pid for pid in old_by_id if pid not in seen]
            for pid in removed:
                old = old_by_id[pid]
                qty = round(float(old['quantity'] or 0), 4)
                prod = db.execute(
                    "SELECT id, name, stock FROM products WHERE id=?", (pid,)
                ).fetchone()
                if not prod:
                    db.rollback()
                    return {'error': 'A removed product no longer exists.', 'status': 409}
                restored = restore_reference_quantity(
                    db, f"CONSUMPTION:{int(consumption_id)}:{pid}", qty,
                )
                if restored.get('error'):
                    db.rollback()
                    return {'error': restored['error'], 'status': 409}
                stock = round(float(prod['stock'] or 0), 4)
                new_stock = round(stock + qty, 4)
                changed = db.execute(
                    "UPDATE products SET stock=?, updated_at=? "
                    "WHERE id=? AND ROUND(COALESCE(stock,0),4)=?",
                    (new_stock, now, pid, stock),
                )
                if changed.rowcount != 1:
                    db.rollback()
                    return {'error': 'Stock changed before the correction could be saved.', 'status': 409}
                movements.append((prod, stock, qty, new_stock))
            db.execute(
                "DELETE FROM stock_consumption_items WHERE consumption_id=?",
                (int(consumption_id),),
            )
            for line in after:
                db.execute(
                    "INSERT INTO stock_consumption_items "
                    "(consumption_id, product_id, product_name, quantity, unit_cost, total_cost,"
                    " selling_price, retail_opportunity, foregone_profit, unit, stock_before, stock_after) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (int(consumption_id), line['product_id'], line['product_name'], line['quantity'],
                     line['unit_cost'], line['total_cost'], line['selling_price'],
                     line['retail_opportunity'], line['foregone_profit'],
                     line.get('unit') or 'pcs', line.get('stock_before'), line.get('stock_after')),
                )
            header_reason = (data.get('reason') or cons['reason'] or '').strip()
            if not header_reason:
                db.rollback()
                return {'error': 'Reason is required.', 'status': 400}
            notes = cons['notes'] if 'notes' not in data else (data.get('notes') or '').strip()
            taken_by = cons['taken_by'] if 'taken_by' not in data else (data.get('taken_by') or '').strip()
            dept_id = cons['department_id'] if data.get('department_id') in (None, '') else int(data.get('department_id'))
            dept = db.execute(
                "SELECT name FROM departments WHERE id=? AND active=1", (dept_id,)
            ).fetchone()
            if not dept:
                db.rollback()
                return {'error': 'Invalid department.', 'status': 400}
            cons_date = (data.get('date') or cons['date'] or '').strip()
            db.execute(
                "UPDATE stock_consumptions SET reason=?, notes=?, taken_by=?, department_id=?,"
                " date=?, total_cost=? WHERE id=?",
                (header_reason, notes, taken_by, dept_id, cons_date, round(total_cost, 2), int(consumption_id)),
            )
            db.execute(
                "INSERT INTO stock_consumption_revisions "
                "(consumption_id, reason, before_json, after_json, edited_by, edited_by_name, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (int(consumption_id), edit_reason, json.dumps(before), json.dumps(after),
                 self._user_id, created_name, now),
            )
            for prod, old_stock, qty_change, new_stock in movements:
                kind = 'INTERNAL_USE' if qty_change < 0 else 'INTERNAL_USE_EDIT'
                db.execute(
                    "INSERT INTO stock_movements "
                    "(product_id,product_name,movement_type,qty_before,qty_change,"
                    "qty_after,reference,reason,user_id,username,device_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (prod['id'], prod['name'], kind, old_stock, qty_change, new_stock,
                     cons['reference_no'],
                     f"Correction: {edit_reason} | Device: {device}",
                     self._user_id, created_name, device),
                )
            result = {
                'success': True,
                'id': int(consumption_id),
                'reference_no': cons['reference_no'],
                'total_cost': round(total_cost, 2),
            }
            if receipt and receipt.get('new'):
                _save_request_receipt(db, token, 'edit_consumption', receipt['hash'], result)
            db.commit()
            _audit(
                self._user_id, created_name, 'EDIT_CONSUMPTION', 'consumption',
                f"ref={cons['reference_no']} reason={edit_reason} device={device}",
            )
            return result
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.exception('edit_consumption failed')
            return {'error': str(exc), 'status': 500}
        finally:
            db.close()

    def void_consumption(self, consumption_id: int, reason: str) -> dict:
        """Soft-void a consumption and restore stock. Admin / superadmin."""
        reason = (reason or '').strip()
        if not reason:
            return {'error': 'Void reason is required.'}
        if (self._role or '').lower() not in ('admin', 'superadmin'):
            _audit(self._user_id, self._username, 'VOID_CONSUMPTION_DENIED',
                   'consumption', f"id={consumption_id} role={self._role}")
            return {'error': 'Insufficient permissions to void consumptions.'}

        db = _db()
        device = self._device_name()
        now = datetime.now().isoformat()
        try:
            db.execute("BEGIN IMMEDIATE")
            cons = db.execute(
                "SELECT * FROM stock_consumptions WHERE id=?", (consumption_id,)
            ).fetchone()
            if not cons:
                db.rollback()
                return {'error': 'Consumption not found.'}
            if int(cons['voided'] or 0) == 1:
                db.rollback()
                return {'error': 'Consumption already voided.'}

            items = db.execute(
                "SELECT * FROM stock_consumption_items WHERE consumption_id=?",
                (consumption_id,)
            ).fetchall()

            from desktop.utils.stock_layers import restore_reference_layers
            restore_reference_layers(db, f"CONSUMPTION:{consumption_id}:")
            audit_lines = []
            for item in items:
                pid = item['product_id']
                if not pid:
                    continue
                prod = db.execute(
                    "SELECT id, name, stock FROM products WHERE id=?", (pid,)
                ).fetchone()
                if not prod:
                    continue
                old_stock = round(float(prod['stock'] or 0), 4)
                qty = round(float(item['quantity'] or 0), 4)
                new_stock = round(old_stock + qty, 4)
                db.execute(
                    "UPDATE products SET stock=?, updated_at=? WHERE id=?",
                    (new_stock, now, pid)
                )
                db.execute(
                    "INSERT INTO stock_movements "
                    "(product_id,product_name,movement_type,qty_before,qty_change,"
                    "qty_after,reference,reason,user_id,username,device_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, prod['name'], 'INTERNAL_USE_VOID',
                     old_stock, qty, new_stock,
                     cons['reference_no'],
                     f"Void restore: {reason} | Device: {device}",
                     self._user_id, self._username or 'admin', device)
                )
                audit_lines.append(
                    f"product={prod['name']} prev={old_stock} new={new_stock} qty={qty}"
                )

            db.execute(
                "UPDATE stock_consumptions SET voided=1, voided_by=?, voided_by_name=?,"
                " voided_at=?, void_reason=? WHERE id=?",
                (self._user_id, self._username or 'admin', now, reason, consumption_id)
            )
            try:
                from desktop.utils.accounting_hooks import reverse_consumption_journal
                reverse_consumption_journal(
                    db, consumption_id, reason=reason,
                    user_id=self._user_id, username=self._username or 'admin',
                    safe=True)
            except Exception as _je:
                logger.error('void consumption accounting: %s', _je, exc_info=True)
            db.commit()
            for line in audit_lines:
                _audit(
                    self._user_id, self._username, 'INTERNAL_USE_VOID', 'inventory',
                    f"ref={cons['reference_no']} {line} void_reason={reason} device={device}"
                )
            _audit(
                self._user_id, self._username, 'VOID_CONSUMPTION', 'consumption',
                f"ref={cons['reference_no']} reason={reason} device={device}"
            )
            return {'success': True}
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.exception('void_consumption failed')
            return {'error': str(e)}
        finally:
            db.close()

    def unvoid_consumption(self, consumption_id: int, reason: str) -> dict:
        """Restore one voided internal-use receipt. Super Admin session only."""
        reason = (reason or '').strip()
        if (self._role or '').lower() != 'superadmin':
            _audit(self._user_id, self._username, 'UNVOID_CONSUMPTION_DENIED',
                   'consumption', f"id={consumption_id} role={self._role}")
            return {'error': 'Only a signed-in Super Admin can restore a receipt.', 'status': 403}
        if not reason:
            return {'error': 'Enter a reason for restoring this receipt.', 'status': 400}
        db = _db()
        now = datetime.now().isoformat()
        try:
            db.execute('BEGIN IMMEDIATE')
            cons = db.execute(
                "SELECT * FROM stock_consumptions WHERE id=?", (int(consumption_id),)
            ).fetchone()
            if not cons:
                db.rollback()
                return {'error': 'Consumption not found.', 'status': 404}
            if int(cons['voided'] or 0) != 1:
                db.rollback()
                return {'success': True, 'duplicate': True, 'status': 'active'}
            items = db.execute(
                "SELECT product_id, quantity FROM stock_consumption_items WHERE consumption_id=?",
                (int(consumption_id),),
            ).fetchall()
            changes = []
            for item in items:
                pid = item['product_id']
                qty = round(float(item['quantity'] or 0), 4)
                if not pid or qty <= 0:
                    continue
                prod = db.execute(
                    "SELECT name, COALESCE(stock,0) AS stock FROM products WHERE id=?",
                    (int(pid),),
                ).fetchone()
                if not prod:
                    db.rollback()
                    return {'error': 'A product on this receipt no longer exists.', 'status': 409}
                old_stock = round(float(prod['stock'] or 0), 4)
                if old_stock + 1e-9 < qty:
                    db.rollback()
                    return {
                        'error': (
                            f"Not enough {prod['name']} on hand ({old_stock:g}) to restore "
                            f"this consumption ({qty:g})."
                        ),
                        'status': 409,
                    }
                new_stock = round(old_stock - qty, 4)
                changed = db.execute(
                    "UPDATE products SET stock=?, updated_at=? "
                    "WHERE id=? AND ROUND(COALESCE(stock,0),4)>=?",
                    (new_stock, now, int(pid), qty),
                )
                if changed.rowcount != 1:
                    db.rollback()
                    return {'error': 'Stock changed before the receipt could be restored.', 'status': 409}
                db.execute(
                    "INSERT INTO stock_movements "
                    "(product_id,product_name,movement_type,qty_before,qty_change,"
                    "qty_after,reference,reason,user_id,username,device_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (int(pid), prod['name'], 'INTERNAL_USE_UNVOID',
                     old_stock, -qty, new_stock, cons['reference_no'],
                     f"Restore voided consumption: {reason}",
                     self._user_id, self._username or 'superadmin', self._device_name()),
                )
                changes.append(f"{prod['name']} {old_stock}->{new_stock}")
            self._reapply_reference_layers(db, f"CONSUMPTION:{int(consumption_id)}:")
            db.execute(
                "UPDATE stock_consumptions SET voided=0 WHERE id=? AND voided=1",
                (int(consumption_id),),
            )
            db.commit()
            _audit(
                self._user_id, self._username, 'UNVOID_CONSUMPTION', 'consumption',
                f"ref={cons['reference_no']} reason={reason} "
                f"before=voided after=active stock={'; '.join(changes)} "
                f"original_void_reason={cons['void_reason'] or ''}",
            )
            return {'success': True, 'status': 'active', 'reference': cons['reference_no']}
        except ValueError as exc:
            try:
                db.rollback()
            except Exception:
                pass
            return {'error': str(exc), 'status': 409}
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.exception('unvoid_consumption failed')
            return {'error': str(exc), 'status': 500}
        finally:
            db.close()

    def _reapply_reference_layers(self, db, prefix: str) -> None:
        try:
            uses = db.execute(
                "SELECT id, layer_id, quantity FROM cost_layer_uses "
                "WHERE reference LIKE ? AND reversed=1",
                (prefix + '%',),
            ).fetchall()
        except Exception:
            return
        for use in uses:
            layer = db.execute(
                "SELECT remaining_qty FROM cost_layers WHERE id=?", (use['layer_id'],)
            ).fetchone()
            if not layer or float(layer['remaining_qty'] or 0) + 1e-9 < float(use['quantity'] or 0):
                raise ValueError(
                    'A later stock movement used the quantity this void returned. '
                    'The receipt was not restored.'
                )
        for use in uses:
            changed = db.execute(
                "UPDATE cost_layers SET remaining_qty=remaining_qty-? "
                "WHERE id=? AND remaining_qty>=?",
                (float(use['quantity'] or 0), use['layer_id'], float(use['quantity'] or 0)),
            )
            if changed.rowcount != 1:
                raise ValueError(
                    'A later stock movement used the quantity this void returned. '
                    'The receipt was not restored.'
                )
            db.execute("UPDATE cost_layer_uses SET reversed=0 WHERE id=?", (use['id'],))

    def get_consumption(self, consumption_id: int) -> dict:
        db = _db()
        try:
            cons = _row(db.execute("""
                SELECT sc.*, d.name as department_name
                FROM stock_consumptions sc
                LEFT JOIN departments d ON d.id = sc.department_id
                WHERE sc.id=?
            """, (consumption_id,)))
            if not cons:
                return {}
            cons['items'] = _rows(db.execute(
                "SELECT sci.id, sci.consumption_id, sci.product_id, sci.product_name, "
                "sci.quantity, sci.unit_cost, sci.total_cost, sci.selling_price, "
                "sci.stock_before, sci.stock_after, p.sku, p.barcode, "
                "COALESCE(NULLIF(sci.unit, ''), p.unit, 'pcs') AS unit "
                "FROM stock_consumption_items sci "
                "LEFT JOIN products p ON p.id = sci.product_id "
                "WHERE sci.consumption_id=? ORDER BY sci.id",
                (consumption_id,)
            ))
            first_before = {}
            for move in db.execute(
                "SELECT product_id, qty_before FROM stock_movements "
                "WHERE reference=? AND movement_type='INTERNAL_USE' ORDER BY id",
                (cons.get('reference_no'),),
            ).fetchall():
                try:
                    pid = int(move['product_id'] or 0)
                except (TypeError, ValueError):
                    continue
                if pid and pid not in first_before and move['qty_before'] is not None:
                    first_before[pid] = float(move['qty_before'])
            for item in cons['items']:
                if item.get('stock_before') is None:
                    try:
                        pid = int(item.get('product_id') or 0)
                    except (TypeError, ValueError):
                        pid = 0
                    if pid in first_before:
                        item['stock_before'] = first_before[pid]
                        item['stock_after'] = round(first_before[pid] - float(item.get('quantity') or 0), 4)
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            cons['revisions'] = _rows(db.execute(
                "SELECT id, reason, before_json, after_json, edited_by_name, created_at "
                "FROM stock_consumption_revisions WHERE consumption_id=? ORDER BY id",
                (consumption_id,),
            )) if 'stock_consumption_revisions' in tables else []
            cons['void_requested'] = int(consumption_id) in self._pending_consumption_void_ids(db)
            return cons
        finally:
            db.close()

    def _pending_consumption_void_ids(self, db) -> set:
        try:
            open_rows = db.execute(
                "SELECT meta_json FROM cc_approvals "
                "WHERE type='consumption_void' AND status IN ('pending','escalated','executing')"
            ).fetchall()
        except Exception:
            return set()
        found = set()
        for open_row in open_rows:
            try:
                meta = json.loads(open_row['meta_json'] or '{}')
            except (TypeError, json.JSONDecodeError):
                meta = {}
            if not isinstance(meta, dict):
                continue
            try:
                found.add(int(meta.get('consumption_id') or 0))
            except (TypeError, ValueError):
                continue
        found.discard(0)
        return found

    def get_consumptions(self, start=None, end=None, department_id=None,
                         reason=None, include_voided=True, limit=500) -> list:
        start = start or str(date.today())
        end = end or str(date.today())
        db = _db()
        try:
            sql = """
                SELECT sc.*, d.name as department_name,
                       (SELECT COUNT(*) FROM stock_consumption_items sci
                        WHERE sci.consumption_id=sc.id) as item_count
                FROM stock_consumptions sc
                LEFT JOIN departments d ON d.id = sc.department_id
                WHERE date(sc.date) BETWEEN ? AND ?
            """
            params = [start, end]
            if department_id:
                sql += " AND sc.department_id=?"
                params.append(department_id)
            if reason:
                sql += " AND (sc.reason=? OR sc.reason LIKE ?)"
                params.append(reason)
                params.append(str(reason) + ':%')
            if not include_voided:
                sql += " AND COALESCE(sc.voided,0)=0"
            sql += " ORDER BY sc.date DESC, sc.id DESC LIMIT ?"
            params.append(int(limit))
            rows = _rows(db.execute(sql, params))
            pending = self._pending_consumption_void_ids(db)
            for row in rows:
                try:
                    row['void_requested'] = int(row.get('id') or 0) in pending
                except (TypeError, ValueError):
                    row['void_requested'] = False
            return rows
        finally:
            db.close()

    def get_consumption_report(self, start: str, end: str, department_id=None,
                               user_id=None, product_id=None, reason=None,
                               include_voided=False) -> dict:
        """Line-level internal consumption report with footer totals."""
        db = _db()
        try:
            sql = """
                SELECT sc.id as consumption_id, sc.reference_no, sc.date, sc.reason,
                       sc.notes, sc.taken_by, sc.created_by_name, sc.created_at,
                       sc.voided, sc.void_reason, sc.voided_by_name, sc.voided_at,
                       d.name as department_name,
                       sci.product_id, sci.product_name, sci.quantity,
                       sci.unit_cost, sci.total_cost
                FROM stock_consumption_items sci
                JOIN stock_consumptions sc ON sc.id = sci.consumption_id
                LEFT JOIN departments d ON d.id = sc.department_id
                WHERE date(sc.date) BETWEEN ? AND ?
            """
            params = [start, end]
            if not include_voided:
                sql += " AND COALESCE(sc.voided,0)=0"
            if department_id:
                sql += " AND sc.department_id=?"
                params.append(department_id)
            if user_id:
                sql += " AND sc.created_by=?"
                params.append(user_id)
            if product_id:
                sql += " AND sci.product_id=?"
                params.append(product_id)
            if reason:
                sql += " AND sc.reason=?"
                params.append(reason)
            sql += " ORDER BY sc.date DESC, sc.reference_no, sci.id"

            rows = _rows(db.execute(sql, params))
            total_qty = sum(float(r.get('quantity') or 0) for r in rows)
            total_cost = sum(float(r.get('total_cost') or 0) for r in rows)
            # Distinct consumptions / products
            cons_ids = {r['consumption_id'] for r in rows}
            voided = db.execute(
                "SELECT COUNT(*) FROM stock_consumptions "
                "WHERE date(date) BETWEEN ? AND ? AND COALESCE(voided,0)=1",
                (start, end),
            ).fetchone()[0]
            return {
                'rows': rows,
                'totals': {
                    'line_count': len(rows),
                    'consumption_count': len(cons_ids),
                    'total_qty': round(total_qty, 4),
                    'total_cost': round(total_cost, 2),
                    'voided_count': int(voided or 0),
                },
            }
        finally:
            db.close()

    def get_consumption_today_summary(self, start=None, end=None) -> dict:
        today = str(date.today())
        range_start = str(start or today)[:10]
        range_end = str(end or range_start)[:10]
        db = _db()
        try:
            hdr = _row(db.execute("""
                SELECT COUNT(*) as consumption_count,
                       COALESCE(SUM(total_cost),0) as total_cost
                FROM stock_consumptions
                WHERE date(date) BETWEEN ? AND ? AND COALESCE(voided,0)=0
            """, (range_start, range_end)))
            items = _row(db.execute("""
                SELECT COALESCE(SUM(sci.quantity),0) as item_qty,
                       COUNT(sci.id) as line_count
                FROM stock_consumption_items sci
                JOIN stock_consumptions sc ON sc.id = sci.consumption_id
                WHERE date(sc.date) BETWEEN ? AND ? AND COALESCE(sc.voided,0)=0
            """, (range_start, range_end)))
            return {
                'consumption_count': int((hdr or {}).get('consumption_count') or 0),
                'total_cost': float((hdr or {}).get('total_cost') or 0),
                'item_qty': float((items or {}).get('item_qty') or 0),
                'line_count': int((items or {}).get('line_count') or 0),
            }
        finally:
            db.close()

    # ── ACCOUNTING ──────────────────────────────────────────────────────────────

    def _acc_perm(self, action: str) -> bool:
        """Granular accounting permissions by role."""
        from desktop.utils.security import client_actor, has_permission
        return has_permission(client_actor(self), action)

    def accounting_dashboard(self) -> dict:
        if not self._acc_perm('accounting.view'):
            return {'error': 'Insufficient permissions'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import dashboard_kpis
            return dashboard_kpis(db)
        finally:
            db.close()

    def accounting_accounts(self, active_only=True) -> list:
        if not self._acc_perm('accounting.view'):
            return []
        db = _db()
        try:
            from desktop.utils.accounting_engine import list_accounts
            return list_accounts(db, active_only=active_only)
        finally:
            db.close()

    def accounting_save_account(self, data: dict) -> dict:
        if not self._acc_perm('accounting.edit_accounts'):
            return {'error': 'Insufficient permissions to edit accounts'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import upsert_account
            r = upsert_account(db, data, user_id=self._user_id,
                               username=self._username or '')
            db.commit()
            return r
        except Exception as e:
            db.rollback()
            return {'error': str(e)}
        finally:
            db.close()

    def accounting_delete_account(self, code: str) -> dict:
        if not self._acc_perm('accounting.edit_accounts'):
            return {'error': 'Insufficient permissions'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import soft_delete_account
            r = soft_delete_account(db, code, user_id=self._user_id,
                                    username=self._username or '')
            db.commit()
            return r
        except Exception as e:
            db.rollback()
            return {'error': str(e)}
        finally:
            db.close()

    def accounting_journals(self, start=None, end=None, source_module=None) -> list:
        if not self._acc_perm('accounting.view'):
            return []
        db = _db()
        try:
            from desktop.utils.accounting_engine import list_journals
            return list_journals(db, start=start, end=end,
                                 source_module=source_module)
        finally:
            db.close()

    def accounting_journal(self, journal_id: int) -> dict:
        if not self._acc_perm('accounting.view'):
            return {'error': 'Insufficient permissions'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import get_journal
            return get_journal(db, journal_id) or {}
        finally:
            db.close()

    def accounting_post_manual(self, data: dict) -> dict:
        if not self._acc_perm('accounting.create_journal'):
            return {'error': 'Insufficient permissions to create journals'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import post_journal
            r = post_journal(
                db, data.get('lines') or [],
                description=data.get('description') or 'Manual journal',
                entry_date=data.get('entry_date'),
                source_module='manual',
                source_id=data.get('source_id') or f"manual:{datetime.now().timestamp()}",
                entry_type='manual',
                user_id=self._user_id,
                username=self._username or '',
                branch_id=data.get('branch_id'),
            )
            db.commit()
            return r
        except Exception as e:
            db.rollback()
            return {'error': str(e)}
        finally:
            db.close()

    def accounting_reverse(self, journal_id: int, reason: str = '') -> dict:
        if not self._acc_perm('accounting.reverse_journal'):
            return {'error': 'Insufficient permissions to reverse journals'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import reverse_journal
            r = reverse_journal(
                db, journal_id, reason=reason,
                user_id=self._user_id, username=self._username or '',
                source_module='manual',
                source_id=f'rev:{journal_id}',
                entry_type='reversal',
            )
            db.commit()
            return r
        except Exception as e:
            db.rollback()
            return {'error': str(e)}
        finally:
            db.close()

    def accounting_ledger(self, account_code: str, start=None, end=None) -> dict:
        if not self._acc_perm('accounting.view'):
            return {'error': 'Insufficient permissions'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import account_activity
            return account_activity(db, account_code, start, end)
        finally:
            db.close()

    def accounting_trial_balance(self, as_of=None, start=None) -> dict:
        if not self._acc_perm('accounting.view_reports'):
            return {'error': 'Insufficient permissions'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import trial_balance
            return trial_balance(db, as_of=as_of, start=start)
        finally:
            db.close()

    def accounting_pnl(self, start=None, end=None) -> dict:
        if not self._acc_perm('accounting.view_reports'):
            return {'error': 'Insufficient permissions'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import profit_and_loss
            return profit_and_loss(db, start=start, end=end)
        finally:
            db.close()

    def accounting_balance_sheet(self, as_of=None) -> dict:
        if not self._acc_perm('accounting.view_reports'):
            return {'error': 'Insufficient permissions'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import balance_sheet
            return balance_sheet(db, as_of=as_of)
        finally:
            db.close()

    def accounting_cash_book(self, account_code='1000', start=None, end=None) -> dict:
        if not self._acc_perm('accounting.view_reports'):
            return {'error': 'Insufficient permissions'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import cash_book
            return cash_book(db, account_code, start, end)
        finally:
            db.close()

    def accounting_ar_aging(self) -> dict:
        if not self._acc_perm('accounting.view_reports'):
            return {'error': 'Insufficient permissions'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import ar_aging_from_debts
            return ar_aging_from_debts(db)
        finally:
            db.close()

    def accounting_ap_aging(self) -> dict:
        if not self._acc_perm('accounting.view_reports'):
            return {'error': 'Insufficient permissions'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import ap_aging_stub
            return ap_aging_stub(db)
        finally:
            db.close()

    def accounting_expenses(self, start=None, end=None) -> list:
        see_all = self._acc_perm('accounting.view')
        own_only = not see_all and self._acc_perm('accounting.create_expenses')
        if not see_all and not own_only:
            return []
        db = _db()
        try:
            from desktop.utils.accounting_engine import list_expenses
            rows = list_expenses(db, start, end)
            if own_only:
                uid = int(self._user_id or 0)
                rows = [row for row in rows if int(row.get('created_by') or 0) == uid]
            return rows
        finally:
            db.close()

    def accounting_create_expense(self, data: dict) -> dict:
        if not (
            self._acc_perm('accounting.create_expenses')
            or self._acc_perm('accounting.approve_expenses')
        ):
            return {'error': 'Insufficient permissions to record expenses'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import create_expense
            r = create_expense(db, data, user_id=self._user_id,
                               username=self._username or '')
            db.commit()
            return r
        except Exception as e:
            db.rollback()
            return {'error': str(e)}
        finally:
            db.close()

    def accounting_reverse_expense(self, expense_id: int, reason: str) -> dict:
        if not self._acc_perm('accounting.approve_expenses'):
            return {'error': 'Insufficient permissions to reverse expenses'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import reverse_expense
            r = reverse_expense(
                db, int(expense_id), reason,
                user_id=self._user_id, username=self._username or '',
            )
            if r.get('error'):
                db.rollback()
                return r
            db.commit()
            return r
        except Exception as e:
            db.rollback()
            return {'error': str(e)}
        finally:
            db.close()

    def accounting_cash_position(self) -> dict:
        db = _db()
        try:
            from desktop.utils.accounting_engine import cash_position
            return cash_position(db)
        finally:
            db.close()

    def accounting_save_expense_category(self, name: str) -> dict:
        if not (
            self._acc_perm('accounting.create_expenses')
            or self._acc_perm('accounting.approve_expenses')
        ):
            return {'error': 'Insufficient permissions to record expense categories'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import save_expense_category
            r = save_expense_category(db, name)
            db.commit()
            return r
        except Exception as e:
            db.rollback()
            return {'error': str(e)}
        finally:
            db.close()

    def accounting_expense_categories(self) -> list:
        db = _db()
        try:
            from desktop.utils.accounting_engine import list_expense_categories
            return list_expense_categories(db)
        finally:
            db.close()

    def accounting_update_expense(self, expense_id: int, data: dict) -> dict:
        if not self._acc_perm('accounting.approve_expenses'):
            return {'error': 'Insufficient permissions to update expenses'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import update_expense
            r = update_expense(
                db, int(expense_id), data or {},
                user_id=self._user_id, username=self._username or '',
            )
            db.commit()
            return r
        except Exception as e:
            db.rollback()
            return {'error': str(e)}
        finally:
            db.close()

    def accounting_delete_expense(self, expense_id: int, reason: str = '') -> dict:
        if not self._acc_perm('accounting.approve_expenses'):
            return {'error': 'Insufficient permissions to delete expenses'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import delete_expense
            r = delete_expense(
                db, int(expense_id), reason=reason or '',
                user_id=self._user_id, username=self._username or '',
            )
            db.commit()
            return r
        except Exception as e:
            db.rollback()
            return {'error': str(e)}
        finally:
            db.close()

    def accounting_create_transfer(self, data: dict) -> dict:
        if not self._acc_perm('accounting.create_journal'):
            return {'error': 'Insufficient permissions'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import create_transfer
            r = create_transfer(db, data, user_id=self._user_id,
                                username=self._username or '')
            db.commit()
            return r
        except Exception as e:
            db.rollback()
            return {'error': str(e)}
        finally:
            db.close()

    def accounting_periods(self) -> list:
        if not self._acc_perm('accounting.view'):
            return []
        db = _db()
        try:
            from desktop.utils.accounting_engine import list_periods
            return list_periods(db)
        finally:
            db.close()

    def accounting_close_period(self, period_id: int, notes: str = '') -> dict:
        if not self._acc_perm('accounting.close_period'):
            return {'error': 'Insufficient permissions to close periods'}
        db = _db()
        try:
            from desktop.utils.accounting_engine import close_period
            r = close_period(db, period_id, user_id=self._user_id,
                             username=self._username or '', notes=notes)
            db.commit()
            return r
        except Exception as e:
            db.rollback()
            return {'error': str(e)}
        finally:
            db.close()

    def accounting_currency(self) -> str:
        db = _db()
        try:
            from desktop.utils.accounting_engine import get_currency_code
            return get_currency_code(db)
        finally:
            db.close()

    def health(self) -> bool:
        try:
            db = _db()
            db.execute("SELECT 1")
            db.close()
            return True
        except Exception:
            return False
