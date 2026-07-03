"""
MBT POS System - Backend API
MugoByte Technologies
"""
import os
import sys
import json
import sqlite3
import logging
from datetime import datetime, date
from flask import Flask, request, jsonify, g
from functools import wraps
import jwt

try:
    from flask_cors import CORS
    _has_cors = True
except ImportError:
    _has_cors = False

import hashlib as _hashlib, os as _os2

def hash_pw(pw):
    """Always use salt:sha256 — works without bcrypt on all platforms."""
    salt = _os2.urandom(16).hex()
    return salt + ':' + _hashlib.sha256((salt + pw).encode()).hexdigest()

def check_pw(pw, h):
    """Detect hash format first to avoid bcrypt Invalid salt error."""
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
    return _hashlib.sha256((salt + pw_str).encode()).hexdigest() == stored

app = Flask(__name__)
if _has_cors:
    CORS(app)
else:
    @app.after_request
    def _cors(r):
        r.headers['Access-Control-Allow-Origin']  = '*'
        r.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        r.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
        return r

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Share the exact same database the desktop app uses (AppData when frozen,
# project data/ in development) so the web dashboard reflects live shop data.
try:
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    from mbt_paths import get_db_path as _get_db_path, ensure_data_dirs as _ensure_dirs, configure_sqlite_connection
    _ensure_dirs()
    DB_PATH = _get_db_path()
except Exception:
    DB_PATH = os.path.join(BASE_DIR, 'data', 'mbt_pos.db')
CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'settings.json')
LOG_PATH = os.path.join(BASE_DIR, 'logs', 'backend.log')
SECRET_KEY = "MBT_POS_SECRET_2024_MUGOBYTE"

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
    """)

    # Default shop owner (wizard normally creates this; fallback for API-only init)
    existing = cur.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not existing:
        from roles import default_tab_permissions
        pw_hash = hash_pw('admin123')
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
        'telegram_bot_token': '8342651179:AAE_JPNBUxWz9dkz49Ldr9sySwsabpx1IwQ',
        'telegram_chat_id': '',       # customer's own chat ID (for receiving keys)
        'developer_chat_id': '8293620725',      # YOUR Telegram ID — hardcoded for @mugobyte_technologies
        'currency_symbol': 'KES',
        'tax_rate': '0',
        'receipt_footer': 'Thank you for shopping with us!',
        'theme': 'dark',
        'sync_interval': '30',
        'printer_name': '',
        'printer_port': 'USB',
        'auto_print': '1',
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

    db.commit()
    db.close()
    logger.info("Database initialized")


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({'error': 'Token required'}), 401
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE id=? AND is_active=1",
                              (data['user_id'],)).fetchone()
            if not user:
                return jsonify({'error': 'Invalid token'}), 401
            g.current_user = dict(user)
        except Exception as e:
            return jsonify({'error': 'Invalid token'}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.current_user.get('role') not in ('admin', 'superadmin'):
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
    username = data.get('username', '').strip()
    password = data.get('password', '').encode()

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username=? AND is_active=1",
                      (username,)).fetchone()

    if not user or not check_pw(password.decode() if isinstance(password,bytes) else data.get('password',''), user['password_hash']):
        return jsonify({'error': 'Invalid credentials'}), 401

    db.execute("UPDATE users SET last_login=? WHERE id=?",
               (datetime.now().isoformat(), user['id']))
    db.commit()

    token = jwt.encode({
        'user_id': user['id'],
        'username': user['username'],
        'role': user['role'],
        'exp': datetime.utcnow().timestamp() + 86400 * 7
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
    db.execute("""INSERT INTO users (username, password_hash, role, full_name, email, tab_permissions)
                  VALUES (?, ?, ?, ?, ?, ?)""",
               (data['username'], pw_hash, new_role,
                data.get('full_name'), data.get('email'), json.dumps(perms)))
    db.commit()
    log_action('CREATE_USER', 'admin', f"Created user: {data['username']}")
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
    log_action('UPDATE_USER', 'admin', f"Updated user id={uid}")
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
    db = get_db()
    db.execute("""INSERT INTO products (name, sku, category, price, cost_price, stock, min_stock, unit, barcode)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
               (data['name'], data.get('sku'), data.get('category'),
                data.get('price', 0), data.get('cost_price', 0),
                data.get('stock', 0), data.get('min_stock', 5),
                data.get('unit', 'pcs'), data.get('barcode')))
    db.commit()
    log_action('CREATE_PRODUCT', 'inventory', f"Product: {data['name']}")
    return jsonify({'success': True})


@app.route('/api/products/<int:pid>', methods=['PUT'])
@token_required
def update_product(pid):
    data = request.json or {}
    db = get_db()
    fields = []
    values = []
    for field in ('name', 'sku', 'category', 'price', 'cost_price', 'stock', 'min_stock', 'unit', 'barcode'):
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

