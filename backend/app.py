"""
MBT POS System - Backend API
MugoByte Technologies
"""
import os
import sys
import json
import sqlite3
import logging
import secrets
import time
import threading
from datetime import datetime, date
from flask import Flask, request, jsonify, g
from functools import wraps
import jwt
from runtime_security import get_jwt_secret

try:
    from flask_cors import CORS
    _has_cors = True
except ImportError:
    _has_cors = False

def hash_pw(pw):
    """Hash new passwords with bcrypt; legacy hashes remain readable."""
    import bcrypt
    raw = pw.encode() if isinstance(pw, str) else pw
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode()

def check_pw(pw, h):
    """Verify bcrypt or the legacy salt:sha256 format."""
    import hashlib
    h = h.decode() if isinstance(h, bytes) else h
    pw_str = pw.decode() if isinstance(pw, bytes) else pw
    # bcrypt hashes start with $2b$, $2a$, $2y$
    if h.startswith(('$2b$', '$2a$', '$2y$')):
        try:
            import bcrypt as _bc
            return _bc.checkpw(pw_str.encode(), h.encode())
        except Exception:
            return False
    # Custom salt:sha256 format
    parts = h.split(':', 1)
    if len(parts) != 2:
        return False
    salt, stored = parts
    actual = hashlib.sha256((salt + pw_str).encode()).hexdigest()
    return secrets.compare_digest(actual, stored)

app = Flask(__name__)
_login_attempts = {}
_login_attempts_lock = threading.Lock()
_LOGIN_WINDOW_SECONDS = int(os.environ.get('MBT_LOGIN_WINDOW_SECONDS', '300'))
_LOGIN_MAX_ATTEMPTS = int(os.environ.get('MBT_LOGIN_MAX_ATTEMPTS', '10'))


def _login_rate_limited(client_key: str) -> tuple[bool, int]:
    """Small fixed-window limiter for the local/Portal login edge."""
    now = time.time()
    with _login_attempts_lock:
        attempts = [
            ts for ts in _login_attempts.get(client_key, [])
            if now - ts < _LOGIN_WINDOW_SECONDS
        ]
        _login_attempts[client_key] = attempts
        if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
            retry_after = max(1, int(_LOGIN_WINDOW_SECONDS - (now - attempts[0])))
            return True, retry_after
        attempts.append(now)
        return False, 0


def _clear_login_attempts(client_key: str) -> None:
    with _login_attempts_lock:
        _login_attempts.pop(client_key, None)


_ALLOWED_ORIGINS = {
    origin.strip().rstrip('/')
    for origin in os.environ.get(
        'MBT_CORS_ORIGINS',
        'https://portal.mugobyte.com,http://127.0.0.1:5173,http://127.0.0.1:5174',
    ).split(',')
    if origin.strip()
}
if _has_cors:
    CORS(
        app,
        origins=sorted(_ALLOWED_ORIGINS),
        allow_headers=['Content-Type', 'Authorization', 'X-Request-ID'],
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
        supports_credentials=False,
    )
else:
    @app.after_request
    def _cors(r):
        origin = request.headers.get('Origin', '').rstrip('/')
        if origin in _ALLOWED_ORIGINS:
            r.headers['Access-Control-Allow-Origin'] = origin
            r.headers['Vary'] = 'Origin'
        r.headers['Access-Control-Allow-Headers'] = (
            'Content-Type,Authorization,X-Request-ID'
        )
        r.headers['Access-Control-Allow-Methods'] = (
            'GET,POST,PUT,PATCH,DELETE,OPTIONS'
        )
        return r


@app.before_request
def _request_context():
    g.request_id = request.headers.get('X-Request-ID') or secrets.token_hex(12)


@app.after_request
def _security_headers(response):
    response.headers['X-Request-ID'] = getattr(g, 'request_id', '')
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = (
        'camera=(), microphone=(), geolocation=(), payment=()'
    )
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://*.supabase.co; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.is_secure or request.headers.get('X-Forwarded-Proto') == 'https':
        response.headers['Strict-Transport-Security'] = (
            'max-age=63072000; includeSubDomains; preload'
        )
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


BUNDLE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = BUNDLE_DIR  # PyInstaller bundle root (_internal when frozen onedir)
try:
    if BUNDLE_DIR not in sys.path:
        sys.path.insert(0, BUNDLE_DIR)
    from mbt_paths import (
        get_db_path as _get_db_path,
        ensure_data_dirs as _ensure_dirs,
        configure_sqlite_connection,
    )
    DATA_ROOT = _ensure_dirs()
    DB_PATH = _get_db_path()
    CONFIG_PATH = os.path.join(DATA_ROOT, 'config', 'settings.json')
    LOG_PATH = os.path.join(DATA_ROOT, 'logs', 'backend.log')
except Exception:
    DATA_ROOT = BUNDLE_DIR
    DB_PATH = os.path.join(BUNDLE_DIR, 'data', 'mbt_pos.db')
    CONFIG_PATH = os.path.join(BUNDLE_DIR, 'config', 'settings.json')
    LOG_PATH = os.path.join(BUNDLE_DIR, 'logs', 'backend.log')
