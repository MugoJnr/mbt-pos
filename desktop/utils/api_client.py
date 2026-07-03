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
def _db() -> sqlite3.Connection:
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    is_new = not os.path.exists(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    # Always ensure schema exists (safe on existing DBs via CREATE IF NOT EXISTS)
    _ensure_schema(conn)
    return conn


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
             '["dashboard","sales","inventory","reports","notes","settings","admin",'
             '"license","diagnostics","security"]')
        )
    _migrate_columns(conn)
    # Seed default settings if missing (per-shop; see config/deploy.py)
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
        }
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
        pass
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
    conn.commit()


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
        db = _db()
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
            user = _row(db.execute(
                "SELECT * FROM users WHERE username=? AND is_active=1", (username,)
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
            return {
                'token': token,
                'user': {
                    'id':              user['id'],
                    'username':        user['username'],
                    'full_name':       user['full_name'],
                    'role':            user['role'],
                    'tab_permissions': perms,
                }
            }
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
        db = _db()
        try:
            pw_hash = _hash_pw(data['password'])
            perms   = json.dumps(data.get('tab_permissions', ['dashboard','sales']))
            db.execute(
                "INSERT INTO users (username,password_hash,role,full_name,email,tab_permissions)"
                " VALUES (?,?,?,?,?,?)",
                (data['username'], pw_hash, data.get('role','cashier'),
                 data.get('full_name'), data.get('email'), perms)
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
        db = _db()
        try:
            fields, values = [], []
            for field in ('role','full_name','email','is_active'):
                if field in data:
                    fields.append(f"{field}=?"); values.append(data[field])
            if 'tab_permissions' in data:
                fields.append("tab_permissions=?")
                values.append(json.dumps(data['tab_permissions']))
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
        db = _db()
        try:
            db.execute("UPDATE users SET is_active=0 WHERE id=?", (uid,))
            db.commit()
            return {'success': True}
        finally:
            db.close()

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
            return {'success': True, 'id': pid}
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
                          'min_stock','unit','barcode'):
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
            return {'success': True}
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

    def create_sale(self, data: dict) -> dict:
        db = _db()
        try:
            db.execute("BEGIN IMMEDIATE")
            # Allow sale line items even if a product was later removed from inventory.
            db.execute("PRAGMA foreign_keys=OFF")

            rn = _next_receipt(db)          # pass connection — avoids race condition
            total = float(data.get('total') or 0)

            notes = data.get('notes', '') or ''
            mpesa_ref = (data.get('mpesa_ref') or '').strip()
            if mpesa_ref and 'mpesa ref' not in notes.lower():
                notes = (notes + f' | M-Pesa ref: {mpesa_ref}').strip(' |')

            db.execute(
                "INSERT INTO sales (receipt_number,cashier_id,cashier_name,subtotal,"
                "discount,tax,total,payment_method,amount_paid,change_amount,notes,mpesa_ref)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (rn,
                 self._user_id,
                 self._username or 'staff',
                 float(data.get('subtotal') or 0),
                 float(data.get('discount') or 0),
                 float(data.get('tax') or 0),
                 total,
                 data.get('payment_method', 'cash'),
                 float(data.get('amount_paid') or 0),
                 float(data.get('change_amount') or 0),
                 notes,
                 mpesa_ref or None)
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

            db.execute(
                "INSERT INTO sync_queue (action_type,payload) VALUES (?,?)",
                ('sale', json.dumps({
                    'receipt_number': rn,
                    'total':          total,
                    'cashier':        self._username or 'staff',
                    'created_at':     datetime.now().isoformat()
                }))
            )
            db.commit()
            _audit(self._user_id, self._username or 'staff',
                   'CREATE_SALE', 'sales', f"receipt={rn} total={total}")
            return {'success': True, 'receipt_number': rn, 'sale_id': sale_id}

        except Exception as e:
            try: db.rollback()
            except Exception: pass
            logger.error(f"create_sale failed: {e}", exc_info=True)
            raise   # re-raise so the UI shows the real error message
        finally:
            try: db.execute("PRAGMA foreign_keys=ON")
            except Exception: pass
            db.close()

    def get_sale(self, sale_id: int) -> dict:
        db = _db()
        try:
            sale  = _row(db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)))
            if not sale:
                return {}
            items = _rows(db.execute("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)))
            sale['items'] = items
            return sale
        finally:
            db.close()

    # ── SALES EDITING / VOID ─────────────────────────────────────────────────────

    def void_sale(self, sale_id: int, reason: str) -> dict:
        """
        Void a completed sale. Only admin/superadmin.
        Restores stock for all items. Full audit trail.
        """
        if self._role not in ('admin', 'superadmin'):
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

            # Cancel linked debt invoices for this sale
            debt_rows = db.execute(
                "SELECT id, invoice_number, status FROM debt_invoices "
                "WHERE sale_id=? AND status NOT IN ('paid','cancelled')",
                (sale_id,)
            ).fetchall()
            for inv in debt_rows:
                db.execute(
                    "UPDATE debt_invoices SET status='cancelled', notes=?, updated_at=? "
                    "WHERE id=?",
                    (f"CANCELLED: sale {sale['receipt_number']} voided — {reason}",
                     datetime.now().isoformat(), inv['id'])
                )
                _audit(self._user_id, self._username or 'admin',
                       'CANCEL_INVOICE', 'debt',
                       f"inv={inv['invoice_number']} auto-cancelled (void sale)")

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

            db.commit()
            _audit(self._user_id, self._username,
                   'VOID_SALE', 'sales',
                   f"sale_id={sale_id} receipt={sale['receipt_number']} reason={reason}")
            return {'success': True}
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
                       COALESCE(AVG(total),0) as avg_transaction,
                       COALESCE(SUM(discount),0) as total_discounts,
                       COALESCE(SUM(tax),0) as total_tax
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

    # ── NOTES ─────────────────────────────────────────────────────────────────────

    def get_notes(self) -> list:
        db = _db()
        try:
            return _rows(db.execute("SELECT * FROM notes ORDER BY updated_at DESC"))
        finally:
            db.close()

    def create_note(self, data: dict) -> dict:
        db = _db()
        try:
            db.execute(
                "INSERT INTO notes (user_id,title,content) VALUES (?,?,?)",
                (self._user_id, data.get('title',''), data.get('content',''))
            )
            db.commit()
            return {'success': True}
        finally:
            db.close()

    def update_note(self, nid: int, data: dict) -> dict:
        db = _db()
        try:
            db.execute(
                "UPDATE notes SET title=?,content=?,updated_at=? WHERE id=?",
                (data.get('title',''), data.get('content',''),
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
                "COUNT(di.id) as open_invoices "
                "FROM customers c "
                "LEFT JOIN debt_invoices di ON c.id=di.customer_id AND di.status NOT IN ('paid','cancelled') "
                "WHERE c.is_active=1 GROUP BY c.id ORDER BY c.name"
            ))
        finally:
            db.close()

    def create_customer(self, data: dict) -> dict:
        db = _db()
        try:
            db.execute(
                "INSERT INTO customers (name,phone,email,address,credit_limit,notes) VALUES (?,?,?,?,?,?)",
                (data['name'], data.get('phone',''), data.get('email',''),
                 data.get('address',''), data.get('credit_limit',0), data.get('notes',''))
            )
            db.commit()
            cid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            _audit(self._user_id, self._username, 'CREATE_CUSTOMER', 'debt', f"name={data['name']}")
            return {'success': True, 'customer_id': cid}
        except sqlite3.IntegrityError:
            return {'error': 'Customer already exists'}
        finally:
            db.close()

    def update_customer(self, cid: int, data: dict) -> dict:
        db = _db()
        try:
            fields, values = [], []
            for f in ('name','phone','email','address','credit_limit','notes','is_active'):
                if f in data:
                    fields.append(f"{f}=?"); values.append(data[f])
            if fields:
                values.append(cid)
                db.execute(f"UPDATE customers SET {','.join(fields)} WHERE id=?", values)
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
        Create a debt invoice (part payment or credit sale).
        data keys: customer_id, sale_id, receipt_number, total_amount,
                   amount_paid, due_date, notes, cashier_name
        """
        db = _db()
        try:
            cust = _row(db.execute("SELECT * FROM customers WHERE id=?", (data['customer_id'],)))
            if not cust:
                return {'error': 'Customer not found'}

            total    = float(data['total_amount'])
            paid     = float(data.get('amount_paid', 0))
            balance  = round(total - paid, 2)

            if balance < 0:
                return {'error': 'Amount paid exceeds total — no debt to record.'}

            inv_num  = self._next_invoice_number(db)
            status   = 'paid' if balance == 0 else ('partial' if paid > 0 else 'pending')

            db.execute(
                "INSERT INTO debt_invoices (invoice_number,sale_id,receipt_number,"
                "customer_id,customer_name,customer_phone,total_amount,amount_paid,"
                "balance,status,due_date,cashier_id,cashier_name,notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (inv_num, data.get('sale_id'), data.get('receipt_number'),
                 data['customer_id'], cust['name'], cust.get('phone',''),
                 total, paid, balance, status,
                 data.get('due_date'), self._user_id,
                 self._username or data.get('cashier_name','staff'),
                 data.get('notes',''))
            )
            inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Record initial payment if any
            if paid > 0:
                pay_receipt = self._next_payment_receipt(db)
                db.execute(
                    "INSERT INTO debt_payments (payment_receipt,invoice_id,customer_id,"
                    "amount,payment_method,balance_before,balance_after,cashier_id,cashier_name,notes) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (pay_receipt, inv_id, data['customer_id'],
                     paid, data.get('payment_method','cash'),
                     total, balance,
                     self._user_id, self._username or 'staff',
                     f"Initial payment on invoice {inv_num}")
                )

            db.commit()
            _audit(self._user_id, self._username, 'CREATE_INVOICE', 'debt',
                   f"inv={inv_num} customer={cust['name']} total={total} paid={paid} balance={balance}")
            return {'success': True, 'invoice_number': inv_num, 'invoice_id': inv_id, 'balance': balance}
        except Exception as e:
            db.rollback()
            logger.error(f"create_debt_invoice: {e}", exc_info=True)
            return {'error': str(e)}
        finally:
            db.close()

    def get_debt_invoices(self, status=None, customer_id=None,
                          start=None, end=None) -> list:
        db = _db()
        try:
            clauses = []
            params  = []
            if status:
                if isinstance(status, list):
                    ph = ','.join('?' * len(status))
                    clauses.append(f"di.status IN ({ph})")
                    params.extend(status)
                else:
                    clauses.append("di.status=?"); params.append(status)
            if customer_id:
                clauses.append("di.customer_id=?"); params.append(customer_id)
            if start:
                clauses.append("date(di.created_at)>=?"); params.append(start)
            if end:
                clauses.append("date(di.created_at)<=?"); params.append(end)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            return _rows(db.execute(
                f"SELECT di.*, c.phone as c_phone, c.email as c_email "
                f"FROM debt_invoices di JOIN customers c ON di.customer_id=c.id "
                f"{where} ORDER BY di.created_at DESC", params
            ))
        finally:
            db.close()

    def get_overdue_invoices(self) -> list:
        db = _db()
        try:
            return _rows(db.execute(
                "SELECT di.*, c.phone, c.email FROM debt_invoices di "
                "JOIN customers c ON di.customer_id=c.id "
                "WHERE di.status NOT IN ('paid','cancelled') "
                "AND di.due_date IS NOT NULL AND di.due_date < date('now') "
                "ORDER BY di.due_date ASC"
            ))
        finally:
            db.close()

    def record_debt_payment(self, invoice_id: int, amount: float,
                            payment_method: str = 'cash', notes: str = '') -> dict:
        """Collect a payment against an existing invoice."""
        db = _db()
        try:
            inv = _row(db.execute("SELECT * FROM debt_invoices WHERE id=?", (invoice_id,)))
            if not inv:
                return {'error': 'Invoice not found'}
            if inv['status'] in ('paid', 'cancelled'):
                return {'error': f"Invoice is already {inv['status']}"}

            amount = round(float(amount), 2)
            balance_before = round(float(inv['balance']), 2)

            if amount <= 0:
                return {'error': 'Payment amount must be greater than zero'}
            if amount > balance_before:
                return {'error': f"Payment ({amount:,.2f}) exceeds outstanding balance ({balance_before:,.2f})"}

            balance_after = round(balance_before - amount, 2)
            new_paid      = round(float(inv['amount_paid']) + amount, 2)
            new_status    = 'paid' if balance_after == 0 else 'partial'

            pay_receipt = self._next_payment_receipt(db)

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
            db.commit()
            _audit(self._user_id, self._username, 'DEBT_PAYMENT', 'debt',
                   f"inv={inv['invoice_number']} amount={amount} balance_after={balance_after}")
            return {
                'success': True,
                'payment_receipt': pay_receipt,
                'balance_before': balance_before,
                'balance_after': balance_after,
                'status': new_status,
                'invoice_number': inv['invoice_number'],
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
                clauses.append("dp.invoice_id=?"); params.append(invoice_id)
            if customer_id:
                clauses.append("dp.customer_id=?"); params.append(customer_id)
            if start:
                clauses.append("date(dp.created_at)>=?"); params.append(start)
            if end:
                clauses.append("date(dp.created_at)<=?"); params.append(end)
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

    def health(self) -> bool:
        try:
            db = _db()
            db.execute("SELECT 1")
            db.close()
            return True
        except Exception:
            return False