@app.route('/api/sales', methods=['GET'])
@token_required
def list_sales():
    db = get_db()
    start = request.args.get('start', str(date.today()))
    end = request.args.get('end', str(date.today()))
    sales = db.execute("""SELECT s.*, GROUP_CONCAT(si.product_name || ' x' || si.quantity) as items_summary
                          FROM sales s LEFT JOIN sale_items si ON s.id = si.sale_id
                          WHERE date(s.created_at) BETWEEN ? AND ?
                          GROUP BY s.id ORDER BY s.created_at DESC""",
                       (start, end)).fetchall()
    return jsonify([dict(s) for s in sales])


@app.route('/api/sales', methods=['POST'])
@token_required
def create_sale():
    data = request.json or {}
    db = get_db()
    user = g.current_user
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("PRAGMA foreign_keys=OFF")

        today = datetime.now().strftime('%Y%m%d')
        count = db.execute(
            "SELECT COUNT(*) FROM sales WHERE date(created_at)=date('now')"
        ).fetchone()[0]
        receipt_number = f"RCP-{today}-{count+1:04d}"

        notes = data.get('notes', '') or ''
        mpesa_ref = (data.get('mpesa_ref') or '').strip()
        if mpesa_ref and 'mpesa ref' not in notes.lower():
            notes = (notes + f' | M-Pesa ref: {mpesa_ref}').strip(' |')

        db.execute("""INSERT INTO sales (receipt_number, cashier_id, cashier_name, subtotal, discount,
                  tax, total, payment_method, amount_paid, change_amount, notes, mpesa_ref)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
               (receipt_number, user['id'], user['full_name'] or user['username'],
                data.get('subtotal', 0), data.get('discount', 0), data.get('tax', 0),
                data['total'], data.get('payment_method', 'cash'),
                data.get('amount_paid', 0), data.get('change_amount', 0),
                notes, mpesa_ref or None))

        sale_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        for item in data.get('items', []):
            pid = item.get('product_id')
            db.execute("""INSERT INTO sale_items (sale_id, product_id, product_name, sku, quantity, unit_price, discount, total)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                       (sale_id, pid, item['product_name'],
                        item.get('sku', ''), item['quantity'], item['unit_price'],
                        item.get('discount', 0), item['total']))

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
        return jsonify({
            'success': True,
            'receipt_number': receipt_number,
            'sale_id': sale_id
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
    items = db.execute("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)).fetchall()
    result = dict(sale)
    result['items'] = [dict(i) for i in items]
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
        FROM sales WHERE date(created_at) BETWEEN ? AND ? AND status='completed'
    """, (start, end)).fetchone()

    top_products = db.execute("""
        SELECT si.product_name, SUM(si.quantity) as qty_sold, SUM(si.total) as revenue
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        WHERE date(s.created_at) BETWEEN ? AND ? AND s.status='completed'
        GROUP BY si.product_name ORDER BY revenue DESC LIMIT 10
    """, (start, end)).fetchall()

    by_payment = db.execute("""
        SELECT payment_method, COUNT(*) as count, SUM(total) as total
        FROM sales WHERE date(created_at) BETWEEN ? AND ? AND status='completed'
        GROUP BY payment_method
    """, (start, end)).fetchall()

    hourly = db.execute("""
        SELECT strftime('%H', created_at) as hour, COUNT(*) as count, SUM(total) as total
        FROM sales WHERE date(created_at) BETWEEN ? AND ? AND status='completed'
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
    notes = db.execute("SELECT * FROM notes ORDER BY updated_at DESC").fetchall()
    return jsonify([dict(n) for n in notes])


@app.route('/api/notes', methods=['POST'])
@token_required
def create_note():
    data = request.json or {}
    db = get_db()
    db.execute("INSERT INTO notes (user_id, title, content) VALUES (?, ?, ?)",
               (g.current_user['id'], data.get('title', ''), data.get('content', '')))
    db.commit()
    return jsonify({'success': True})


@app.route('/api/notes/<int:nid>', methods=['PUT'])
@token_required
def update_note(nid):
    data = request.json or {}
    db = get_db()
    db.execute("UPDATE notes SET title=?, content=?, updated_at=? WHERE id=?",
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


# ── Web Dashboard Blueprint (optional; used by web_launcher.py) ──────────────
try:
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    from web.web_routes import web as web_blueprint
    app.register_blueprint(web_blueprint)
    logger.info("Web dashboard blueprint registered")
except Exception as _e:
    logger.warning(f"Web blueprint not loaded: {_e}")


if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', os.environ.get('FLASK_PORT', 5050)))
    app.run(host='0.0.0.0', port=port, debug=False)