SECRET_KEY = get_jwt_secret()

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=5.0)
        g.db.row_factory = sqlite3.Row
        configure_sqlite_connection(g.db)
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH, timeout=5.0)
    configure_sqlite_connection(db)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    cur.executescript("""
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
        void_reason TEXT
    );

    CREATE TABLE IF NOT EXISTS stock_consumption_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        consumption_id INTEGER NOT NULL,
        product_id INTEGER,
        product_name TEXT,
        quantity REAL NOT NULL,
        unit_cost REAL NOT NULL,
        total_cost REAL NOT NULL
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

    CREATE TABLE IF NOT EXISTS customer_wallet (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL UNIQUE,
        balance REAL NOT NULL DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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

    for dept_name in (
        'Kitchen', 'Bakery', 'Juice Bar', 'Office',
        'Workshop', 'Manufacturing', 'Maintenance',
    ):
        cur.execute(
            "INSERT OR IGNORE INTO departments (name, active) VALUES (?, 1)",
            (dept_name,),
        )

    # Production never creates a known default credential. API-only development
    # may opt in with an explicit, non-empty bootstrap password.
    bootstrap_password = os.environ.get('MBT_BOOTSTRAP_ADMIN_PASSWORD', '')
    existing = cur.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not existing and bootstrap_password:
        from roles import default_tab_permissions
        pw_hash = hash_pw(bootstrap_password)
        cur.execute("""INSERT INTO users (username, password_hash, role, full_name, tab_permissions)
                       VALUES (?, ?, ?, ?, ?)""",
                    ('admin', pw_hash, 'superadmin', 'Shop Owner',
                     json.dumps(default_tab_permissions('superadmin'))))

    # Default settings
    defaults = {
        'shop_name': 'My Shop',
        'shop_address': '',
        'shop_phone': '',
        'shop_email': '',
        'currency_symbol': 'KES',
        'tax_rate': '0',
        'receipt_footer': 'Thank you for shopping with us!',
        'theme': 'dark',
        'sync_interval': '30',
        'printer_name': '',
        'printer_port': 'USB',
        'auto_print': '1',
        'auto_report_daily': '1',
        'auto_report_weekly': '1',
        'auto_report_interval_hours': '4',
        'auto_db_backup': '1',
        'auto_db_backup_interval_hours': '24',
    }
    for k, v in defaults.items():
        cur.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", (k, v))

    cols = {r[1] for r in cur.execute("PRAGMA table_info(sales)").fetchall()}
    if 'status' not in cols:
        cur.execute("ALTER TABLE sales ADD COLUMN status TEXT DEFAULT 'completed'")
        cur.execute(
            "UPDATE sales SET status='completed' WHERE status IS NULL OR status=''"
        )
    if 'mpesa_ref' not in cols:
        cur.execute("ALTER TABLE sales ADD COLUMN mpesa_ref TEXT")
    sales_cols = {r[1] for r in cur.execute("PRAGMA table_info(sales)").fetchall()}
    if 'credit_applied' not in sales_cols:
        cur.execute("ALTER TABLE sales ADD COLUMN credit_applied REAL DEFAULT 0")
    if 'customer_id' not in sales_cols:
        cur.execute("ALTER TABLE sales ADD COLUMN customer_id INTEGER")
    if 'variance_handling' not in sales_cols:
        cur.execute("ALTER TABLE sales ADD COLUMN variance_handling TEXT")
    if 'original_total' not in sales_cols:
        cur.execute("ALTER TABLE sales ADD COLUMN original_total REAL DEFAULT 0")
    if 'cash_rounding_adj' not in sales_cols:
        cur.execute("ALTER TABLE sales ADD COLUMN cash_rounding_adj REAL DEFAULT 0")
    if 'electronic_paid' not in sales_cols:
        cur.execute("ALTER TABLE sales ADD COLUMN electronic_paid REAL DEFAULT 0")

    note_cols = {r[1] for r in cur.execute("PRAGMA table_info(notes)").fetchall()}
    if 'pinned' not in note_cols:
        cur.execute("ALTER TABLE notes ADD COLUMN pinned INTEGER DEFAULT 0")

    cur.execute("""
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
        # POS checkout layout: retail_classic | product_explorer | checkout_pro
        ('pos_checkout_layout', 'product_explorer'),
    ):
        cur.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", (k, v))

    # Category visual management (mirror desktop api_client)
    cur.execute("""
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
    cat_cols = {r[1] for r in cur.execute("PRAGMA table_info(categories)").fetchall()}
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
        if col not in cat_cols:
            try:
                cur.execute(ddl)
            except Exception:
                pass
    try:
        from desktop.utils.category_suggest import suggest_visual_for_category_name as _sug_cat
    except Exception:
        _sug_cat = None
    seed_names = {'General', 'Grocery', 'Pharmacy', 'Electronics', 'Clothing',
                  'Hardware', 'Beverages', 'Beauty'}
    try:
        for row in cur.execute(
            "SELECT DISTINCT category FROM products "
            "WHERE category IS NOT NULL AND TRIM(category) != ''"
        ).fetchall():
            seed_names.add((row[0] or '').strip())
    except Exception:
        pass
    for _cname in sorted(n for n in seed_names if n):
        exists = cur.execute(
            "SELECT id, icon_name FROM categories WHERE LOWER(name)=LOWER(?)",
            (_cname,),
        ).fetchone()
        if exists:
            continue
        vis = _sug_cat(_cname) if _sug_cat else {
            'visual_type': 'icon', 'icon_name': 'generic/general-product',
            'accent_color': '#3B82F6',
        }
        try:
            cur.execute(
                "INSERT INTO categories (name, visual_type, icon_name, accent_color, is_active) "
                "VALUES (?,?,?,?,1)",
                (_cname, vis.get('visual_type', 'icon'),
                 vis.get('icon_name'), vis.get('accent_color', '#3B82F6')),
            )
        except Exception:
            pass

    # Cloud backup sync columns (non-breaking)
    for table in ('products', 'sales', 'customers'):
        try:
            tcols = {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
        except Exception:
            continue
        for col, ddl in (
            ('sync_id', f"ALTER TABLE {table} ADD COLUMN sync_id TEXT"),
            ('sync_status', f"ALTER TABLE {table} ADD COLUMN sync_status TEXT DEFAULT 'local'"),
        ):
            if col not in tcols:
                try:
                    cur.execute(ddl)
                except Exception:
                    pass
        if table == 'customers' and 'updated_at' not in tcols:
            try:
                cur.execute(
                    "ALTER TABLE customers ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP")
            except Exception:
                pass
        if table == 'sales' and 'updated_at' not in tcols:
            try:
                cur.execute(
                    "ALTER TABLE sales ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP")
            except Exception:
                pass
    try:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS cloud_change_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            row_id INTEGER,
            op TEXT NOT NULL,
            payload TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            synced INTEGER DEFAULT 0
        )
        """)
    except Exception:
        pass
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sync_outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        entity_type TEXT NOT NULL,
        row_id TEXT NOT NULL,
        operation TEXT NOT NULL CHECK(operation IN ('upsert','delete')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        processed_at TEXT
    )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_sync_outbox_pending "
        "ON sync_outbox(processed_at, available_at, id)"
    )
    # Triggers make the outbox transactional: domain data and its sync event
    # commit or roll back together. Missing optional tables are skipped.
    sync_tables = {
        'products': 'product',
        'sales': 'sale',
        'sale_items': 'sale_item',
        'customers': 'customer',
        'suppliers': 'supplier',
        'expenses': 'expense',
        'purchases': 'purchase',
        'purchase_items': 'purchase_item',
        'employees': 'employee',
        'users': 'user',
        'branches': 'branch',
        # audit_log intentionally omitted — high volume, not needed for portal analytics
        'system_settings': 'setting',
        'debt_invoices': 'debt_invoice',
        'debt_payments': 'debt_payment',
        'stock_movements': 'stock_movement',
    }
    existing_tables = {
        row[0] for row in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for table_name, entity_type in sync_tables.items():
        if table_name not in existing_tables:
            continue
        columns = {
            row[1] for row in cur.execute(
                f'PRAGMA table_info("{table_name}")'
            ).fetchall()
        }
        row_key_new = 'NEW.id' if 'id' in columns else 'NEW.key'
        row_key_old = 'OLD.id' if 'id' in columns else 'OLD.key'
        for suffix, timing, operation, row_key in (
            ('insert', 'AFTER INSERT', 'upsert', row_key_new),
            ('update', 'AFTER UPDATE', 'upsert', row_key_new),
            ('delete', 'AFTER DELETE', 'delete', row_key_old),
        ):
            trigger_name = f'sync_{table_name}_{suffix}'
            cur.execute(f'''
                CREATE TRIGGER IF NOT EXISTS "{trigger_name}"
                {timing} ON "{table_name}"
                BEGIN
                  INSERT INTO sync_outbox(
                    event_id, entity_type, row_id, operation
                  ) VALUES (
                    lower(hex(randomblob(16))),
                    '{entity_type}',
                    CAST({row_key} AS TEXT),
                    '{operation}'
                  );
                END
            ''')

    db.commit()
    db.close()
    logger.info("Database initialized")


def _resolve_local_identity(token: str):
    """Decode the local Flask JWT. Returns the user row dict or None."""
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id=? AND is_active=1",
                          (data['user_id'],)).fetchone()
        return dict(user) if user else None
    except Exception:
        return None


