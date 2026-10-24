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
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = (request.headers.get('Origin') or '').rstrip('/')
        host = (request.host_url or '').rstrip('/')
        if origin and origin not in _ALLOWED_ORIGINS and origin != host:
            return jsonify({'error': 'Origin is not allowed.'}), 403
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
    if 'electronic_method' not in sales_cols:
        cur.execute("ALTER TABLE sales ADD COLUMN electronic_method TEXT")
    if 'cash_paid' not in sales_cols:
        cur.execute("ALTER TABLE sales ADD COLUMN cash_paid REAL DEFAULT 0")
    if 'payment_tenders' not in sales_cols:
        cur.execute("ALTER TABLE sales ADD COLUMN payment_tenders TEXT")
    if 'sale_date' not in sales_cols:
        cur.execute("ALTER TABLE sales ADD COLUMN sale_date TEXT")
        cur.execute(
            "UPDATE sales SET sale_date=date(created_at) "
            "WHERE sale_date IS NULL OR sale_date=''"
        )
    if 'client_token' not in sales_cols:
        cur.execute("ALTER TABLE sales ADD COLUMN client_token TEXT")
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_client_token "
        "ON sales(client_token) WHERE client_token IS NOT NULL AND client_token != ''"
    )

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


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({'error': 'Token required'}), 401
        # 1) Local Flask JWT (desktop POS / local users)
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE id=? AND is_active=1",
                              (data['user_id'],)).fetchone()
            if user:
                sid = str(data.get('sid') or '')
                if sid:
                    from desktop.utils.account_sessions import web_session_active
                    if not web_session_active(db, sid):
                        return jsonify({'error': 'This sign-in has ended. Sign in again.'}), 401
                g.current_user = dict(user)
                g.session_id = sid
                g.auth_provider = 'local'
                return f(*args, **kwargs)
        except Exception:
            pass
        # 2) Supabase JWT (MugoByte Platform cloud auth)
        try:
            from backend.cloud_backup.paths import is_cloud_configured, load_cloud_config
            if is_cloud_configured():
                from backend.cloud.net_gate import network_up
                if not network_up(1.0):
                    return jsonify({'error': 'Invalid token'}), 401
                from backend.cloud_backup.supabase_client import SupabaseClient
                cfg = load_cloud_config()
                r = SupabaseClient()._session.get(
                    f"{(cfg.get('supabase_url') or '').rstrip('/')}/auth/v1/user",
                    headers={
                        'apikey': cfg.get('anon_key') or '',
                        'Authorization': f'Bearer {token}',
                    },
                    timeout=4,
                )
                if r.status_code < 400:
                    u = r.json() or {}
                    meta = u.get('user_metadata') or {}
                    app_meta = u.get('app_metadata') or {}
                    g.current_user = {
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
                    g.auth_provider = 'supabase'
                    return f(*args, **kwargs)
        except Exception as e:
            logger.debug('Supabase token check: %s', e)
        return jsonify({'error': 'Invalid token'}), 401
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
    from desktop.utils.account_sessions import open_web_session
    sid = open_web_session(db, dict(user), request.remote_addr or '')
    db.commit()

    token = jwt.encode({
        'user_id': user['id'],
        'username': user['username'],
        'role': user['role'],
        'sid': sid,
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


def _account_api():
    from desktop.utils.api_client import APIClient
    user = g.current_user or {}
    api = APIClient()
    api._user_id = user.get('id')
    api._username = user.get('username') or ''
    api._role = (user.get('role') or '').lower()
    return api


def _manage_users():
    return _role_is('admin', 'superadmin', 'manager')


@app.route('/api/account/password', methods=['POST'])
@token_required
def change_own_password_http():
    data = request.json or {}
    result = _account_api().change_own_password(
        data.get('current_password') or '',
        data.get('new_password') or '',
        data.get('confirm_password') or '',
    )
    if result.get('success'):
        keep = getattr(g, 'session_id', '') or ''
        db = get_db()
        from desktop.utils.account_sessions import revoke_other_web_sessions
        revoke_other_web_sessions(db, g.current_user.get('id'), keep)
        db.commit()
        return jsonify(result)
    code = int(result.get('status') or 400)
    return jsonify(result), code


@app.route('/api/account/pin', methods=['POST'])
@token_required
def change_superadmin_pin_http():
    data = request.json or {}
    result = _account_api().change_superadmin_pin(
        data.get('current_pin') or '',
        data.get('new_pin') or '',
        data.get('confirm_pin') or '',
    )
    code = 200 if result.get('success') else int(result.get('status') or 400)
    return jsonify(result), code


@app.route('/api/sessions', methods=['GET'])
@token_required
def list_sessions_http():
    if not _manage_users():
        return jsonify({'error': 'Forbidden'}), 403
    from desktop.utils.account_sessions import list_web_sessions
    db = get_db()
    return jsonify({'sessions': list_web_sessions(db)})


@app.route('/api/sessions/<sid>/revoke', methods=['POST'])
@token_required
def revoke_session_http(sid):
    if not _manage_users():
        return jsonify({'error': 'Forbidden'}), 403
    from desktop.utils.account_sessions import revoke_web_session
    db = get_db()
    result = revoke_web_session(db, sid)
    if result.get('error'):
        return jsonify(result), 404
    db.commit()
    log_action('SESSION_REVOKED', 'users', 'web session ended')
    return jsonify(result)


@app.route('/api/till/signins', methods=['GET'])
@token_required
def list_till_signins_http():
    if not _manage_users():
        return jsonify({'error': 'Forbidden'}), 403
    from desktop.utils.account_sessions import list_till_sessions
    db = get_db()
    return jsonify({'signins': list_till_sessions(db)})


@app.route('/api/till/signins/<int:session_id>/end', methods=['POST'])
@token_required
def end_till_signin_http(session_id):
    if not _manage_users():
        return jsonify({'error': 'Forbidden'}), 403
    from desktop.utils.account_sessions import request_till_end
    db = get_db()
    result = request_till_end(db, session_id)
    if result.get('error'):
        return jsonify(result), 404
    db.commit()
    log_action('TILL_SIGNIN_END', 'users', f'session={session_id}')
    return jsonify(result)


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
    username = (data.get('username') or '').strip()
    password = '' if data.get('password') is None else str(data.get('password'))
    if not username or len(password.strip()) < 6 or password != password.strip():
        return jsonify({'error': 'Username and a password of at least 6 characters are required.'}), 400
    pw_hash = hash_pw(password)
    db = get_db()
    raw_perms = data.get('tab_permissions')
    if raw_perms is None:
        perms = default_tab_permissions(new_role)
    else:
        perms = sanitize_tab_permissions(new_role, raw_perms)
    try:
        db.execute("""INSERT INTO users (username, password_hash, role, full_name, email, tab_permissions)
                      VALUES (?, ?, ?, ?, ?, ?)""",
                   (username, pw_hash, new_role,
                    data.get('full_name'), data.get('email'), json.dumps(perms)))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'That username already exists.'}), 400
    except (KeyError, TypeError):
        return jsonify({'error': 'Username and password are required.'}), 400
    log_action('CREATE_USER', 'admin', f"Created user: {username} role={new_role}")
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
    data = request.json or {}
    user = g.current_user or {}
    from desktop.utils.api_client import APIClient
    api = APIClient()
    api._user_id = user.get('id')
    api._username = user.get('username') or user.get('full_name') or 'web'
    api._role = (user.get('role') or 'cashier').lower()
    result = api.create_product(data)
    code = 200 if result.get('success') else int(result.get('status') or 400)
    return jsonify(result), code


@app.route('/api/products/<int:pid>', methods=['PUT'])
@token_required
def update_product(pid):
    data = request.json or {}
    if 'stock' in data:
        return jsonify({
            'error': 'Change stock through the protected Adjust Stock action.',
        }), 403
    db = get_db()
    fields = []
    values = []
    for field in ('name', 'sku', 'category', 'price', 'cost_price', 'min_stock', 'unit', 'barcode'):
        if field in data:
            fields.append(f"{field}=?")
            values.append(data[field])
    fields.append("updated_at=?")
    values.append(datetime.now().isoformat())
    values.append(pid)
    db.execute(f"UPDATE products SET {', '.join(fields)} WHERE id=?", values)
    db.commit()
    return jsonify({'success': True})


@app.route('/api/products/<int:pid>', methods=['DELETE'])
@token_required
def delete_product(pid):
    db = get_db()
    db.execute("UPDATE products SET is_active=0 WHERE id=?", (pid,))
    db.commit()
    return jsonify({'success': True})


# ── SALES ─────────────────────────────────────────────────────────────────────

def _sale_day_sql(alias: str = '') -> str:
    """Same business day the till uses: sale_date, otherwise the created date."""
    prefix = f'{alias}.' if alias else ''
    return f"COALESCE(NULLIF({prefix}sale_date,''), date({prefix}created_at))"


@app.route('/api/sales', methods=['GET'])
@token_required
def list_sales():
    db = get_db()
    start = request.args.get('start', str(date.today()))
    end = request.args.get('end', str(date.today()))
    day = _sale_day_sql('s')
    sales = db.execute(f"""SELECT s.*, GROUP_CONCAT(si.product_name || ' x' || si.quantity) as items_summary
                          FROM sales s LEFT JOIN sale_items si ON s.id = si.sale_id
                          WHERE {day} BETWEEN ? AND ?
                          GROUP BY s.id ORDER BY s.created_at DESC""",
                       (start, end)).fetchall()
    return jsonify([dict(s) for s in sales])


@app.route('/api/sales/void-request', methods=['POST'])
@app.route('/api/sales/<int:sale_id>/void', methods=['POST'])
@token_required
def void_sale_http(sale_id=None):
    """Ask for a void. The sale stays completed until Approvals accepts it."""
    data = request.json or {}
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({'error': 'Enter a reason before requesting a void.'}), 400
    user = g.current_user or {}
    from desktop.utils.api_client import APIClient
    from desktop.utils.security import has_permission
    role = (user.get('role') or '').lower()
    if not has_permission({'role': role}, 'sales.request_void'):
        return jsonify({'error': 'You cannot request a void.'}), 403
    if sale_id is None:
        receipt = (data.get('receipt_number') or '').strip()
        if not receipt:
            return jsonify({'error': 'Enter the receipt number.'}), 400
        row = get_db().execute(
            "SELECT id FROM sales WHERE receipt_number=?", (receipt,)
        ).fetchone()
        if not row:
            return jsonify({'error': 'Sale was not found.'}), 404
        sale_id = row['id']
    api = APIClient()
    api._user_id = user.get('id')
    api._username = user.get('username') or user.get('full_name') or 'web'
    api._role = role
    result = api.request_sale_void(int(sale_id), reason)
    code = 200 if result.get('success') else int(result.get('status') or 400)
    return jsonify(result), code


@app.route('/api/sales', methods=['POST'])
@token_required
def create_sale():
    data = request.json or {}
    items = data.get('items') or []
    if not items:
        return jsonify({'error': 'Cart is empty — add at least one product before charging.'}), 400
    db = get_db()
    user = g.current_user
    from desktop.utils.shop_time import (
        business_day_iso, parse_sale_date, sale_created_at_for_day, shop_today,
    )
    role = (user.get('role') or '').lower()
    raw_day = (data.get('sale_date') or data.get('business_day') or '').strip()
    requested = parse_sale_date(raw_day) if raw_day else shop_today()
    if requested is None:
        return jsonify({'error': 'Invalid sale date. Use YYYY-MM-DD.'}), 400
    if requested > shop_today():
        return jsonify({'error': 'Sale date cannot be in the future.'}), 400
    if requested != shop_today() and role not in ('admin', 'superadmin', 'manager'):
        return jsonify({'error': 'Only a manager or admin can backdate a sale.'}), 403
    sale_date_s = business_day_iso(requested)
    created_at_s = sale_created_at_for_day(sale_date_s)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("PRAGMA foreign_keys=OFF")
        sale_token = (data.get('client_token') or '').strip()
        if sale_token:
            existing = db.execute(
                "SELECT id, receipt_number, total, sale_date FROM sales WHERE client_token=?",
                (sale_token,),
            ).fetchone()
            if existing:
                db.rollback()
                return jsonify({
                    'success': True,
                    'duplicate': True,
                    'sale_id': existing['id'],
                    'receipt_number': existing['receipt_number'],
                    'total': existing['total'],
                    'sale_date': existing['sale_date'],
                })
        day_key = sale_date_s.replace('-', '')
        count = db.execute(
            "SELECT COUNT(*) FROM sales WHERE " + _sale_day_sql() + "=?",
            (sale_date_s,),
        ).fetchone()[0]
        receipt_number = f"RCP-{day_key}-{count+1:04d}"

        notes = data.get('notes', '') or data.get('note', '') or ''
        if sale_date_s != shop_today().isoformat() and 'business day' not in notes.lower():
            notes = (notes + f' | Business day: {sale_date_s}').strip(' |')
        mpesa_ref = (data.get('mpesa_ref') or '').strip()
        if mpesa_ref and 'mpesa ref' not in notes.lower():
            notes = (notes + f' | M-Pesa ref: {mpesa_ref}').strip(' |')
        method_name = (data.get('payment_method') or 'cash').strip()
        electronic_paid = round(float(data.get('electronic_paid') or 0), 2)
        cash_paid_col = round(float(data.get('cash_paid') or 0), 2)
        emethod = (data.get('electronic_method') or '').strip()
        if method_name.lower() in ('mixed', 'split'):
            method_name = 'Mixed'
            if cash_paid_col <= 0.009 or electronic_paid <= 0.009:
                db.rollback()
                return jsonify({'error': 'A split sale needs both a cash amount and a second payment.'}), 400
            if cash_paid_col + electronic_paid + 0.009 < float(data.get('total') or 0):
                db.rollback()
                return jsonify({'error': 'Split payments do not cover the total.'}), 400
        tenders = data.get('payment_tenders')
        if isinstance(tenders, list):
            tenders_json = json.dumps(tenders)
        else:
            tenders_json = None
        if not tenders_json and electronic_paid > 0.009:
            from desktop.utils.payment_tenders import build_tenders
            tenders_json = json.dumps(build_tenders(
                cash_paid=cash_paid_col,
                electronic_paid=electronic_paid,
                electronic_method=emethod or 'M-Pesa',
            ))
        if electronic_paid > 0.009 and 'split:' not in notes.lower():
            notes = (
                notes + f' | Split: {emethod or "M-Pesa"} {electronic_paid:,.2f} + Cash {cash_paid_col:,.2f}'
            ).strip(' |')

        db.execute("""INSERT INTO sales (receipt_number, cashier_id, cashier_name, subtotal, discount,
                  tax, total, payment_method, amount_paid, change_amount, notes, mpesa_ref,
                  sale_date, created_at, customer_id, electronic_paid, electronic_method,
                  cash_paid, payment_tenders, client_token)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
               (receipt_number, user['id'], user['full_name'] or user['username'],
                data.get('subtotal', 0), data.get('discount', 0), data.get('tax', 0),
                data['total'], method_name,
                data.get('amount_paid', 0), data.get('change_amount', 0),
                notes, mpesa_ref or None, sale_date_s, created_at_s,
                data.get('customer_id') or None, electronic_paid, emethod or None,
                cash_paid_col, tenders_json, sale_token or None))

        sale_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        from backend.sale_lines import fill_sale_line
        for item in items:
            line = fill_sale_line(db, item)
            pid = line['product_id']
            db.execute("""INSERT INTO sale_items (sale_id, product_id, product_name, sku, quantity, unit_price, discount, total)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                       (sale_id, pid, line['product_name'], line['sku'],
                        line['quantity'], line['unit_price'], line['discount'], line['total']))

            if pid:
                prod_row = db.execute(
                    "SELECT id, name, stock FROM products WHERE id=?", (pid,)
                ).fetchone()
                if prod_row:
                    qty_requested = float(item.get('quantity') or 1)
                    current_stock = float(prod_row['stock'])
                    if current_stock < qty_requested:
                        db.rollback()
                        return jsonify({
                            'error': (
                                f"Insufficient stock for '{prod_row['name']}': "
                                f"requested {qty_requested}, available {current_stock}"
                            )
                        }), 400
                    new_stock = current_stock - qty_requested
                    db.execute(
                        "UPDATE products SET stock=? WHERE id=?",
                        (new_stock, pid)
                    )
                    db.execute(
                        """INSERT INTO stock_movements
                           (product_id, product_name, movement_type, qty_before, qty_change,
                            qty_after, reference, reason, user_id, username)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (pid, prod_row['name'], 'SALE',
                         current_stock, -qty_requested, new_stock,
                         receipt_number, f"Sale: {receipt_number}",
                         user['id'], user['username'])
                    )

        db.execute("INSERT INTO sync_queue (action_type, payload) VALUES (?, ?)",
                   ('sale', json.dumps({
                       'receipt_number': receipt_number,
                       'total': data['total'],
                       'cashier': user['username'],
                       'created_at': datetime.now().isoformat()
                   })))
        db.commit()
        log_action('CREATE_SALE', 'sales',
                   f"Receipt: {receipt_number}, Total: {data['total']}")
        debt = None
        method = (data.get('payment_method') or 'cash').strip().lower()
        cust_id = data.get('customer_id')
        if method in ('credit sale', 'credit', 'part payment', 'part-payment') and cust_id:
            try:
                from desktop.utils.api_client import APIClient
                debt = APIClient().create_debt_invoice({
                    'customer_id': cust_id,
                    'sale_id': sale_id,
                    'receipt_number': receipt_number,
                    'total_amount': data['total'],
                    'amount_paid': data.get('amount_paid') or 0,
                    'payment_method': method,
                    'notes': notes,
                })
            except Exception as debt_err:
                logger.error(f"debt invoice after sale failed: {debt_err}", exc_info=True)
                debt = {'error': str(debt_err)}
        return jsonify({
            'success': True,
            'receipt_number': receipt_number,
            'sale_id': sale_id,
            'sale_date': sale_date_s,
            'debt': debt,
        })
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(f"create_sale failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass


@app.route('/api/sales/<int:sale_id>', methods=['GET'])
@token_required
def get_sale(sale_id):
    db = get_db()
    sale = db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
    if not sale:
        return jsonify({'error': 'Not found'}), 404
    items = db.execute(
        """SELECT si.*,
                  p.sku AS product_sku, p.barcode, p.category, p.unit,
                  p.price AS product_price, p.cost_price, p.stock AS current_stock
           FROM sale_items si
           LEFT JOIN products p ON p.id = si.product_id
           WHERE si.sale_id=?""",
        (sale_id,),
    ).fetchall()
    result = dict(sale)
    result['items'] = [dict(i) for i in items]
    if result.get('customer_id'):
        cust = db.execute(
            "SELECT name, phone FROM customers WHERE id=?",
            (result['customer_id'],),
        ).fetchone()
        if cust:
            result['customer_name'] = cust['name'] or ''
            result['customer_phone'] = cust['phone'] or ''
    try:
        debt = db.execute(
            "SELECT invoice_number, status, balance, total_amount, amount_paid "
            "FROM debt_invoices WHERE sale_id=? ORDER BY id DESC LIMIT 1",
            (sale_id,),
        ).fetchone()
        if debt:
            result['debt'] = dict(debt)
    except Exception:
        pass
    return jsonify(result)


# ── REPORTS ───────────────────────────────────────────────────────────────────

@app.route('/api/reports/summary', methods=['GET'])
@token_required
def sales_summary():
    db = get_db()
    start = request.args.get('start', str(date.today()))
    end = request.args.get('end', str(date.today()))

    summary = db.execute("""
        SELECT
            COUNT(*) as total_transactions,
            COALESCE(SUM(total), 0) as total_revenue,
            COALESCE(AVG(total), 0) as avg_transaction,
            COALESCE(SUM(discount), 0) as total_discounts,
            COALESCE(SUM(tax), 0) as total_tax
        FROM sales WHERE """ + _sale_day_sql() + """ BETWEEN ? AND ?
          AND status IN ('completed','return')
    """, (start, end)).fetchone()

    top_products = db.execute("""
        SELECT si.product_name, SUM(si.quantity) as qty_sold, SUM(si.total) as revenue
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        WHERE """ + _sale_day_sql('s') + """ BETWEEN ? AND ?
          AND s.status IN ('completed','return')
        GROUP BY si.product_name ORDER BY revenue DESC LIMIT 10
    """, (start, end)).fetchall()

    by_payment = db.execute("""
        SELECT payment_method, COUNT(*) as count, SUM(total) as total
        FROM sales WHERE """ + _sale_day_sql() + """ BETWEEN ? AND ?
          AND status IN ('completed','return')
        GROUP BY payment_method
    """, (start, end)).fetchall()

    hourly = db.execute("""
        SELECT strftime('%H', created_at) as hour, COUNT(*) as count, SUM(total) as total
        FROM sales WHERE """ + _sale_day_sql() + """ BETWEEN ? AND ?
          AND status IN ('completed','return')
        GROUP BY hour ORDER BY hour
    """, (start, end)).fetchall()

    return jsonify({
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
    return jsonify({r['key']: r['value'] for r in rows})


@app.route('/api/settings', methods=['PUT'])
@token_required
def update_settings():
    if not _role_is('admin', 'superadmin'):
        return jsonify({'error': 'Admin only'}), 403
    data = request.json or {}
    from backend.settings_guard import reject_secret_settings
    try:
        data = reject_secret_settings(data)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
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
    db = get_db()
    items = db.execute("SELECT * FROM sync_queue WHERE status='pending' ORDER BY created_at").fetchall()
    return jsonify([dict(i) for i in items])


@app.route('/api/sync/mark-sent', methods=['POST'])
@token_required
def mark_synced():
    data = request.json or {}
    ids = data.get('ids', [])
    db = get_db()
    for sid in ids:
        db.execute("UPDATE sync_queue SET status='sent', synced_at=? WHERE id=?",
                   (datetime.now().isoformat(), sid))
    db.commit()
    return jsonify({'success': True})


# ── NOTES ─────────────────────────────────────────────────────────────────────

@app.route('/api/notes', methods=['GET'])
@token_required
def list_notes():
    db = get_db()
    notes = db.execute(
        "SELECT * FROM notes ORDER BY COALESCE(pinned,0) DESC, updated_at DESC"
    ).fetchall()
    return jsonify([dict(n) for n in notes])


@app.route('/api/notes', methods=['POST'])
@token_required
def create_note():
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
    data = request.json or {}
    db = get_db()
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
    db = get_db()
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
