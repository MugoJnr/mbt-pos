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
import jwt
from datetime import datetime, date

logger = logging.getLogger(__name__)

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

SECRET_KEY = "MBT_POS_SECRET_2024_MUGOBYTE"


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
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    # Always ensure schema exists (safe on existing DBs via CREATE IF NOT EXISTS)
    # Running full migrations on every open caused multi-second stalls / lock storms
    # under rapid POS API sequences (sale → debt → payment).
    if ensure_schema and not _SCHEMA_READY:
        _ensure_schema(conn)
        _SCHEMA_READY = True
    return conn


def _db_light() -> sqlite3.Connection:
    """Connection for audit/helpers — skip schema bootstrap."""
    return _db(ensure_schema=False)


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
    # Seed default admin if missing
    existing = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not existing:
        import os as _os2, hashlib as _hl
        salt = _os2.urandom(16).hex()
        pw_hash = salt + ':' + _hl.sha256((salt + 'admin123').encode()).hexdigest()
        conn.execute(
            "INSERT INTO users (username,password_hash,role,full_name,tab_permissions) VALUES (?,?,?,?,?)",
            ('admin', pw_hash, 'superadmin', 'Shop Owner',
             '["dashboard","sales","inventory","consumption","debt","accounting","reports","notes",'
             '"settings","admin","license","diagnostics","security"]')
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
                'shop_email': '', 'telegram_bot_token': '', 'telegram_chat_id': '',
                'developer_chat_id': '', 'currency_symbol': 'KES', 'tax_rate': '0',
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
    ):
        conn.execute("INSERT OR IGNORE INTO system_settings (key,value) VALUES (?,?)", (k, v))
    for k, v in defaults.items():
        conn.execute("INSERT OR IGNORE INTO system_settings (key,value) VALUES (?,?)", (k, v))
    # Upgrade path: fill empty Telegram fields from build-time deploy config
    try:
        from config.deploy import load_deploy_config
        deploy = load_deploy_config()
        for key in ('telegram_bot_token', 'developer_chat_id'):
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key=?", (key,)
            ).fetchone()
            if not row or not str(row[0] or '').strip():
                val = str(deploy.get(key, '') or '').strip()
                if val:
                    conn.execute(
                        "INSERT OR REPLACE INTO system_settings (key,value) VALUES (?,?)",
                        (key, val),
                    )
    except Exception:
        deploy = {}
        try:
            from config.deploy import load_deploy_config
            deploy = load_deploy_config()
        except Exception:
            pass
        for key in ('telegram_bot_token', 'developer_chat_id'):
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key=?", (key,)
            ).fetchone()
            if not row or not str(row[0] or '').strip():
                val = str(deploy.get(key, '') or '').strip()
                if val:
                    conn.execute(
                        "INSERT OR REPLACE INTO system_settings (key,value) VALUES (?,?)",
                        (key, val),
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
            if fixed != perms:
                conn.execute(
                    "UPDATE users SET tab_permissions=? WHERE id=?",
                    (_json.dumps(fixed), row['id']),
                )
        except Exception:
            pass
    # Seed default departments for internal stock consumption
    for dept_name in (
        'Kitchen', 'Bakery', 'Juice Bar', 'Office',
        'Workshop', 'Manufacturing', 'Maintenance',
    ):
        conn.execute(
            "INSERT OR IGNORE INTO departments (name, active) VALUES (?, 1)",
            (dept_name,),
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
def _next_receipt(conn=None) -> str:
    """Generate the next receipt number for today.
    Accepts an optional open connection so it runs inside the caller's transaction,
    eliminating the race condition when two sales happen in the same second.
    """
    today = datetime.now().strftime('%Y%m%d')
    close_after = conn is None
    db = conn if conn is not None else _db()
    try:
        count = db.execute(
            "SELECT COUNT(*) FROM sales WHERE date(created_at)=date('now')"
        ).fetchone()[0]
        return f"RCP-{today}-{count+1:04d}"
    finally:
        if close_after:
            db.close()


# ── Audit logger ────────────────────────────────────────────────────────────────
def _audit(user_id, username, action, module='system', details=''):
    try:
        db = _db_light()
        db.execute(
            "INSERT INTO audit_log (user_id,username,action,module,details) VALUES (?,?,?,?,?)",
            (user_id, username, action, module, details)
        )
        db.commit(); db.close()
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
        db = _db()
        try:
            # Case-insensitive username match (Admin == admin == ADMIN)
            uname = (username or '').strip()
            user = _row(db.execute(
                "SELECT * FROM users WHERE LOWER(username)=LOWER(?) AND is_active=1",
                (uname,),
            ))
            if not user or not _check_pw(password, user['password_hash']):
                return {'error': 'Invalid credentials'}

            db.execute("UPDATE users SET last_login=? WHERE id=?",
                       (datetime.now().isoformat(), user['id']))
            db.commit()

            import time
            token = jwt.encode({
                'user_id':  user['id'],
                'username': user['username'],
                'role':     user['role'],
                'exp':      time.time() + 86400 * 7,
            }, SECRET_KEY, algorithm='HS256')

            perms = json.loads(user.get('tab_permissions') or '[]')
            result = {
                'token': token,
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

    # ── SETTINGS ────────────────────────────────────────────────────────────────

    def get_settings(self) -> dict:
        db = _db()
        try:
            rows = db.execute("SELECT key, value FROM system_settings").fetchall()
            return {r['key']: r['value'] for r in rows}
        finally:
            db.close()

    def update_settings(self, data: dict) -> dict:
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
                "tab_permissions,created_at,last_login FROM users"
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
                if new_role != target['role']:
                    return {'error': 'Only the shop owner can change a Super Admin account.'}
                if 'tab_permissions' in data:
                    return {'error': 'Only the shop owner can change a Super Admin account.'}
                if data.get('is_active') == 0:
                    return {'error': 'Only the shop owner can deactivate a Super Admin account.'}
            fields, values = [], []
            for field in ('role','full_name','email','is_active'):
                if field in data:
                    fields.append(f"{field}=?"); values.append(data[field])
            if 'tab_permissions' in data:
                fields.append("tab_permissions=?")
                values.append(json.dumps(
                    sanitize_tab_permissions(new_role, data['tab_permissions'])
                ))
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
        if not is_superadmin_role(self._role or ''):
            return {'error': 'Super Admin only'}
        if uid == self._user_id:
            return {'error': 'You cannot deactivate your own account.'}
        db = _db()
        try:
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
            return _rows(db.execute(
                "SELECT * FROM products WHERE is_active=1 ORDER BY name"
            ))
        finally:
            db.close()

    def create_product(self, data: dict) -> dict:
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
            db.commit()
            _audit(self._user_id, self._username, 'CREATE_PRODUCT', 'inventory',
                   f"name={name} stock={initial_stock}")
            result = {'success': True, 'id': pid}
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

    def update_product(self, pid: int, data: dict, pin_verified=False) -> dict:
        """
        Update a product.
        SECURITY: Stock changes require either:
          - pin_verified=True (called after PIN check), OR
          - caller is admin/superadmin (they use adjust_stock via UI with PIN)
        Cashiers can never change stock regardless.
        """
        db = _db()
        try:
            caller_role = getattr(self, '_role', self._role if hasattr(self, '_role') else 'cashier')
            is_privileged = caller_role in ('admin', 'superadmin')

            # Block direct stock manipulation from cashiers always
            if 'stock' in data and not pin_verified and not is_privileged:
                _audit(self._user_id, self._username,
                       'STOCK_ADJUST_BLOCKED', 'inventory',
                       f"pid={pid} attempted_stock={data['stock']} role={caller_role}")
                return {'error': 'Stock adjustment requires Super-Admin PIN.'}

            # Get current values for audit trail
            old = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()

            fields, values = [], []
            for field in ('name','sku','category','price','cost_price',
                          'min_stock','unit','barcode','is_active'):
                if field in data:
                    fields.append(f"{field}=?"); values.append(data[field])

            # Stock adjustment — only reaches here if pin_verified=True
            if 'stock' in data and pin_verified:
                old_stock = round(float((old['stock'] if old else 0) or 0), 4)
                new_stock  = round(float(data['stock']), 4)
                qty_change = round(new_stock - old_stock, 4)
                fields.append("stock=?"); values.append(new_stock)
                # Mandatory movement log
                db.execute(
                    "INSERT INTO stock_movements "
                    "(product_id,product_name,movement_type,qty_before,qty_change,"
                    "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (pid, old['name'] if old else str(pid), 'MANUAL_ADJUST',
                     old_stock, qty_change, new_stock,
                     f"EDIT_pid={pid}",
                     data.get('adjust_reason', 'Manual stock correction by superadmin'),
                     self._user_id, self._username or 'system')
                )

            if fields:
                fields.append("updated_at=?"); values.append(datetime.now().isoformat())
                values.append(pid)
                db.execute(f"UPDATE products SET {','.join(fields)} WHERE id=?", values)
                db.commit()

            _audit(self._user_id, self._username, 'UPDATE_PRODUCT', 'inventory',
                   f"pid={pid} fields={list(data.keys())} pin_verified={pin_verified}")
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

    def adjust_stock(self, pid: int, new_qty, reason: str) -> dict:
        """
        Superadmin-only direct stock adjustment.
        Caller MUST have verified PIN before calling this.
        Supports decimal quantities (e.g. 89.75 after quarter sales).
        """
        if self._role != 'superadmin':
            return {'error': 'Only Super-Admin can adjust stock quantities.'}
        new_qty = round(float(new_qty), 4)
        db = _db()
        try:
            row = db.execute(
                "SELECT id, name, stock FROM products WHERE id=?", (pid,)
            ).fetchone()
            if not row:
                return {'error': 'Product not found'}
            old_stock  = round(float(row['stock'] or 0), 4)
            qty_change = round(new_qty - old_stock, 4)
            db.execute("UPDATE products SET stock=?, updated_at=? WHERE id=?",
                       (new_qty, datetime.now().isoformat(), pid))
            db.execute(
                "INSERT INTO stock_movements "
                "(product_id,product_name,movement_type,qty_before,qty_change,"
                "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, row['name'], 'SUPERADMIN_ADJUST',
                 old_stock, qty_change, new_qty,
                 f"ADJUST_pid={pid}", reason,
                 self._user_id, self._username or 'superadmin')
            )
            mov_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            try:
                cost_row = db.execute(
                    "SELECT cost_price FROM products WHERE id=?", (pid,)
                ).fetchone()
                unit_cost = float(cost_row['cost_price'] or 0) if cost_row else 0
                from desktop.utils.accounting_hooks import post_stock_adjust_journal
                post_stock_adjust_journal(
                    db, product_id=pid, product_name=row['name'],
                    qty_change=qty_change, unit_cost=unit_cost, reason=reason,
                    movement_id=mov_id, user_id=self._user_id,
                    username=self._username or 'superadmin', safe=True)
            except Exception as _je:
                logger.error('stock adjust accounting: %s', _je, exc_info=True)
            db.commit()
            _audit(self._user_id, self._username,
                   'STOCK_ADJUSTED', 'inventory',
                   f"pid={pid} name={row['name']} {old_stock}→{new_qty} reason={reason}")
            return {'success': True, 'old_stock': old_stock, 'new_stock': new_qty}
        finally:
            db.close()

    def delete_product(self, pid: int) -> dict:
        db = _db()
        try:
            db.execute("UPDATE products SET is_active=0 WHERE id=?", (pid,))
            db.commit()
            return {'success': True}
        finally:
            db.close()

    # ── SALES ─────────────────────────────────────────────────────────────────────

    def get_sales(self, start=None, end=None) -> list:
        start = start or str(date.today())
        end   = end   or str(date.today())
        db = _db()
        try:
            return _rows(db.execute(
                "SELECT s.*,GROUP_CONCAT(si.product_name||' x'||si.quantity) as items_summary"
                " FROM sales s LEFT JOIN sale_items si ON s.id=si.sale_id"
                " WHERE date(s.created_at) BETWEEN ? AND ?"
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
        start = start or str(date.today())
        end = end or str(date.today())
        db = _db()
        try:
            status_clause = "" if include_voided else " AND s.status='completed' "
            return _rows(db.execute(f"""
                SELECT si.*,
                       s.receipt_number, s.created_at AS sale_created_at,
                       s.cashier_name, s.payment_method, s.status AS sale_status,
                       s.id AS sale_id
                FROM sale_items si
                JOIN sales s ON si.sale_id = s.id
                WHERE date(s.created_at) BETWEEN ? AND ?
                {status_clause}
                ORDER BY s.created_at DESC, si.id ASC
            """, (start, end)))
        finally:
            db.close()

    def create_sale(self, data: dict) -> dict:
        items = data.get('items') or []
        if not items:
            return {'error': 'Cart is empty — add at least one product before charging.'}
        db = _db()
        try:
            db.execute("BEGIN IMMEDIATE")
            # Allow sale line items even if a product was later removed from inventory.
            db.execute("PRAGMA foreign_keys=OFF")

            rn = _next_receipt(db)          # pass connection — avoids race condition
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
            if electronic_paid > 0.009 and emethod and 'split:' not in notes.lower():
                cash_bit = round(float(data.get('cash_paid') or (amount_paid - electronic_paid)), 2)
                notes = (
                    notes + f' | Split: {emethod} {electronic_paid:,.2f} + Cash {cash_bit:,.2f}'
                ).strip(' |')

            db.execute(
                "INSERT INTO sales (receipt_number,cashier_id,cashier_name,subtotal,"
                "discount,tax,total,payment_method,amount_paid,change_amount,notes,mpesa_ref,"
                "credit_applied,customer_id,variance_handling,"
                "original_total,cash_rounding_adj,electronic_paid)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                 electronic_paid)
            )
            sale_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

            for item in data.get('items', []):
                pid = item.get('product_id')
                db.execute(
                    "INSERT INTO sale_items"
                    " (sale_id,product_id,product_name,sku,quantity,unit_price,discount,total)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (sale_id,
                     pid,
                     item.get('product_name', ''),
                     item.get('sku', '') or '',
                     float(item.get('quantity') or 1),
                     float(item.get('unit_price') or 0),
                     float(item.get('discount') or 0),
                     float(item.get('total') or 0))
                )
                # Stock enforcement — block sale if insufficient stock
                if pid:
                    prod_row = db.execute(
                        "SELECT id, name, stock FROM products WHERE id=?", (pid,)
                    ).fetchone()
                    if prod_row:
                        qty_requested = float(item.get('quantity') or 1)
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
                    'created_at':     datetime.now().isoformat()
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
            db.commit()
            _audit(self._user_id, self._username or 'staff',
                   'CREATE_SALE', 'sales',
                   f"receipt={rn} total={total} original={original_total} "
                   f"rounding={cash_rounding_adj} paid={amount_paid} "
                   f"credit={credit_applied} variance={variance_handling or 'none'}")
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
                    f"misc={variance_result.get('misc_amount')}"
                )
            out = {'success': True, 'receipt_number': rn, 'sale_id': sale_id,
                   'original_total': original_total,
                   'cash_rounding_adj': cash_rounding_adj,
                   'total': total}
            if wallet_balance_after is not None:
                out['wallet_balance'] = wallet_balance_after
            if variance_result:
                out['variance'] = variance_result
            return out

        except Exception as e:
            try: db.rollback()
            except Exception: pass
            logger.error(f"create_sale failed: {e}", exc_info=True)
            raise   # re-raise so the UI shows the real error message
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
        tip = transport = deposit = advance = change_ret = misc = 0.0
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
            }
            return {'rows': rows, 'summary': summary, 'start': start, 'end': end}
        finally:
            db.close()

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
            return sale
        finally:
            db.close()

    # ── SALES EDITING / VOID ─────────────────────────────────────────────────────

    def void_sale(self, sale_id: int, reason: str, *, force_with_payments: bool = False) -> dict:
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
                return {'error': 'Sale not found'}
            if sale['status'] == 'voided':
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

            items = db.execute(
                "SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)
            ).fetchall()

            # Restore stock for each item
            for item in items:
                pid = item['product_id']
                if pid:
                    prod = db.execute(
                        "SELECT id,name,stock FROM products WHERE id=?", (pid,)
                    ).fetchone()
                    if prod:
                        old_stock = prod['stock']
                        new_stock = old_stock + item['quantity']
                        db.execute(
                            "UPDATE products SET stock=?, updated_at=? WHERE id=?",
                            (new_stock, datetime.now().isoformat(), pid)
                        )
                        db.execute(
                            "INSERT INTO stock_movements "
                            "(product_id,product_name,movement_type,qty_before,qty_change,"
                            "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (pid, prod['name'], 'VOID_RESTORE',
                             old_stock, item['quantity'], new_stock,
                             f"VOID_sale={sale_id}",
                             f"Stock restored: sale {sale['receipt_number']} voided",
                             self._user_id, self._username or 'admin')
                        )

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
            return {
                'product': prod,
                'movements': movements,
                'sales': sales,
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
            summary = _row(db.execute("""
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
                                         THEN amount_paid ELSE 0 END),0) as cash_received
                FROM sales WHERE date(created_at) BETWEEN ? AND ?
                AND status='completed'
            """, (start, end)))

            top_products = _rows(db.execute("""
                SELECT si.product_name,
                       SUM(si.quantity) as qty_sold,
                       SUM(si.total)    as revenue,
                       COUNT(si.id)     as transactions
                FROM sale_items si JOIN sales s ON si.sale_id=s.id
                WHERE date(s.created_at) BETWEEN ? AND ?
                  AND s.status='completed'
                GROUP BY si.product_name ORDER BY revenue DESC LIMIT 20
            """, (start, end)))

            by_payment = _rows(db.execute("""
                SELECT payment_method,COUNT(*) as count,SUM(total) as total
                FROM sales WHERE date(created_at) BETWEEN ? AND ?
                AND status='completed' GROUP BY payment_method
            """, (start, end)))

            return {
                'summary':      summary or {},
                'top_products': top_products,
                'by_payment':   by_payment,
            }
        finally:
            db.close()

    def get_sales_trend(self, days: int = 7) -> list:
        """Daily completed revenue for the last N days (inclusive of today)."""
        from datetime import date, timedelta
        days = max(1, min(int(days or 7), 31))
        end = date.today()
        start = end - timedelta(days=days - 1)
        db = _db()
        try:
            rows = _rows(db.execute("""
                SELECT date(created_at) as d,
                       COUNT(*) as txn_count,
                       COALESCE(SUM(total), 0) as revenue
                FROM sales
                WHERE date(created_at) BETWEEN ? AND ?
                  AND LOWER(COALESCE(status,'')) IN ('completed','paid','')
                GROUP BY date(created_at)
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
                "SELECT dp.* FROM debt_payments dp "
                "JOIN debt_invoices di ON dp.invoice_id=di.id "
                "WHERE di.customer_id=? ORDER BY dp.created_at DESC", (cid,)
            ))
            total_owed = sum(i['balance'] for i in invoices if i['status'] not in ('paid','cancelled'))
            total_paid = sum(p['amount'] for p in payments)
            c['invoices'] = invoices
            c['payments'] = payments
            c['total_outstanding'] = total_owed
            c['total_paid'] = total_paid
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

    def create_debt_invoice(self, data: dict) -> dict:
        """
        Create a debt invoice linked to a completed sale.
        Required: customer_id, sale_id, receipt_number, total_amount.
        Orphan debts (no sale / no invoice) are rejected.
        """
        db = _db()
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

            # Prevent duplicate debt for same sale
            existing = _row(db.execute(
                "SELECT id, invoice_number FROM debt_invoices "
                "WHERE sale_id=? AND status NOT IN ('cancelled')",
                (int(sale_id),)
            ))
            if existing:
                return {
                    'error': f'Debt already exists for this sale ({existing.get("invoice_number")}).',
                    'invoice_id': existing.get('id'),
                    'invoice_number': existing.get('invoice_number'),
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

            db.commit()
            _audit(self._user_id, self._username, 'CREATE_INVOICE', 'debt',
                   f"inv={inv_num} sale={sale_id} receipt={receipt_number} "
                   f"customer={cust['name']} total={total} paid={paid} balance={balance}")
            return {
                'success': True,
                'invoice_number': inv_num,
                'invoice_id': inv_id,
                'balance': balance,
                'sale_id': int(sale_id),
                'receipt_number': receipt_number,
            }
        except Exception as e:
            db.rollback()
            logger.error(f"create_debt_invoice: {e}", exc_info=True)
            return {'error': str(e)}
        finally:
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

            balance_before = round(float(inv['balance']), 2)
            if amount > balance_before + 0.009:
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
            dp_cols = {r[1] for r in db.execute("PRAGMA table_info(debt_payments)").fetchall()}
            ref = (payment_reference or '').strip()

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
            db.execute(
                "UPDATE debt_invoices SET amount_paid=?, balance=?, status=?, updated_at=? WHERE id=?",
                (new_paid, balance_after, new_status, datetime.now().isoformat(), invoice_id)
            )
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

    def get_debt_summary(self) -> dict:
        """Dashboard widget data for debt management."""
        db = _db()
        try:
            today = str(date.today())
            outstanding = _row(db.execute(
                "SELECT COALESCE(SUM(balance),0) as total, COUNT(*) as count "
                "FROM debt_invoices WHERE status NOT IN ('paid','cancelled')"
            ))
            overdue = _row(db.execute(
                "SELECT COALESCE(SUM(balance),0) as total, COUNT(*) as count "
                "FROM debt_invoices WHERE status NOT IN ('paid','cancelled') "
                "AND due_date IS NOT NULL AND due_date < date('now')"
            ))
            today_collected = _row(db.execute(
                "SELECT COALESCE(SUM(amount),0) as total, COUNT(*) as count "
                "FROM debt_payments WHERE date(created_at)=?", (today,)
            ))
            credit_today = _row(db.execute(
                "SELECT COALESCE(SUM(balance),0) as total, COUNT(*) as count "
                "FROM debt_invoices WHERE date(created_at)=?", (today,)
            ))
            customers_with_debt = db.execute(
                "SELECT COUNT(DISTINCT customer_id) FROM debt_invoices "
                "WHERE status NOT IN ('paid','cancelled')"
            ).fetchone()[0]
            top_debtors = _rows(db.execute(
                "SELECT customer_name, COALESCE(SUM(balance),0) as total_balance "
                "FROM debt_invoices WHERE status NOT IN ('paid','cancelled') "
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
            for item in items:
                pid = item.get('product_id')
                qty = round(float(item.get('quantity') or 0), 4)
                if not pid or qty <= 0:
                    db.rollback()
                    return {'error': 'Each line needs a product and quantity > 0.'}
                prod = db.execute(
                    "SELECT id, name, stock, cost_price FROM products WHERE id=? AND is_active=1",
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
                total_cost += line_total
                line_rows.append((prod, qty, unit_cost, line_total, stock))

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

            for prod, qty, unit_cost, line_total, old_stock in line_rows:
                new_stock = round(old_stock - qty, 4)
                db.execute(
                    "INSERT INTO stock_consumption_items "
                    "(consumption_id, product_id, product_name, quantity, unit_cost, total_cost) "
                    "VALUES (?,?,?,?,?,?)",
                    (cons_id, prod['id'], prod['name'], qty, unit_cost, line_total)
                )
                db.execute(
                    "UPDATE products SET stock=?, updated_at=? WHERE id=?",
                    (new_stock, now, prod['id'])
                )
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
                    f"qty={qty} reason={reason} notes={notes} device={device}"
                )

            try:
                from desktop.utils.accounting_hooks import post_consumption_journal
                post_consumption_journal(
                    db, cons_id,
                    user_id=self._user_id, username=created_name, safe=True)
            except Exception as _je:
                logger.error('consumption accounting: %s', _je, exc_info=True)

            db.commit()
            _audit(
                self._user_id, created_name, 'CREATE_CONSUMPTION', 'consumption',
                f"ref={ref} dept={dept['name']} total={total_cost:.2f} lines={len(line_rows)} "
                f"reason={reason} notes={notes} device={device} | "
                + '; '.join(audit_lines)
            )
            return {
                'success': True,
                'id': cons_id,
                'reference_no': ref,
                'total_cost': round(total_cost, 2),
            }
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.exception('create_consumption failed')
            return {'error': str(e)}
        finally:
            db.close()

    def void_consumption(self, consumption_id: int, reason: str) -> dict:
        """Soft-void a consumption and restore stock. Admin / superadmin."""
        reason = (reason or '').strip()
        if not reason:
            return {'error': 'Void reason is required.'}
        if self._role not in ('admin', 'superadmin'):
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
                "SELECT * FROM stock_consumption_items WHERE consumption_id=? ORDER BY id",
                (consumption_id,)
            ))
            return cons
        finally:
            db.close()

    def get_consumptions(self, start=None, end=None, department_id=None,
                         include_voided=True, limit=500) -> list:
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
            if not include_voided:
                sql += " AND COALESCE(sc.voided,0)=0"
            sql += " ORDER BY sc.date DESC, sc.id DESC LIMIT ?"
            params.append(int(limit))
            return _rows(db.execute(sql, params))
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
            return {
                'rows': rows,
                'totals': {
                    'line_count': len(rows),
                    'consumption_count': len(cons_ids),
                    'total_qty': round(total_qty, 4),
                    'total_cost': round(total_cost, 2),
                },
            }
        finally:
            db.close()

    def get_consumption_today_summary(self) -> dict:
        today = str(date.today())
        db = _db()
        try:
            hdr = _row(db.execute("""
                SELECT COUNT(*) as consumption_count,
                       COALESCE(SUM(total_cost),0) as total_cost
                FROM stock_consumptions
                WHERE date(date)=? AND COALESCE(voided,0)=0
            """, (today,)))
            items = _row(db.execute("""
                SELECT COALESCE(SUM(sci.quantity),0) as item_qty,
                       COUNT(sci.id) as line_count
                FROM stock_consumption_items sci
                JOIN stock_consumptions sc ON sc.id = sci.consumption_id
                WHERE date(sc.date)=? AND COALESCE(sc.voided,0)=0
            """, (today,)))
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
        from desktop.utils.security import has_permission
        return has_permission({'role': self._role}, action)

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
        if not self._acc_perm('accounting.view'):
            return []
        db = _db()
        try:
            from desktop.utils.accounting_engine import list_expenses
            return list_expenses(db, start, end)
        finally:
            db.close()

    def accounting_create_expense(self, data: dict) -> dict:
        if not self._acc_perm('accounting.approve_expenses'):
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