def _resolve_supabase_identity(token: str):
    """Verify a Supabase JWT (MugoByte Platform cloud auth)."""
    try:
        from backend.cloud_backup.paths import is_cloud_configured, load_cloud_config
        from backend.cloud.net_gate import network_up, mark_network_down
        if not is_cloud_configured():
            return None
        # Never hang Flask auth on offline supabase.co DNS.
        if not network_up(1.0):
            return None
        import requests as _req
        cfg = load_cloud_config()
        r = _req.get(
            f"{(cfg.get('supabase_url') or '').rstrip('/')}/auth/v1/user",
            headers={
                'apikey': cfg.get('anon_key') or '',
                'Authorization': f'Bearer {token}',
            },
            timeout=3,
        )
        if r.status_code >= 400:
            return None
        u = r.json() or {}
        meta = u.get('user_metadata') or {}
        app_meta = u.get('app_metadata') or {}
        return {
            'id': u.get('id'),
            'username': (u.get('email') or '').split('@')[0] or 'cloud',
            'full_name': meta.get('full_name') or meta.get('name') or (u.get('email') or ''),
            'email': u.get('email') or '',
            # Platform roles are server-controlled app metadata.
            # Organization ownership is checked through org_members.
            'role': app_meta.get('platform_role') or 'member',
            'tab_permissions': '[]',
            'is_active': 1,
        }
    except Exception as e:
        try:
            from backend.cloud.net_gate import mark_network_down
            mark_network_down()
        except Exception:
            pass
        logger.debug('Supabase token check: %s', e)
        return None


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({'error': 'Token required'}), 401
        # Identity resolution is kept strictly separate from view execution.
        # Running the view inside the decode try/except turned every view
        # exception (duplicate username, DB error, …) into "Invalid token".
        user = _resolve_local_identity(token)
        provider = 'local'
        if user is None:
            user = _resolve_supabase_identity(token)
            provider = 'supabase'
        if user is None:
            return jsonify({'error': 'Invalid token'}), 401
        g.current_user = user
        g.auth_provider = provider
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.current_user.get('role') not in ('admin', 'superadmin', 'platform_admin'):
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return token_required(decorated)


def _role_is(*roles: str) -> bool:
    return g.current_user.get('role') in roles


def _actor_role() -> str:
    return g.current_user.get('role', 'cashier')


def _user_tab_allowed(tab: str, user=None) -> bool:
    """Mirror desktop navigation, including owner/admin lockout protection."""
    from roles import default_tab_permissions
    user = user or g.current_user
    role = str(user.get('role') or 'cashier').strip().lower()
    if role in ('admin', 'superadmin'):
        return True
    raw = user.get('tab_permissions')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or '[]')
        except Exception:
            raw = []
    if not isinstance(raw, list):
        raw = []
    tabs = set(raw if raw else default_tab_permissions(role))
    return tab in tabs


def _public_settings(rows) -> dict:
    """Return settings safe for browser/HTTP clients."""
    blocked_fragments = (
        'pin', 'password', 'token', 'secret', 'private_key',
        'service_role', 'license_key', 'license_private',
    )
    safe = {}
    for row in rows:
        key = str(row['key'] or '')
        normalized = key.strip().lower()
        if any(fragment in normalized for fragment in blocked_fragments):
            continue
        safe[key] = row['value']
    return safe


def _user_role_guard(target_role: str):
    from roles import can_assign_role
    if not can_assign_role(_actor_role(), target_role):
        return jsonify({'error': 'Only the shop owner (Super Admin) can assign the Super Admin role.'}), 403
    return None


def _load_user(db, uid: int):
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return dict(row) if row else None


def log_action(action, module='system', details=''):
    try:
        db = get_db()
        user = getattr(g, 'current_user', {})
        db.execute("""INSERT INTO audit_log (user_id, username, action, module, details, ip_address)
                      VALUES (?, ?, ?, ?, ?, ?)""",
                   (user.get('id'), user.get('username', 'system'),
                    action, module, details, request.remote_addr))
        db.commit()
    except Exception as e:
        logger.error(f"Audit log error: {e}")


# ── AUTH ──────────────────────────────────────────────────────────────────────

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = data.get('password', '').encode()
    client_key = f"{request.remote_addr or 'unknown'}:{username.lower()}"
    limited, retry_after = _login_rate_limited(client_key)
    if limited:
        response = jsonify({'error': 'Too many login attempts. Try again later.'})
        response.headers['Retry-After'] = str(retry_after)
        return response, 429

    db = get_db()
    # Case-insensitive username (Admin == admin == ADMIN)
    user = db.execute(
        "SELECT * FROM users WHERE LOWER(username)=LOWER(?) AND is_active=1",
        (username,),
    ).fetchone()

    if not user or not check_pw(password.decode() if isinstance(password,bytes) else data.get('password',''), user['password_hash']):
        return jsonify({'error': 'Invalid credentials'}), 401

    _clear_login_attempts(client_key)
    password_text = password.decode() if isinstance(password, bytes) else str(password)
    if not str(user['password_hash']).startswith(('$2b$', '$2a$', '$2y$')):
        db.execute(
            "UPDATE users SET password_hash=?, last_login=? WHERE id=?",
            (hash_pw(password_text), datetime.now().isoformat(), user['id']),
        )
    else:
        db.execute("UPDATE users SET last_login=? WHERE id=?",
                   (datetime.now().isoformat(), user['id']))
    db.commit()

    token = jwt.encode({
        'user_id': user['id'],
        'username': user['username'],
        'role': user['role'],
        'iat': int(time.time()),
        'exp': int(time.time()) + int(os.environ.get('MBT_JWT_TTL_SECONDS', '28800')),
    }, SECRET_KEY, algorithm='HS256')

    perms = json.loads(user['tab_permissions'] or '[]')
    return jsonify({
        'token': token,
        'user': {
            'id': user['id'],
            'username': user['username'],
            'full_name': user['full_name'],
            'role': user['role'],
            'tab_permissions': perms,
        }
    })


@app.route('/api/auth/me', methods=['GET'])
@token_required
def me():
    return jsonify(g.current_user)


# ── USERS ─────────────────────────────────────────────────────────────────────

@app.route('/api/users', methods=['GET'])
@token_required
def list_users():
    if not _role_is('admin', 'superadmin', 'manager'):
        return jsonify({'error': 'Forbidden'}), 403
    db = get_db()
    users = db.execute("""SELECT id, username, full_name, role, email, is_active,
                          tab_permissions, created_at, last_login FROM users""").fetchall()
    return jsonify([dict(u) for u in users])


@app.route('/api/users', methods=['POST'])
@token_required
def create_user():
    if not _role_is('admin', 'superadmin'):
        return jsonify({'error': 'Admin only'}), 403
    from roles import default_tab_permissions, sanitize_tab_permissions
    data = request.json or {}
    new_role = data.get('role', 'cashier')
    err = _user_role_guard(new_role)
    if err:
        return err
    pw_hash = hash_pw(data['password'])
    db = get_db()
    raw_perms = data.get('tab_permissions')
    if raw_perms is None:
        perms = default_tab_permissions(new_role)
    else:
        perms = sanitize_tab_permissions(new_role, raw_perms)
    try:
        db.execute("""INSERT INTO users (username, password_hash, role, full_name, email, tab_permissions)
                      VALUES (?, ?, ?, ?, ?, ?)""",
                   (data['username'], pw_hash, new_role,
                    data.get('full_name'), data.get('email'), json.dumps(perms)))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return jsonify({
            'error': f"Username '{data['username']}' already exists.",
            'code': 'username_taken',
        }), 409
    log_action('CREATE_USER', 'admin', f"Created user: {data['username']} role={new_role}")
    # Flag suspicious privilege creation
    if new_role in ('superadmin', 'admin'):
        try:
            from backend.cloud.platform_service import publish_security_event
            actor = g.current_user.get('username') or g.current_user.get('id')
            publish_security_event(
                None,
                f'Privileged account created: {data["username"]}',
                f'Role={new_role} by {actor}',
                {'username': data['username'], 'role': new_role, 'actor': str(actor), 'event': 'CREATE_USER'},
            )
        except Exception:
            pass
    return jsonify({'success': True})


@app.route('/api/users/<int:uid>', methods=['PUT'])
@token_required
def update_user(uid):
    if not _role_is('admin', 'superadmin'):
        return jsonify({'error': 'Admin only'}), 403
    from roles import sanitize_tab_permissions, is_superadmin_role
    data = request.json or {}
    db = get_db()
    target = _load_user(db, uid)
    if not target:
        return jsonify({'error': 'User not found'}), 404
    new_role = data.get('role', target['role'])
    err = _user_role_guard(new_role)
    if err:
        return err
    actor = _actor_role()
    if not is_superadmin_role(actor) and is_superadmin_role(target['role']):
        if new_role != target['role']:
            return jsonify({'error': 'Only the shop owner can change a Super Admin account.'}), 403
        if 'tab_permissions' in data:
            return jsonify({'error': 'Only the shop owner can change a Super Admin account.'}), 403
        if data.get('is_active') == 0:
            return jsonify({'error': 'Only the shop owner can deactivate a Super Admin account.'}), 403
    fields = []
    values = []
    for field in ('role', 'full_name', 'email', 'is_active'):
        if field in data:
            fields.append(f"{field}=?")
            values.append(data[field])
    if 'tab_permissions' in data:
        fields.append("tab_permissions=?")
        values.append(json.dumps(
            sanitize_tab_permissions(new_role, data['tab_permissions'])
        ))
    if 'password' in data:
        pw_hash = hash_pw(data['password'])
        fields.append("password_hash=?")
        values.append(pw_hash)
    if fields:
        values.append(uid)
        db.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=?", values)
        db.commit()
    role_changed = 'role' in data and data['role'] != target['role']
    elevated = role_changed and data.get('role') in ('admin', 'superadmin')
    log_action('UPDATE_USER', 'admin', f"Updated user id={uid} role={new_role}")
    if elevated or data.get('is_active') == 0:
        try:
            from backend.cloud.platform_service import publish_security_event
            actor_name = g.current_user.get('username') or g.current_user.get('id')
            title = 'User privilege change' if elevated else 'User deactivated'
            publish_security_event(
                None,
                title,
                f'User id={uid} ({target.get("username")}) → role={new_role} by {actor_name}',
                {
                    'user_id': uid,
                    'username': target.get('username'),
                    'old_role': target.get('role'),
                    'new_role': new_role,
                    'actor': str(actor_name),
                    'event': 'UPDATE_USER',
                },
            )
        except Exception:
            pass
    return jsonify({'success': True})


@app.route('/api/users/<int:uid>', methods=['DELETE'])
@token_required
def delete_user(uid):
    if not _role_is('superadmin'):
        return jsonify({'error': 'Super Admin only'}), 403
    db = get_db()
    target = _load_user(db, uid)
    if target and target.get('id') == g.current_user.get('id'):
        return jsonify({'error': 'You cannot deactivate your own account.'}), 400
    db.execute("UPDATE users SET is_active=0 WHERE id=?", (uid,))
    db.commit()
    log_action('DELETE_USER', 'admin', f"Deactivated user id={uid}")
    return jsonify({'success': True})


# ── PRODUCTS ──────────────────────────────────────────────────────────────────

@app.route('/api/products', methods=['GET'])
@token_required
def list_products():
    db = get_db()
    products = db.execute("SELECT * FROM products WHERE is_active=1 ORDER BY name").fetchall()
    return jsonify([dict(p) for p in products])


@app.route('/api/products', methods=['POST'])
@token_required
def create_product():
    if not _role_is('manager', 'admin', 'superadmin'):
        return jsonify({'error': 'Inventory Manager access required'}), 403
    data = request.json or {}
    from desktop.utils.api_client import APIClient
    api = APIClient()
    api._role = g.current_user.get('role')
    api._user_id = g.current_user.get('id')
    api._username = (
        g.current_user.get('full_name') or g.current_user.get('username')
    )
    result = api.create_product(data)
    return jsonify(result), (200 if result.get('success') else 400)


@app.route('/api/products/<int:pid>', methods=['PUT'])
@token_required
def update_product(pid):
    if not _role_is('manager', 'admin', 'superadmin'):
        return jsonify({'error': 'Inventory Manager access required'}), 403
    data = request.json or {}
    if 'stock' in data:
        log_action(
            'STOCK_ADJUST_BLOCKED', 'inventory',
            f"Product edit attempted stock change: pid={pid}",
        )
        return jsonify({
            'error': (
                'Stock cannot be changed from Edit Product. '
                'Use the protected Adjust Stock action.'
            )
        }), 403
    from desktop.utils.api_client import APIClient
    api = APIClient()
    api._role = g.current_user.get('role')
    api._user_id = g.current_user.get('id')
    api._username = (
        g.current_user.get('full_name') or g.current_user.get('username')
    )
    result = api.update_product(pid, data)
    return jsonify(result), (200 if result.get('success') else 400)


@app.route('/api/products/<int:pid>', methods=['DELETE'])
@token_required
def delete_product(pid):
    if not _role_is('manager', 'admin', 'superadmin'):
        return jsonify({'error': 'Inventory Manager access required'}), 403
    from desktop.utils.api_client import APIClient
    api = APIClient()
    api._role = g.current_user.get('role')
    api._user_id = g.current_user.get('id')
    api._username = (
        g.current_user.get('full_name') or g.current_user.get('username')
    )
    result = api.delete_product(pid)
    return jsonify(result), (200 if result.get('success') else 400)


# ── SALES ─────────────────────────────────────────────────────────────────────

@app.route('/api/sales', methods=['GET'])
@token_required
def list_sales():
    db = get_db()
    start = request.args.get('start', str(date.today()))
    end = request.args.get('end', str(date.today()))
    where = "date(s.created_at) BETWEEN ? AND ?"
    params = [start, end]
    if _actor_role() == 'cashier':
        # Cashier HTTP history is limited to receipts created by that account.
        where += " AND s.cashier_id=?"
        params.append(g.current_user.get('id'))
    sales = db.execute(f"""SELECT s.*, GROUP_CONCAT(si.product_name || ' x' || si.quantity) as items_summary
                           FROM sales s LEFT JOIN sale_items si ON s.id = si.sale_id
                           WHERE {where}
                           GROUP BY s.id ORDER BY s.created_at DESC""",
                       params).fetchall()
    return jsonify([dict(s) for s in sales])


@app.route('/api/sales', methods=['POST'])
@token_required
def create_sale():
    if not _role_is('cashier', 'manager', 'admin', 'superadmin'):
        return jsonify({'error': 'Sales access required'}), 403
    data = request.json or {}
    user = g.current_user
    from desktop.utils.api_client import APIClient
    api = APIClient()
    api._role = user.get('role')
    api._user_id = user.get('id')
    api._username = user.get('full_name') or user.get('username')
    result = api.create_sale(data)
    return jsonify(result), (200 if result.get('success') else 400)


@app.route('/api/sales/<int:sale_id>', methods=['GET'])
@token_required
def get_sale(sale_id):
    db = get_db()
    sale = db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
    if not sale:
        return jsonify({'error': 'Not found'}), 404
    if _actor_role() == 'cashier' and sale['cashier_id'] != g.current_user.get('id'):
        return jsonify({'error': 'Forbidden'}), 403
    items = db.execute("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)).fetchall()
    result = dict(sale)
    result['items'] = [dict(i) for i in items]
    return jsonify(result)


# ── REPORTS ───────────────────────────────────────────────────────────────────

@app.route('/api/reports/summary', methods=['GET'])
@token_required
def sales_summary():
    # A cashier has no reports tab, but the web dashboard needs their own
    # takings or every KPI renders as zero. They get the same aggregate shape
    # restricted to receipts they created — never shop-wide figures, and never
    # the richer /api/reports/data feed.
    full_access = _user_tab_allowed('reports')
    own_only = False
    if not full_access:
        if not _user_tab_allowed('sales'):
            return jsonify({'error': 'Reports access required'}), 403
        own_only = True

    db = get_db()
    start = request.args.get('start', str(date.today()))
    end = request.args.get('end', str(date.today()))

    scope = ''
    params = [start, end]
    if own_only:
        scope = ' AND {alias}cashier_id=?'
        params.append(g.current_user.get('id'))

    sales_scope = scope.format(alias='') if scope else ''
    joined_scope = scope.format(alias='s.') if scope else ''

    summary = db.execute(f"""
        SELECT
            COUNT(*) as total_transactions,
            COALESCE(SUM(total), 0) as total_revenue,
            COALESCE(AVG(total), 0) as avg_transaction,
            COALESCE(SUM(discount), 0) as total_discounts,
            COALESCE(SUM(tax), 0) as total_tax
        FROM sales
        WHERE date(created_at) BETWEEN ? AND ? AND status='completed'{sales_scope}
    """, params).fetchone()

    top_products = db.execute(f"""
        SELECT si.product_name, SUM(si.quantity) as qty_sold, SUM(si.total) as revenue
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        WHERE date(s.created_at) BETWEEN ? AND ? AND s.status='completed'{joined_scope}
        GROUP BY si.product_name ORDER BY revenue DESC LIMIT 10
    """, params).fetchall()

    by_payment = db.execute(f"""
        SELECT payment_method, COUNT(*) as count, SUM(total) as total
        FROM sales
        WHERE date(created_at) BETWEEN ? AND ? AND status='completed'{sales_scope}
        GROUP BY payment_method
    """, params).fetchall()

    hourly = db.execute(f"""
        SELECT strftime('%H', created_at) as hour, COUNT(*) as count, SUM(total) as total
        FROM sales
        WHERE date(created_at) BETWEEN ? AND ? AND status='completed'{sales_scope}
        GROUP BY hour ORDER BY hour
    """, params).fetchall()

    return jsonify({
        'scope': 'own' if own_only else 'all',
        'summary': dict(summary),
        'top_products': [dict(p) for p in top_products],
        'by_payment': [dict(p) for p in by_payment],
        'hourly': [dict(h) for h in hourly],
    })


# ── SETTINGS ──────────────────────────────────────────────────────────────────

@app.route('/api/settings', methods=['GET'])
@token_required
def get_settings():
    db = get_db()
    rows = db.execute("SELECT key, value FROM system_settings").fetchall()
    return jsonify(_public_settings(rows))


@app.route('/api/settings', methods=['PUT'])
@token_required
def update_settings():
    if not _role_is('admin', 'superadmin'):
        return jsonify({'error': 'Admin only'}), 403
    data = request.json or {}
    db = get_db()
    for k, v in data.items():
        db.execute("INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)",
                   (k, str(v), datetime.now().isoformat()))
    db.commit()
    log_action('UPDATE_SETTINGS', 'settings', f"Keys: {list(data.keys())}")
    return jsonify({'success': True})


# ── AUDIT LOG ─────────────────────────────────────────────────────────────────

@app.route('/api/audit', methods=['GET'])
@token_required
def get_audit():
    if not _role_is('admin', 'superadmin', 'manager'):
        return jsonify({'error': 'Forbidden'}), 403
    db = get_db()
    logs = db.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 500").fetchall()
    return jsonify([dict(l) for l in logs])


# ── SYNC QUEUE ────────────────────────────────────────────────────────────────

@app.route('/api/sync/pending', methods=['GET'])
@token_required
def pending_sync():
    if not _role_is('admin', 'superadmin'):
        return jsonify({'error': 'Admin access required'}), 403
    db = get_db()
    items = db.execute("SELECT * FROM sync_queue WHERE status='pending' ORDER BY created_at").fetchall()
    return jsonify([dict(i) for i in items])


@app.route('/api/sync/mark-sent', methods=['POST'])
@token_required
def mark_synced():
    if not _role_is('admin', 'superadmin'):
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json or {}
    ids = data.get('ids', [])
    if not isinstance(ids, list) or len(ids) > 1000:
        return jsonify({'error': 'Invalid sync id list'}), 400
    try:
        ids = [int(value) for value in ids]
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid sync id list'}), 400
    db = get_db()
    for sid in ids:
        db.execute("UPDATE sync_queue SET status='sent', synced_at=? WHERE id=?",
                   (datetime.now().isoformat(), sid))
    db.commit()
    return jsonify({'success': True})


# ── NOTES ─────────────────────────────────────────────────────────────────────

def _note_read_scope():
    """(may_read, see_all) for the current actor, from central permissions."""
    from desktop.utils.security import has_permission
    actor = {'role': _actor_role()}
    see_all = has_permission(actor, 'notes.view_all')
    return (see_all or has_permission(actor, 'notes.own')), see_all


def _note_write_scope():
    """(allowed, owner_only) for note mutations — mirrors the desktop API.

    `notes.view_all` alone (viewer) is read-only; `notes.own` grants writes on
    the actor's own notes, and shop admins may mutate every note.
    """
    from desktop.utils.security import has_permission
    from roles import is_shop_admin_role
    role = _actor_role()
    if not has_permission({'role': role}, 'notes.own'):
        return False, True
    return True, not is_shop_admin_role(role)


def _authorize_note(db, nid: int, owner_only: bool):
    """Load the target note and authorize it. Returns (row, error_response)."""
    row = db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    if not row:
        return None, (jsonify({'error': 'Note not found'}), 404)
    if owner_only and row['user_id'] != g.current_user.get('id'):
        return None, (jsonify({'error': 'You can only change your own notes.'}), 403)
    return row, None


@app.route('/api/notes', methods=['GET'])
@token_required
def list_notes():
    may_read, see_all = _note_read_scope()
    if not may_read:
        return jsonify({'error': 'Notes access required'}), 403
    db = get_db()
    order = "ORDER BY COALESCE(pinned,0) DESC, updated_at DESC"
    if see_all:
        notes = db.execute(f"SELECT * FROM notes {order}").fetchall()
    else:
        notes = db.execute(
            f"SELECT * FROM notes WHERE user_id IS ? {order}",
            (g.current_user.get('id'),),
        ).fetchall()
    return jsonify([dict(n) for n in notes])


@app.route('/api/notes', methods=['POST'])
@token_required
def create_note():
    allowed, _ = _note_write_scope()
    if not allowed:
        log_action('CREATE_NOTE_DENIED', 'notes', f'role={_actor_role()}')
        return jsonify({'error': 'Insufficient permissions to create notes.'}), 403
    data = request.json or {}
    db = get_db()
    pinned = 1 if data.get('pinned') else 0
    cur = db.execute(
        "INSERT INTO notes (user_id, title, content, pinned) VALUES (?, ?, ?, ?)",
        (g.current_user['id'], data.get('title', ''), data.get('content', ''), pinned))
    db.commit()
    return jsonify({'success': True, 'id': cur.lastrowid})


@app.route('/api/notes/<int:nid>', methods=['PUT'])
@token_required
def update_note(nid):
    allowed, owner_only = _note_write_scope()
    if not allowed:
        log_action('UPDATE_NOTE_DENIED', 'notes', f'id={nid} role={_actor_role()}')
        return jsonify({'error': 'Insufficient permissions to edit notes.'}), 403
    data = request.json or {}
    db = get_db()
    _row, denied = _authorize_note(db, nid, owner_only)
    if denied:
        log_action('UPDATE_NOTE_DENIED', 'notes', f'id={nid} role={_actor_role()}')
        return denied
    if 'pinned' in data:
        db.execute(
            "UPDATE notes SET title=?, content=?, pinned=?, updated_at=? WHERE id=?",
            (data.get('title', ''), data.get('content', ''),
             1 if data.get('pinned') else 0,
             datetime.now().isoformat(), nid))
    else:
        db.execute(
            "UPDATE notes SET title=?, content=?, updated_at=? WHERE id=?",
            (data.get('title', ''), data.get('content', ''),
             datetime.now().isoformat(), nid))
    db.commit()
    return jsonify({'success': True})


@app.route('/api/notes/<int:nid>', methods=['DELETE'])
@token_required
def delete_note(nid):
    allowed, owner_only = _note_write_scope()
    if not allowed:
        log_action('DELETE_NOTE_DENIED', 'notes', f'id={nid} role={_actor_role()}')
        return jsonify({'error': 'Insufficient permissions to delete notes.'}), 403
    db = get_db()
    _row, denied = _authorize_note(db, nid, owner_only)
    if denied:
        log_action('DELETE_NOTE_DENIED', 'notes', f'id={nid} role={_actor_role()}')
        return denied
    db.execute("DELETE FROM notes WHERE id=?", (nid,))
    db.commit()
    return jsonify({'success': True})


# ── HEALTH ────────────────────────────────────────────────────────────────────

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'time': datetime.now().isoformat(), 'system': 'MBT POS'})


# ── Live Dashboard Blueprint (optional; used by web_launcher.py) ──────────────
# Load web_routes.py from the filesystem bundle path so HOT_APPLY can update the
# React SPA routes without a full PyInstaller rebuild (PYZ would otherwise win).
try:
    import importlib.util
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    _web_routes_py = os.path.join(BASE_DIR, 'web', 'web_routes.py')
    if os.path.isfile(_web_routes_py):
        _spec = importlib.util.spec_from_file_location('web.web_routes', _web_routes_py)
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules['web.web_routes'] = _mod
        _spec.loader.exec_module(_mod)
        web_blueprint = _mod.web
    else:
        from web.web_routes import web as web_blueprint
    app.register_blueprint(web_blueprint)
    logger.info("Web dashboard blueprint registered from %s", _web_routes_py)
except Exception as _e:
    logger.warning(f"Web blueprint not loaded: {_e}")


def create_app():
    """Gunicorn application factory for the always-on Portal origin."""
    init_db()
    return app


if __name__ == '__main__':
    create_app()
    port = int(os.environ.get('PORT', os.environ.get('FLASK_PORT', 5050)))
    # Remote access is provided by the local Cloudflare tunnel.  Do not expose
    # the unauthenticated development server directly to the shop LAN.
    app.run(host=os.environ.get('FLASK_HOST', '127.0.0.1'),
            port=port, debug=False)
