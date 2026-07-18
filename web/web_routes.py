"""
MBT POS — Web Dashboard Routes
MugoByte Technologies | mugobyte.com

Adds to the existing Flask backend:
  - Serves the React SPA (web/dashboard-ui/dist) at /
  - Adds /api/debt/* routes
  - Adds /api/customers routes
  - Adds /api/products/<id>/adjust route
  - All routes use the same token_required from backend/app.py
"""
import os
import json
import sqlite3
from datetime import datetime, date
from flask import Blueprint, send_from_directory, jsonify, request, g, current_app, abort

web = Blueprint('web', __name__)

# ── Resolve paths ─────────────────────────────────────────────────────────
_HERE     = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_HERE)
_WEB_DIR  = _HERE
_TMPL_DIR = os.path.join(_HERE, 'templates')
_DIST_DIR = os.path.join(_HERE, 'dashboard-ui', 'dist')
_LEGACY   = os.path.join(_TMPL_DIR, 'dashboard.legacy.html')


def _dist_ready():
    return os.path.isfile(os.path.join(_DIST_DIR, 'index.html'))


# ── Serve SPA ─────────────────────────────────────────────────────────────

@web.route('/')
def index():
    if _dist_ready():
        return send_from_directory(_DIST_DIR, 'index.html')
    # Fallback to legacy single-file SPA if React dist not built yet
    if os.path.isfile(_LEGACY):
        return send_from_directory(_TMPL_DIR, 'dashboard.legacy.html')
    legacy = os.path.join(_TMPL_DIR, 'dashboard.html')
    if os.path.isfile(legacy):
        return send_from_directory(_TMPL_DIR, 'dashboard.html')
    abort(503, description='Web dashboard not built. Run web/dashboard-ui build.')


@web.route('/assets/<path:filename>')
def spa_assets(filename):
    assets = os.path.join(_DIST_DIR, 'assets')
    if not os.path.isdir(assets):
        abort(404)
    return send_from_directory(assets, filename)


@web.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(os.path.join(_HERE, 'static'), filename)


@web.route('/<path:spa_path>')
def spa_fallback(spa_path):
    """Client-side routes (pos, inventory, …) — never steal /api/*."""
    if spa_path.startswith('api/') or spa_path == 'api':
        abort(404)
    # Prefer real files from dist (favicon, etc.)
    candidate = os.path.join(_DIST_DIR, spa_path)
    if _dist_ready() and os.path.isfile(candidate):
        return send_from_directory(_DIST_DIR, spa_path)
    if _dist_ready():
        return send_from_directory(_DIST_DIR, 'index.html')
    abort(404)


# ══════════════════════════════════════════════════════════════════════════
# CUSTOMERS API
# ══════════════════════════════════════════════════════════════════════════

def _get_db():
    """Get DB from Flask g (reuse backend connection if available)."""
    if 'db' not in g:
        from backend.app import DB_PATH
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def _tr(row):
    return dict(row) if row else None


def _trs(rows):
    return [dict(r) for r in rows]


def _user_tabs(user=None):
    user = user or getattr(g, 'current_user', None) or {}
    raw = user.get('tab_permissions')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or '[]')
        except Exception:
            raw = []
    if not isinstance(raw, list):
        raw = []
    role = (user.get('role') or 'cashier').lower()
    if role in ('admin', 'superadmin', 'manager'):
        return set(raw) | {
            'dashboard', 'sales', 'inventory', 'reports', 'debt', 'users',
            'settings', 'security', 'accounting', 'backup',
        }
    return set(raw or ['dashboard', 'sales'])


def _user_can(module, user=None):
    """Permission gate for AI / search surfaces (mirrors desktop tab access)."""
    user = user or getattr(g, 'current_user', None) or {}
    role = (user.get('role') or 'cashier').lower()
    if role in ('admin', 'superadmin'):
        return True
    tabs = _user_tabs(user)
    # Keep POS ops usable for cashiers (sales → product lookup) without granting
    # finance/management tabs via loose aliases (reports←dashboard, etc.).
    aliases = {
        'sales': {'dashboard', 'sales', 'pos'},
        'inventory': {'inventory', 'sales'},  # product search for POS only; use inventory_value for $
        'inventory_value': {'inventory', 'accounting', 'reports'},
        'debt': {'debt', 'customers'},
        'reports': {'reports'},
        'users': {'users'},
        'audit': {'security', 'users'},
        'backup': {'backup', 'settings', 'diagnostics'},
        'customers': {'debt', 'customers'},
        'payments': {'sales', 'reports', 'debt'},
    }
    need = aliases.get(module, {module})
    return bool(tabs & need) or role == 'manager'


class _WebPosApi:
    """API shim so desktop AI context builder can read live POS data over Flask."""

    def get_settings(self):
        db = _get_db()
        try:
            rows = db.execute("SELECT key, value FROM system_settings").fetchall()
            return {r['key']: r['value'] for r in rows}
        except Exception:
            return {}

    def get_sales(self, start=None, end=None):
        db = _get_db()
        q = (
            "SELECT id, receipt_number, cashier_id, cashier_name, total, discount, tax, "
            "payment_method, status, created_at "
            "FROM sales WHERE COALESCE(status,'completed')='completed'"
        )
        params = []
        if start:
            q += " AND date(created_at)>=?"
            params.append(str(start)[:10])
        if end:
            q += " AND date(created_at)<=?"
            params.append(str(end)[:10])
        user = getattr(g, 'current_user', None) or {}
        role = (user.get('role') or '').lower()
        if role == 'cashier' and user.get('id'):
            q += " AND cashier_id=?"
            params.append(user['id'])
        q += " ORDER BY created_at DESC LIMIT 500"
        rows = db.execute(q, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d['receipt_no'] = d.get('receipt_number')
            d['cashier'] = d.get('cashier_name')
            d['user_id'] = d.get('cashier_id')
            out.append(d)
        return out

    def get_products(self):
        if not _user_can('inventory'):
            return []
        db = _get_db()
        try:
            rows = db.execute(
                "SELECT id, name, sku, barcode, category, price, cost_price, stock, min_stock, "
                "quantity, reorder_level, unit, is_active "
                "FROM products WHERE COALESCE(is_active,1)=1"
            ).fetchall()
        except Exception:
            rows = db.execute(
                "SELECT id, name, sku, barcode, stock, min_stock, is_active "
                "FROM products WHERE COALESCE(is_active,1)=1"
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if 'quantity' not in d or d.get('quantity') is None:
                d['quantity'] = d.get('stock')
            if 'reorder_level' not in d or d.get('reorder_level') is None:
                d['reorder_level'] = d.get('min_stock')
            out.append(d)
        return out

    def get_customers(self, q=None):
        if not _user_can('customers'):
            return []
        db = _get_db()
        if q:
            like = f'%{q}%'
            rows = db.execute(
                "SELECT id, name, phone, email FROM customers "
                "WHERE name LIKE ? OR phone LIKE ? OR email LIKE ? LIMIT 50",
                (like, like, like),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id, name, phone, email FROM customers ORDER BY name LIMIT 100"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_debt_summary(self):
        if not _user_can('debt'):
            return {}
        db = _get_db()
        row = _tr(db.execute(
            "SELECT COUNT(*) as open_invoices, COALESCE(SUM(balance),0) as outstanding "
            "FROM debt_invoices WHERE status NOT IN ('paid','cancelled')"
        ).fetchone()) or {}
        return row


def _cfg_currency(db=None):
    db = db or _get_db()
    try:
        row = db.execute(
            "SELECT value FROM system_settings WHERE key='currency_symbol'"
        ).fetchone()
        return (row[0] if row and row[0] else 'KES')
    except Exception:
        return 'KES'


def _cc_today_snapshot(user=None):
    """Authoritative today stats for Command Center AI (never invent numbers)."""
    db = _get_db()
    today = str(date.today())
    user = user or getattr(g, 'current_user', None) or {}
    role = (user.get('role') or '').lower()
    sales_clause = "date(created_at)=? AND COALESCE(status,'completed')='completed'"
    params = [today]
    if role == 'cashier' and user.get('id'):
        sales_clause += " AND cashier_id=?"
        params.append(user['id'])

    sales_n = int(db.execute(
        f"SELECT COUNT(*) FROM sales WHERE {sales_clause}", params,
    ).fetchone()[0])
    rev = float((db.execute(
        f"SELECT COALESCE(SUM(total),0) FROM sales WHERE {sales_clause}", params,
    ).fetchone() or [0])[0])
    try:
        low = int(db.execute(
            "SELECT COUNT(*) FROM products WHERE COALESCE(is_active,1)=1 AND stock<=min_stock"
        ).fetchone()[0]) if _user_can('inventory', user) else 0
    except Exception:
        low = 0

    profit = _today_profit(db, today) if _user_can('reports', user) else None
    inv_val = _inventory_value(db) if _user_can('inventory_value', user) else None
    debt_out = None
    overdue = 0
    if _user_can('debt', user):
        debt_out = float((db.execute(
            "SELECT COALESCE(SUM(balance),0) FROM debt_invoices "
            "WHERE status NOT IN ('paid','cancelled')"
        ).fetchone() or [0])[0])
        overdue = int(db.execute(
            "SELECT COUNT(*) FROM debt_invoices WHERE status NOT IN ('paid','cancelled') "
            "AND due_date IS NOT NULL AND due_date < date('now')"
        ).fetchone()[0])

    by_pay = []
    if _user_can('payments', user) or _user_can('sales', user):
        by_pay = _trs(db.execute(
            f"SELECT payment_method, COUNT(*) as count, COALESCE(SUM(total),0) as total "
            f"FROM sales WHERE {sales_clause} GROUP BY payment_method ORDER BY total DESC",
            params,
        ).fetchall())

    top = []
    if _user_can('reports', user) or _user_can('sales', user):
        top = _trs(db.execute("""
            SELECT si.product_name, SUM(si.quantity) as qty_sold, SUM(si.total) as revenue
            FROM sale_items si JOIN sales s ON si.sale_id=s.id
            WHERE date(s.created_at)=? AND COALESCE(s.status,'completed')='completed'
            GROUP BY si.product_name ORDER BY revenue DESC LIMIT 5
        """, (today,)).fetchall())

    low_names = []
    if _user_can('inventory', user) and low:
        low_names = [
            r[0] for r in db.execute(
                "SELECT name FROM products WHERE COALESCE(is_active,1)=1 AND stock<=min_stock "
                "ORDER BY stock ASC LIMIT 8"
            ).fetchall()
        ]

    return {
        'today': today,
        'sales_count': sales_n,
        'revenue': rev,
        'low_stock': low,
        'low_stock_names': low_names,
        'currency': _cfg_currency(db),
        'profit': profit,
        'inventory_value': inv_val,
        'outstanding_debt': debt_out,
        'overdue_invoices': overdue,
        'by_payment': by_pay,
        'top_products': top,
        'monthly_revenue': _month_revenue(db) if _user_can('reports', user) else None,
        'scope': 'own_sales' if role == 'cashier' else 'shop',
    }


def _authorized_context_text(snap=None, user=None):
    """Permission-filtered ground truth block for AI prompts."""
    snap = snap or _cc_today_snapshot(user)
    cur = snap.get('currency') or 'KES'
    lines = [
        f"GROUND TRUTH for {snap['today']} (authoritative SQLite; do not invent numbers):",
        f"- Scope: {snap.get('scope', 'shop')}",
        f"- Sales count: {snap['sales_count']}",
        f"- Revenue: {cur} {float(snap['revenue']):,.2f}",
    ]
    if snap.get('profit') is not None:
        lines.append(f"- Est. profit: {cur} {float(snap['profit']):,.2f}")
    if snap.get('monthly_revenue') is not None:
        lines.append(f"- Month revenue: {cur} {float(snap['monthly_revenue']):,.2f}")
    if snap.get('inventory_value') is not None:
        lines.append(f"- Inventory value: {cur} {float(snap['inventory_value']):,.2f}")
        lines.append(f"- Low-stock SKUs: {snap.get('low_stock') or 0}")
        names = snap.get('low_stock_names') or []
        if names:
            lines.append(f"- Low-stock examples: {', '.join(names[:6])}")
    if snap.get('outstanding_debt') is not None:
        lines.append(f"- Outstanding debt: {cur} {float(snap['outstanding_debt']):,.2f}")
        lines.append(f"- Overdue invoices: {snap.get('overdue_invoices') or 0}")
    for p in (snap.get('by_payment') or [])[:6]:
        lines.append(
            f"- Pay {p.get('payment_method') or 'cash'}: "
            f"{int(p.get('count') or 0)} tx · {cur} {float(p.get('total') or 0):,.2f}"
        )
    for t in (snap.get('top_products') or [])[:5]:
        lines.append(
            f"- Top {t.get('product_name')}: qty {float(t.get('qty_sold') or 0):g} · "
            f"{cur} {float(t.get('revenue') or 0):,.2f}"
        )
    return '\n'.join(lines)


@web.route('/api/customers', methods=['GET'])
def list_customers():
    from backend.app import token_required
    @token_required
    def _inner():
        if not _user_can('customers') and not _user_can('debt') and not _user_can('sales'):
            return jsonify({'error': 'Forbidden'}), 403
        db = _get_db()
        q  = request.args.get('q', '').strip()
        if q:
            like = f'%{q}%'
            rows = db.execute(
                "SELECT c.*, COALESCE(SUM(di.balance),0) as total_outstanding, "
                "COUNT(di.id) as open_invoices "
                "FROM customers c "
                "LEFT JOIN debt_invoices di ON c.id=di.customer_id "
                "AND di.status NOT IN ('paid','cancelled') "
                "WHERE c.is_active=1 AND (c.name LIKE ? OR c.phone LIKE ? OR c.email LIKE ?) "
                "GROUP BY c.id ORDER BY c.name LIMIT 20",
                (like, like, like)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT c.*, COALESCE(SUM(di.balance),0) as total_outstanding, "
                "COUNT(di.id) as open_invoices "
                "FROM customers c "
                "LEFT JOIN debt_invoices di ON c.id=di.customer_id "
                "AND di.status NOT IN ('paid','cancelled') "
                "WHERE c.is_active=1 GROUP BY c.id ORDER BY c.name"
            ).fetchall()
        # Cashiers may look up customers for sales, but hide shop-wide debt totals
        out = _trs(rows)
        if not _user_can('debt') and not _user_can('reports'):
            for row in out:
                row.pop('total_outstanding', None)
                row.pop('open_invoices', None)
        return jsonify(out)
    return _inner()


@web.route('/api/customers', methods=['POST'])
def create_customer():
    from backend.app import token_required
    @token_required
    def _inner():
        data = request.json or {}
        if not data.get('name', '').strip():
            return jsonify({'error': 'Name is required'}), 400
        db = _get_db()
        try:
            db.execute(
                "INSERT INTO customers (name,phone,email,address,credit_limit,notes) "
                "VALUES (?,?,?,?,?,?)",
                (data['name'].strip(), data.get('phone',''), data.get('email',''),
                 data.get('address',''), float(data.get('credit_limit',0) or 0),
                 data.get('notes',''))
            )
            db.commit()
            cid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            return jsonify({'success': True, 'customer_id': cid})
        except sqlite3.IntegrityError:
            return jsonify({'error': 'Customer already exists'}), 400
    return _inner()


@web.route('/api/customers/<int:cid>', methods=['PUT'])
def update_customer(cid):
    from backend.app import token_required
    @token_required
    def _inner():
        data = request.json or {}
        db   = _get_db()
        fields, values = [], []
        for f in ('name','phone','email','address','credit_limit','notes','is_active'):
            if f in data:
                fields.append(f"{f}=?"); values.append(data[f])
        if fields:
            values.append(cid)
            db.execute(f"UPDATE customers SET {','.join(fields)} WHERE id=?", values)
            db.commit()
        return jsonify({'success': True})
    return _inner()


# ══════════════════════════════════════════════════════════════════════════
# DEBT INVOICES API
# ══════════════════════════════════════════════════════════════════════════

def _next_inv_num(db):
    today = datetime.now().strftime('%Y%m%d')
    count = db.execute(
        "SELECT COUNT(*) FROM debt_invoices WHERE date(created_at)=date('now')"
    ).fetchone()[0]
    return f"INV-{today}-{count+1:04d}"


def _next_pay_receipt(db):
    today = datetime.now().strftime('%Y%m%d')
    count = db.execute(
        "SELECT COUNT(*) FROM debt_payments WHERE date(created_at)=date('now')"
    ).fetchone()[0]
    return f"PAY-{today}-{count+1:04d}"


@web.route('/api/debt/summary', methods=['GET'])
def debt_summary():
    from backend.app import token_required
    @token_required
    def _inner():
        if not _user_can('debt'):
            return jsonify({'error': 'Forbidden'}), 403
        db    = _get_db()
        today = str(date.today())
        out   = _tr(db.execute("SELECT COALESCE(SUM(balance),0) as total, COUNT(*) as count FROM debt_invoices WHERE status NOT IN ('paid','cancelled')").fetchone())
        over  = _tr(db.execute("SELECT COALESCE(SUM(balance),0) as total, COUNT(*) as count FROM debt_invoices WHERE status NOT IN ('paid','cancelled') AND due_date IS NOT NULL AND due_date < date('now')").fetchone())
        col   = _tr(db.execute("SELECT COALESCE(SUM(amount),0) as total, COUNT(*) as count FROM debt_payments WHERE date(created_at)=?", (today,)).fetchone())
        debtors = _trs(db.execute("SELECT customer_name, COALESCE(SUM(balance),0) as total_balance FROM debt_invoices WHERE status NOT IN ('paid','cancelled') GROUP BY customer_id ORDER BY total_balance DESC LIMIT 5").fetchall())
        cust_count = db.execute("SELECT COUNT(DISTINCT customer_id) FROM debt_invoices WHERE status NOT IN ('paid','cancelled')").fetchone()[0]
        return jsonify({'outstanding': out, 'overdue': over, 'today_collected': col, 'top_debtors': debtors, 'customers_with_debt': cust_count})
    return _inner()


@web.route('/api/debt/invoices', methods=['GET'])
def list_debt_invoices():
    from backend.app import token_required
    @token_required
    def _inner():
        db     = _get_db()
        status = request.args.get('status','')
        start  = request.args.get('start','')
        end    = request.args.get('end','')
        clauses, params = [], []
        if status:
            if status == 'overdue':
                clauses.append("di.status NOT IN ('paid','cancelled') AND di.due_date IS NOT NULL AND di.due_date < date('now')")
            else:
                clauses.append("di.status=?"); params.append(status)
        if start: clauses.append("date(di.created_at)>=?"); params.append(start)
        if end:   clauses.append("date(di.created_at)<=?"); params.append(end)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = db.execute(
            f"SELECT di.*, c.phone as c_phone FROM debt_invoices di "
            f"JOIN customers c ON di.customer_id=c.id "
            f"{where} ORDER BY di.created_at DESC", params
        ).fetchall()
        return jsonify(_trs(rows))
    return _inner()


@web.route('/api/debt/invoices', methods=['POST'])
def create_debt_invoice():
    from backend.app import token_required
    @token_required
    def _inner():
        data = request.json or {}
        if not data.get('customer_id'):
            return jsonify({'error': 'customer_id required'}), 400
        db     = _get_db()
        cust   = _tr(db.execute("SELECT * FROM customers WHERE id=?", (data['customer_id'],)).fetchone())
        if not cust:
            return jsonify({'error': 'Customer not found'}), 404
        total   = round(float(data.get('total_amount') or 0), 2)
        paid    = round(float(data.get('amount_paid')  or 0), 2)
        balance = round(total - paid, 2)
        if total <= 0:
            return jsonify({'error': 'Total amount must be greater than zero'}), 400
        if balance < 0:
            return jsonify({'error': 'Amount paid exceeds total'}), 400
        inv_num = _next_inv_num(db)
        status  = 'paid' if balance == 0 else ('partial' if paid > 0 else 'pending')
        user    = g.current_user
        db.execute(
            "INSERT INTO debt_invoices (invoice_number,sale_id,receipt_number,"
            "customer_id,customer_name,customer_phone,total_amount,amount_paid,"
            "balance,status,due_date,cashier_id,cashier_name,notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (inv_num, data.get('sale_id'), data.get('receipt_number'),
             data['customer_id'], cust['name'], cust.get('phone',''),
             total, paid, balance, status,
             data.get('due_date') or None,
             user['id'], user.get('full_name') or user['username'],
             data.get('notes',''))
        )
        inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        if paid > 0:
            pay_r = _next_pay_receipt(db)
            db.execute(
                "INSERT INTO debt_payments (payment_receipt,invoice_id,customer_id,"
                "amount,payment_method,balance_before,balance_after,cashier_id,cashier_name,notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pay_r, inv_id, data['customer_id'], paid,
                 data.get('payment_method','cash'), total, balance,
                 user['id'], user.get('full_name') or user['username'],
                 f"Initial payment on {inv_num}")
            )
        db.commit()
        return jsonify({'success': True, 'invoice_number': inv_num, 'invoice_id': inv_id, 'balance': balance})
    return _inner()


@web.route('/api/debt/invoices/<int:inv_id>/pay', methods=['POST'])
def pay_debt_invoice(inv_id):
    from backend.app import token_required
    @token_required
    def _inner():
        data   = request.json or {}
        amount = round(float(data.get('amount') or 0), 2)
        if amount <= 0:
            return jsonify({'error': 'Amount must be greater than zero'}), 400
        db  = _get_db()
        inv = _tr(db.execute("SELECT * FROM debt_invoices WHERE id=?", (inv_id,)).fetchone())
        if not inv:
            return jsonify({'error': 'Invoice not found'}), 404
        if inv['status'] in ('paid', 'cancelled'):
            return jsonify({'error': f"Invoice is already {inv['status']}"}), 400
        bal_before = round(float(inv['balance']), 2)
        if amount > bal_before:
            return jsonify({'error': f"Payment ({amount:,.2f}) exceeds balance ({bal_before:,.2f})"}), 400
        bal_after  = round(bal_before - amount, 2)
        new_paid   = round(float(inv['amount_paid']) + amount, 2)
        new_status = 'paid' if bal_after == 0 else 'partial'
        pay_r      = _next_pay_receipt(db)
        user       = g.current_user
        db.execute(
            "INSERT INTO debt_payments (payment_receipt,invoice_id,customer_id,"
            "amount,payment_method,balance_before,balance_after,cashier_id,cashier_name,notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pay_r, inv_id, inv['customer_id'], amount,
             data.get('payment_method','cash'), bal_before, bal_after,
             user['id'], user.get('full_name') or user['username'],
             data.get('notes',''))
        )
        db.execute(
            "UPDATE debt_invoices SET amount_paid=?,balance=?,status=?,updated_at=? WHERE id=?",
            (new_paid, bal_after, new_status, datetime.now().isoformat(), inv_id)
        )
        db.commit()
        return jsonify({
            'success': True,
            'payment_receipt': pay_r,
            'balance_before': bal_before,
            'balance_after':  bal_after,
            'status': new_status,
            'invoice_number': inv['invoice_number'],
        })
    return _inner()


@web.route('/api/debt/payments', methods=['GET'])
def list_debt_payments():
    from backend.app import token_required
    @token_required
    def _inner():
        db    = _get_db()
        start = request.args.get('start','')
        end   = request.args.get('end','')
        clauses, params = [], []
        if start: clauses.append("date(dp.created_at)>=?"); params.append(start)
        if end:   clauses.append("date(dp.created_at)<=?"); params.append(end)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = db.execute(
            f"SELECT dp.*, di.invoice_number, di.receipt_number, "
            f"c.name as customer_name, c.phone "
            f"FROM debt_payments dp "
            f"JOIN debt_invoices di ON dp.invoice_id=di.id "
            f"JOIN customers c ON dp.customer_id=c.id "
            f"{where} ORDER BY dp.created_at DESC", params
        ).fetchall()
        return jsonify(_trs(rows))
    return _inner()


# ══════════════════════════════════════════════════════════════════════════
# STOCK ADJUSTMENT (web-accessible)
# ══════════════════════════════════════════════════════════════════════════

@web.route('/api/products/<int:pid>/adjust', methods=['POST'])
def adjust_stock(pid):
    from backend.app import token_required
    @token_required
    def _inner():
        if g.current_user.get('role') not in ('admin', 'superadmin'):
            return jsonify({'error': 'Admin access required'}), 403
        data    = request.json or {}
        try:
            new_qty = float(data.get('new_qty', 0))
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid quantity'}), 400
        reason  = (data.get('reason') or '').strip()
        if not reason:
            return jsonify({'error': 'Reason is required for stock adjustments'}), 400
        db  = _get_db()
        row = _tr(db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())
        if not row:
            return jsonify({'error': 'Product not found'}), 404
        old_qty    = float(row['stock'] or 0)
        qty_change = new_qty - old_qty
        user       = g.current_user
        db.execute("UPDATE products SET stock=?, updated_at=? WHERE id=?",
                   (new_qty, datetime.now().isoformat(), pid))
        db.execute(
            "INSERT INTO stock_movements "
            "(product_id,product_name,movement_type,qty_before,qty_change,"
            "qty_after,reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, row['name'], 'WEB_ADJUST', old_qty, qty_change, new_qty,
             f"WEB_pid={pid}", reason, user['id'],
             user.get('full_name') or user['username'])
        )
        db.commit()
        return jsonify({'success': True, 'old_stock': old_qty, 'new_stock': new_qty})
    return _inner()


# ══════════════════════════════════════════════════════════════════════════
# HTML DAILY REPORT (trading-bot style — standalone shareable file)
# ══════════════════════════════════════════════════════════════════════════

@web.route('/api/reports/html', methods=['GET'])
def html_report():
    from backend.app import token_required
    @token_required
    def _inner():
        from flask import Response
        import json as _json

        rdate = request.args.get('date', str(date.today()))
        db    = _get_db()

        # ── Gather data ────────────────────────────────────────────────────
        summary = _tr(db.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(total),0) as rev, "
            "COALESCE(SUM(discount),0) as disc, COALESCE(SUM(tax),0) as tax "
            "FROM sales WHERE date(created_at)=? AND status='completed'",
            (rdate,)).fetchone()) or {}

        # Top products
        top = _trs(db.execute(
            "SELECT si.product_name, SUM(si.quantity) as qty, "
            "SUM(si.total) as revenue "
            "FROM sale_items si JOIN sales s ON si.sale_id=s.id "
            "WHERE date(s.created_at)=? AND s.status='completed' "
            "GROUP BY si.product_name ORDER BY revenue DESC LIMIT 10",
            (rdate,)).fetchall())

        # Payment breakdown
        by_pay = _trs(db.execute(
            "SELECT payment_method, COUNT(*) as cnt, SUM(total) as rev "
            "FROM sales WHERE date(created_at)=? AND status='completed' "
            "GROUP BY payment_method ORDER BY rev DESC",
            (rdate,)).fetchall())

        # Hourly sales
        hourly = _trs(db.execute(
            "SELECT strftime('%H',created_at) as hr, COUNT(*) as cnt, SUM(total) as rev "
            "FROM sales WHERE date(created_at)=? AND status='completed' "
            "GROUP BY hr ORDER BY hr",
            (rdate,)).fetchall())

        # Low stock
        low_stock = _trs(db.execute(
            "SELECT name, stock, min_stock, unit FROM products "
            "WHERE stock<=min_stock AND is_active=1 ORDER BY stock ASC LIMIT 10"
        ).fetchall())

        # Settings
        cfg_rows = db.execute(
            "SELECT key, value FROM system_settings WHERE key IN "
            "('shop_name','currency_symbol','shop_phone','shop_address')"
        ).fetchall()
        cfg = {r['key']: r['value'] for r in cfg_rows}
        db.close()

        shop     = cfg.get('shop_name', 'MBT POS')
        currency = cfg.get('currency_symbol', 'KES')
        phone    = cfg.get('shop_phone', '')
        address  = cfg.get('shop_address', '')

        # ── Build HTML ─────────────────────────────────────────────────────
        top_json    = _json.dumps(top)
        hourly_json = _json.dumps(hourly)
        pay_json    = _json.dumps(by_pay)

        rev   = float(summary.get('rev', 0))
        cnt   = int(summary.get('cnt', 0))
        disc  = float(summary.get('disc', 0))
        tax   = float(summary.get('tax', 0))
        avg   = round(rev / cnt, 2) if cnt > 0 else 0

        low_rows = ''.join(
            f'<tr><td>{r["name"]}</td>'
            f'<td style="color:#ef4444;font-weight:700">{r["stock"]} {r.get("unit","pcs")}</td>'
            f'<td style="color:#9ca3af">min {r["min_stock"]}</td></tr>'
            for r in low_stock
        ) or '<tr><td colspan="3" style="color:#10b981">All stock levels OK ✓</td></tr>'

        html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sales Report — {shop} — {rdate}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  background:#0f172a;color:#e2e8f0;padding:24px;min-height:100vh}}
.container{{max-width:900px;margin:0 auto}}
.header{{background:#1e293b;border:1px solid #334155;border-radius:16px;
  padding:28px 32px;margin-bottom:24px}}
.shop-name{{font-size:24px;font-weight:800;color:#f8fafc;margin-bottom:4px}}
.shop-meta{{font-size:13px;color:#64748b;margin-bottom:2px}}
.report-date{{font-size:13px;color:#94a3b8;margin-top:8px}}
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));
  gap:16px;margin-bottom:24px}}
.kpi{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:20px}}
.kpi-label{{font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:.06em;color:#64748b;margin-bottom:8px}}
.kpi-value{{font-size:26px;font-weight:800;color:#f8fafc;line-height:1}}
.kpi-sub{{font-size:12px;color:#64748b;margin-top:4px}}
.card{{background:#1e293b;border:1px solid #334155;border-radius:12px;
  padding:20px 24px;margin-bottom:20px}}
.card-title{{font-size:15px;font-weight:700;color:#f8fafc;margin-bottom:16px}}
canvas{{max-height:260px}}
table{{width:100%;border-collapse:collapse}}
th{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;
  color:#64748b;text-align:left;padding:8px 12px;border-bottom:1px solid #334155}}
td{{padding:10px 12px;border-bottom:1px solid #1e293b;font-size:13px}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#263247}}
.footer{{text-align:center;margin-top:32px;font-size:12px;color:#475569}}
@media(max-width:600px){{.kpi-grid{{grid-template-columns:1fr 1fr}}
  body{{padding:12px}}}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="shop-name">{shop}</div>
    {"<div class='shop-meta'>" + address + "</div>" if address else ""}
    {"<div class='shop-meta'>" + phone + "</div>" if phone else ""}
    <div class="report-date">Daily Sales Report &nbsp;·&nbsp; {rdate} &nbsp;·&nbsp;
      Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
  </div>

  <div class="kpi-grid">
    <div class="kpi">
      <div class="kpi-label">Total Revenue</div>
      <div class="kpi-value" style="font-size:20px">{currency} {rev:,.2f}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Transactions</div>
      <div class="kpi-value">{cnt}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Avg Transaction</div>
      <div class="kpi-value" style="font-size:20px">{currency} {avg:,.2f}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Discounts Given</div>
      <div class="kpi-value" style="font-size:20px;color:#f59e0b">{currency} {disc:,.2f}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Tax Collected</div>
      <div class="kpi-value" style="font-size:20px">{currency} {tax:,.2f}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Low Stock Items</div>
      <div class="kpi-value" style="color:{'#ef4444' if low_stock else '#10b981'}">{len(low_stock)}</div>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px">
    <div class="card">
      <div class="card-title">Sales by Hour</div>
      <canvas id="hourlyChart"></canvas>
    </div>
    <div class="card">
      <div class="card-title">Payment Methods</div>
      <canvas id="payChart"></canvas>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Top Products</div>
    <table>
      <thead><tr><th>Product</th><th>Units Sold</th><th>Revenue</th></tr></thead>
      <tbody>
        {"".join(f'<tr><td>{p["product_name"]}</td><td>{float(p["qty"]):g}</td><td>{currency} {float(p["revenue"]):,.2f}</td></tr>' for p in top)
         or "<tr><td colspan='3' style='color:#64748b'>No sales today</td></tr>"}
      </tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-title">⚠ Stock Levels</div>
    <table>
      <thead><tr><th>Product</th><th>Current Stock</th><th>Minimum</th></tr></thead>
      <tbody>{low_rows}</tbody>
    </table>
  </div>

  <div class="footer">
    MBT POS &nbsp;·&nbsp; MugoByte Technologies &nbsp;·&nbsp; mugobyte.com
  </div>
</div>
<script>
const hourly = {hourly_json};
const payData = {pay_json};
const currency = "{currency}";

new Chart(document.getElementById('hourlyChart'), {{
  type: 'bar',
  data: {{
    labels: hourly.map(h => h.hr + ':00'),
    datasets: [{{
      label: 'Revenue',
      data: hourly.map(h => parseFloat(h.rev)),
      backgroundColor: '#3b82f680',
      borderColor: '#3b82f6',
      borderWidth: 1,
      borderRadius: 4,
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#64748b' }}, grid: {{ color: '#1e293b' }} }},
      y: {{ ticks: {{ color: '#64748b', callback: v => currency + ' ' + v.toLocaleString() }},
            grid: {{ color: '#334155' }} }}
    }}
  }}
}});

new Chart(document.getElementById('payChart'), {{
  type: 'doughnut',
  data: {{
    labels: payData.map(p => (p.payment_method || 'cash').toUpperCase()),
    datasets: [{{
      data: payData.map(p => parseFloat(p.rev)),
      backgroundColor: ['#3b82f6','#10b981','#f59e0b','#8b5cf6','#ef4444'],
      borderWidth: 0,
    }}]
  }},
  options: {{
    plugins: {{
      legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 12 }} }} }}
    }}
  }}
}});
</script>
</body>
</html>'''

        return Response(
            html,
            mimetype='text/html',
            headers={
                'Content-Disposition':
                    f'attachment; filename="MBT_Report_{rdate}.html"'
            }
        )
    return _inner()


# ══════════════════════════════════════════════════════════════════════════
# COMMAND CENTER — Approvals, Notifications, Health, Backup, Live, AI
# ══════════════════════════════════════════════════════════════════════════

_APPROVAL_TYPES = (
    'void', 'refund', 'large_discount', 'price_override',
    'stock_adjust', 'expense', 'credit',
)


def _ensure_command_center_schema(db):
    """Create durable tables used by the web command center (idempotent)."""
    db.executescript("""
    CREATE TABLE IF NOT EXISTS cc_approvals (
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
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_cc_approvals_status ON cc_approvals(status);

    CREATE TABLE IF NOT EXISTS cc_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT DEFAULT '',
        severity TEXT DEFAULT 'info',
        is_read INTEGER DEFAULT 0,
        link TEXT DEFAULT '',
        meta_json TEXT DEFAULT '{}',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_cc_notifications_created ON cc_notifications(created_at DESC);

    CREATE TABLE IF NOT EXISTS cc_backup_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT NOT NULL,
        reason TEXT DEFAULT 'manual',
        path TEXT DEFAULT '',
        size_bytes INTEGER DEFAULT 0,
        detail TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS cc_branches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        is_current INTEGER DEFAULT 0,
        address TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        meta_json TEXT DEFAULT '{}',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    # Seed default branch if empty
    n = db.execute("SELECT COUNT(*) FROM cc_branches").fetchone()[0]
    if not n:
        shop = 'Main Branch'
        try:
            row = db.execute(
                "SELECT value FROM system_settings WHERE key='shop_name'"
            ).fetchone()
            if row and row[0]:
                shop = str(row[0])
        except Exception:
            pass
        db.execute(
            "INSERT INTO cc_branches (code, name, is_active, is_current) VALUES (?,?,1,1)",
            ('MAIN', shop),
        )
    db.commit()


def _app_version_info():
    """Read version.json next to package root; fall back to known release."""
    ver_path = os.path.join(_BASE_DIR, 'version.json')
    info = {
        'version': '2.3.87',
        'build': 'PROD-2026-07-18-v2.3.87',
        'build_date': '2026-07-18',
        'exe': 'MBT_POS.exe',
    }
    try:
        if os.path.isfile(ver_path):
            with open(ver_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            info['version'] = data.get('version') or info['version']
            info['build'] = data.get('build') or info['build']
            info['build_date'] = data.get('build_date') or info['build_date']
    except Exception:
        pass
    return info


def _push_notification(db, ntype, title, body='', severity='info', link=''):
    db.execute(
        "INSERT INTO cc_notifications (type, title, body, severity, link) VALUES (?,?,?,?,?)",
        (ntype, title, body, severity, link),
    )


def _today_profit(db, day=None):
    day = day or str(date.today())
    row = db.execute("""
        SELECT COALESCE(SUM(
            si.total - (si.quantity * COALESCE(p.cost_price, 0))
        ), 0) AS profit
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        LEFT JOIN products p ON si.product_id = p.id
        WHERE date(s.created_at)=? AND s.status='completed'
    """, (day,)).fetchone()
    return float(row[0] if row else 0)


def _inventory_value(db):
    row = db.execute("""
        SELECT COALESCE(SUM(stock * COALESCE(NULLIF(cost_price,0), price, 0)), 0)
        FROM products WHERE is_active=1
    """).fetchone()
    return float(row[0] if row else 0)


def _month_revenue(db):
    today = date.today()
    start = today.replace(day=1).isoformat()
    end = today.isoformat()
    row = db.execute("""
        SELECT COALESCE(SUM(total),0) FROM sales
        WHERE date(created_at) BETWEEN ? AND ? AND status='completed'
    """, (start, end)).fetchone()
    return float(row[0] if row else 0)


def _month_expenses_proxy(db):
    """Best-effort expenses from accounting tables if present; else 0."""
    try:
        tables = {
            r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if 'acc_journal_lines' in tables and 'acc_accounts' in tables:
            today = date.today()
            start = today.replace(day=1).isoformat()
            row = db.execute("""
                SELECT COALESCE(SUM(jl.debit), 0)
                FROM acc_journal_lines jl
                JOIN acc_accounts a ON a.id = jl.account_id
                JOIN acc_journal_entries je ON je.id = jl.entry_id
                WHERE a.type='expense' AND date(je.entry_date) BETWEEN ? AND ?
            """, (start, today.isoformat())).fetchone()
            return float(row[0] if row else 0)
        if 'expenses' in tables:
            today = date.today()
            start = today.replace(day=1).isoformat()
            row = db.execute("""
                SELECT COALESCE(SUM(amount),0) FROM expenses
                WHERE date(created_at) BETWEEN ? AND ?
            """, (start, today.isoformat())).fetchone()
            return float(row[0] if row else 0)
    except Exception:
        pass
    return 0.0


def _seed_live_notifications(db):
    """Generate a few situational notifications if the feed is empty today."""
    today = str(date.today())
    cnt = db.execute(
        "SELECT COUNT(*) FROM cc_notifications WHERE date(created_at)=?",
        (today,),
    ).fetchone()[0]
    if cnt:
        return
    low = db.execute(
        "SELECT COUNT(*) FROM products WHERE is_active=1 AND stock<=min_stock"
    ).fetchone()[0]
    if low:
        _push_notification(
            db, 'low_stock', f'{low} product(s) low on stock',
            'Review Inventory and restock soon.', 'warn', '/inventory',
        )
    big = db.execute("""
        SELECT receipt_number, total FROM sales
        WHERE date(created_at)=? AND status='completed' AND total>=5000
        ORDER BY total DESC LIMIT 1
    """, (today,)).fetchone()
    if big:
        _push_notification(
            db, 'large_sale', f'Large sale {big[0]}',
            f'Receipt total {float(big[1]):,.2f}', 'info', '/reports',
        )
    pending_sync = db.execute(
        "SELECT COUNT(*) FROM sync_queue WHERE status='pending'"
    ).fetchone()[0]
    if pending_sync:
        _push_notification(
            db, 'sync', f'{pending_sync} sync item(s) pending',
            'Cloud sync queue has unsent items.', 'warn', '/live',
        )
    db.commit()


@web.route('/api/version', methods=['GET'])
def api_version():
    return jsonify(_app_version_info())


@web.route('/api/command-center/summary', methods=['GET'])
def cc_summary():
    from backend.app import token_required
    @token_required
    def _inner():
        db = _get_db()
        _ensure_command_center_schema(db)
        today = str(date.today())
        user = g.current_user or {}
        role = (user.get('role') or '').lower()
        sales_clause = "date(created_at)=? AND COALESCE(status,'completed')='completed'"
        params = [today]
        if role == 'cashier' and user.get('id'):
            sales_clause += " AND cashier_id=?"
            params.append(user['id'])
        sales = _tr(db.execute(f"""
            SELECT COUNT(*) as txns, COALESCE(SUM(total),0) as revenue,
                   COALESCE(AVG(total),0) as avg_txn,
                   COALESCE(SUM(discount),0) as discounts
            FROM sales WHERE {sales_clause}
        """, params).fetchone()) or {}
        debt_total = None
        if _user_can('debt', user):
            debt = _tr(db.execute(
                "SELECT COALESCE(SUM(balance),0) as total FROM debt_invoices "
                "WHERE status NOT IN ('paid','cancelled')"
            ).fetchone()) or {}
            debt_total = float(debt.get('total') or 0)
        profit = _today_profit(db, today) if _user_can('reports', user) else None
        inv_val = _inventory_value(db) if _user_can('inventory_value', user) else None
        month_rev = _month_revenue(db) if _user_can('reports', user) else None
        expenses = _month_expenses_proxy(db) if _user_can('reports', user) or _user_can('accounting', user) else None
        cash_flow = None
        if expenses is not None:
            cash_flow = float(sales.get('revenue') or 0) - float(expenses) / max(date.today().day, 1)
        return jsonify({
            'today': {
                'revenue': float(sales.get('revenue') or 0),
                'transactions': int(sales.get('txns') or 0),
                'avg_transaction': float(sales.get('avg_txn') or 0),
                'discounts': float(sales.get('discounts') or 0),
                'profit': profit,
            },
            'monthly_revenue': month_rev,
            'expenses': expenses,
            'inventory_value': inv_val,
            'outstanding_debts': debt_total,
            'cash_flow': cash_flow,
            'scope': 'own_sales' if role == 'cashier' else 'shop',
        })
    return _inner()


@web.route('/api/approvals', methods=['GET'])
def list_approvals():
    from backend.app import token_required
    @token_required
    def _inner():
        db = _get_db()
        _ensure_command_center_schema(db)
        status = (request.args.get('status') or '').strip()
        clauses, params = [], []
        if status:
            clauses.append('status=?')
            params.append(status)
        where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
        rows = db.execute(
            f"SELECT * FROM cc_approvals {where} ORDER BY "
            f"CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, "
            f"created_at DESC LIMIT 200",
            params,
        ).fetchall()
        return jsonify({'approvals': _trs(rows)})
    return _inner()


@web.route('/api/approvals', methods=['POST'])
def create_approval():
    from backend.app import token_required
    @token_required
    def _inner():
        data = request.json or {}
        atype = (data.get('type') or '').strip().lower()
        if atype not in _APPROVAL_TYPES:
            return jsonify({'error': f'Invalid type. Allowed: {", ".join(_APPROVAL_TYPES)}'}), 400
        title = (data.get('title') or atype.replace('_', ' ').title()).strip()
        details = (data.get('details') or '').strip()
        try:
            amount = float(data.get('amount') or 0)
        except (TypeError, ValueError):
            amount = 0.0
        user = g.current_user
        db = _get_db()
        _ensure_command_center_schema(db)
        cur = db.execute(
            "INSERT INTO cc_approvals "
            "(type, title, details, amount, status, requested_by, requested_by_id, meta_json) "
            "VALUES (?,?,?,?, 'pending',?,?,?)",
            (
                atype, title, details, amount,
                user.get('full_name') or user.get('username') or '',
                user.get('id'),
                json.dumps(data.get('meta') or {}),
            ),
        )
        _push_notification(
            db, atype, f'Approval requested: {title}',
            details or f'{atype} · {amount}', 'info', '/approvals',
        )
        db.commit()
        return jsonify({'success': True, 'id': cur.lastrowid})
    return _inner()


def _review_approval(aid, action):
    from backend.app import token_required
    @token_required
    def _inner():
        if g.current_user.get('role') not in ('admin', 'superadmin', 'manager'):
            return jsonify({'error': 'Manager or admin access required'}), 403
        data = request.json or {}
        note = (data.get('note') or '').strip()
        db = _get_db()
        _ensure_command_center_schema(db)
        row = _tr(db.execute("SELECT * FROM cc_approvals WHERE id=?", (aid,)).fetchone())
        if not row:
            return jsonify({'error': 'Not found'}), 404
        if row['status'] != 'pending':
            return jsonify({'error': f"Already {row['status']}"}), 400
        user = g.current_user
        status = 'approved' if action == 'approve' else 'rejected'
        db.execute(
            "UPDATE cc_approvals SET status=?, reviewed_by=?, reviewed_by_id=?, "
            "review_note=?, updated_at=? WHERE id=?",
            (
                status,
                user.get('full_name') or user.get('username') or '',
                user.get('id'),
                note,
                datetime.now().isoformat(),
                aid,
            ),
        )
        _push_notification(
            db, row['type'], f"Approval {status}: {row['title']}",
            note or row.get('details') or '',
            'ok' if status == 'approved' else 'warn',
            '/approvals',
        )
        db.commit()
        return jsonify({'success': True, 'status': status})
    return _inner()


@web.route('/api/approvals/<int:aid>/approve', methods=['POST'])
def approve_approval(aid):
    return _review_approval(aid, 'approve')


@web.route('/api/approvals/<int:aid>/reject', methods=['POST'])
def reject_approval(aid):
    return _review_approval(aid, 'reject')


@web.route('/api/notifications', methods=['GET'])
def list_notifications():
    from backend.app import token_required
    @token_required
    def _inner():
        db = _get_db()
        _ensure_command_center_schema(db)
        _seed_live_notifications(db)
        limit = min(int(request.args.get('limit') or 50), 200)
        rows = db.execute(
            "SELECT * FROM cc_notifications ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        unread = db.execute(
            "SELECT COUNT(*) FROM cc_notifications WHERE is_read=0"
        ).fetchone()[0]
        return jsonify({'notifications': _trs(rows), 'unread': unread})
    return _inner()


@web.route('/api/notifications/<int:nid>/read', methods=['POST'])
def mark_notification_read(nid):
    from backend.app import token_required
    @token_required
    def _inner():
        db = _get_db()
        _ensure_command_center_schema(db)
        db.execute("UPDATE cc_notifications SET is_read=1 WHERE id=?", (nid,))
        db.commit()
        return jsonify({'success': True})
    return _inner()


@web.route('/api/notifications/read-all', methods=['POST'])
def mark_all_notifications_read():
    from backend.app import token_required
    @token_required
    def _inner():
        db = _get_db()
        _ensure_command_center_schema(db)
        db.execute("UPDATE cc_notifications SET is_read=1 WHERE is_read=0")
        db.commit()
        return jsonify({'success': True})
    return _inner()


@web.route('/api/health/detail', methods=['GET'])
def health_detail():
    from backend.app import token_required
    @token_required
    def _inner():
        import shutil
        import time as _time
        db = _get_db()
        _ensure_command_center_schema(db)
        checks = []
        score = 0
        max_score = 0

        def add(key, label, ok, detail, weight=1, warn=False):
            nonlocal score, max_score
            max_score += weight
            if ok and not warn:
                score += weight
                state = 'healthy'
            elif ok and warn:
                score += weight * 0.5
                state = 'warn'
            else:
                state = 'err'
            checks.append({
                'key': key, 'label': label, 'state': state,
                'detail': detail, 'weight': weight,
            })

        # DB
        try:
            sales_n = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            add('db', 'Database', True, f'SQLite OK · {sales_n} sales records', 2)
        except Exception as e:
            add('db', 'Database', False, str(e), 2)

        # Storage
        try:
            usage = shutil.disk_usage(_BASE_DIR)
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            warn = free_gb < 5
            add('storage', 'Storage', free_gb > 1,
                f'{free_gb:.1f} GB free of {total_gb:.1f} GB', 1, warn=warn)
        except Exception as e:
            add('storage', 'Storage', False, str(e), 1)

        # Cloud / backup
        cloud_ok = False
        cloud_detail = 'Cloud backup not configured'
        try:
            from backend.cloud_backup.paths import is_cloud_configured, is_logged_in, load_json, backup_state_path
            if is_cloud_configured():
                cloud_ok = True
                st = load_json(backup_state_path(), {})
                last = st.get('last_success_at') or st.get('last_attempt_at') or 'never'
                cloud_detail = f"Configured · logged_in={is_logged_in()} · last={last}"
                if not is_logged_in():
                    add('cloud', 'Cloud', True, cloud_detail, 1, warn=True)
                else:
                    add('cloud', 'Cloud', True, cloud_detail, 1)
            else:
                add('cloud', 'Cloud', True, cloud_detail, 1, warn=True)
        except Exception as e:
            add('cloud', 'Cloud', False, str(e), 1)

        # AI
        try:
            from desktop.utils.ai.connectivity import get_connectivity
            conn = get_connectivity()
            if conn.configured and conn.online:
                add('ai', 'AI', True, 'AI configured and online', 1)
            elif conn.configured:
                add('ai', 'AI', True, 'AI configured but offline', 1, warn=True)
            else:
                add('ai', 'AI', True, 'AI not configured — local insights only', 1, warn=True)
        except Exception:
            add('ai', 'AI', True, 'AI module unavailable — heuristics only', 1, warn=True)

        # Backups (local history)
        try:
            last_bak = _tr(db.execute(
                "SELECT * FROM cc_backup_history ORDER BY created_at DESC LIMIT 1"
            ).fetchone())
            if last_bak:
                age_warn = last_bak.get('status') != 'ok'
                add('backups', 'Backups', True,
                    f"Last {last_bak.get('status')} at {last_bak.get('created_at')}",
                    1, warn=age_warn)
            else:
                add('backups', 'Backups', True, 'No local backup history yet', 1, warn=True)
        except Exception as e:
            add('backups', 'Backups', False, str(e), 1)

        # Sync
        try:
            pending = db.execute(
                "SELECT COUNT(*) FROM sync_queue WHERE status='pending'"
            ).fetchone()[0]
            add('sync', 'Sync', True,
                f'{pending} pending item(s)', 1, warn=pending > 0)
        except Exception as e:
            add('sync', 'Sync', False, str(e), 1)

        # API (self)
        t0 = _time.perf_counter()
        _ = datetime.now().isoformat()
        ms = int((_time.perf_counter() - t0) * 1000)
        add('api', 'API', True, f'Responding · ~{ms} ms', 1)

        # Security
        try:
            inactive = db.execute(
                "SELECT COUNT(*) FROM users WHERE is_active=0"
            ).fetchone()[0]
            admins = db.execute(
                "SELECT COUNT(*) FROM users WHERE role IN ('admin','superadmin') AND is_active=1"
            ).fetchone()[0]
            add('security', 'Security', admins > 0,
                f'{admins} admin(s) · {inactive} disabled user(s)', 1,
                warn=admins == 0)
        except Exception as e:
            add('security', 'Security', False, str(e), 1)

        pct = int(round(100 * score / max_score)) if max_score else 0
        overall = 'healthy' if pct >= 85 else ('warn' if pct >= 60 else 'err')
        return jsonify({
            'score': pct,
            'overall': overall,
            'checks': checks,
            'time': datetime.now().isoformat(),
            'version': _app_version_info(),
        })
    return _inner()


@web.route('/api/live', methods=['GET'])
def live_monitor():
    from backend.app import token_required
    @token_required
    def _inner():
        db = _get_db()
        _ensure_command_center_schema(db)
        today = str(date.today())
        sales = _tr(db.execute("""
            SELECT COUNT(*) as txns, COALESCE(SUM(total),0) as revenue
            FROM sales WHERE date(created_at)=? AND status='completed'
        """, (today,)).fetchone()) or {}
        cashiers = _trs(db.execute("""
            SELECT cashier_name as name, COUNT(*) as txns, COALESCE(SUM(total),0) as revenue
            FROM sales WHERE date(created_at)=? AND status='completed'
            GROUP BY cashier_name ORDER BY revenue DESC
        """, (today,)).fetchall())
        online_users = _trs(db.execute("""
            SELECT id, username, full_name, role, last_login
            FROM users WHERE is_active=1
            ORDER BY last_login DESC LIMIT 20
        """).fetchall())
        pending_sync = db.execute(
            "SELECT COUNT(*) FROM sync_queue WHERE status='pending'"
        ).fetchone()[0]
        last_bak = _tr(db.execute(
            "SELECT * FROM cc_backup_history ORDER BY created_at DESC LIMIT 1"
        ).fetchone())
        pending_approvals = db.execute(
            "SELECT COUNT(*) FROM cc_approvals WHERE status='pending'"
        ).fetchone()[0]
        ai_status = {'configured': False, 'online': False, 'label': 'Local heuristics'}
        try:
            from desktop.utils.ai.connectivity import get_connectivity
            conn = get_connectivity()
            ai_status = {
                'configured': bool(conn.configured),
                'online': bool(conn.online),
                'label': (
                    'Online' if conn.configured and conn.online
                    else ('Offline' if conn.configured else 'Not configured')
                ),
            }
        except Exception:
            pass
        return jsonify({
            'sales_today': {
                'transactions': int(sales.get('txns') or 0),
                'revenue': float(sales.get('revenue') or 0),
            },
            'cashiers': cashiers,
            'online_users': online_users,
            'sync': {'pending': pending_sync},
            'backup': last_bak or {'status': 'unknown'},
            'ai': ai_status,
            'pending_approvals': pending_approvals,
            'refreshed_at': datetime.now().isoformat(),
        })
    return _inner()


@web.route('/api/backup/status', methods=['GET'])
def backup_status():
    from backend.app import token_required
    @token_required
    def _inner():
        if not _user_can('backup'):
            return jsonify({'error': 'Forbidden'}), 403
        db = _get_db()
        _ensure_command_center_schema(db)
        history = _trs(db.execute(
            "SELECT * FROM cc_backup_history ORDER BY created_at DESC LIMIT 30"
        ).fetchall())
        last = history[0] if history else None
        cloud = {'configured': False, 'logged_in': False, 'state': {}}
        try:
            from backend.cloud_backup.paths import (
                is_cloud_configured, is_logged_in, load_json, backup_state_path,
            )
            cloud = {
                'configured': is_cloud_configured(),
                'logged_in': is_logged_in(),
                'state': load_json(backup_state_path(), {}),
            }
        except Exception as e:
            cloud['error'] = str(e)
        return jsonify({
            'last': last,
            'next_hint': 'Manual or scheduled via desktop Cloud Backup',
            'cloud': cloud,
            'history': history,
        })
    return _inner()


@web.route('/api/backup/run', methods=['POST'])
def backup_run():
    from backend.app import token_required, DB_PATH
    @token_required
    def _inner():
        if g.current_user.get('role') not in ('admin', 'superadmin', 'manager'):
            return jsonify({'error': 'Manager or admin access required'}), 403
        db = _get_db()
        _ensure_command_center_schema(db)
        reason = (request.json or {}).get('reason') or 'manual_web'
        detail = ''
        status = 'ok'
        path = ''
        size_bytes = 0

        # Prefer cloud backup when available
        try:
            from backend.cloud_backup import get_sync_manager
            from backend.cloud_backup.paths import is_cloud_configured, is_logged_in
            if is_cloud_configured() and is_logged_in():
                result = get_sync_manager().run_backup(reason=reason)
                if result.get('ok'):
                    detail = 'Cloud backup completed'
                    path = result.get('object_path') or result.get('path') or ''
                    size_bytes = int(result.get('size') or result.get('enc_size') or 0)
                else:
                    status = 'queued' if result.get('queued') else 'error'
                    detail = result.get('error') or 'Cloud backup failed'
            else:
                raise RuntimeError('cloud_unavailable')
        except Exception:
            # Local snapshot fallback
            try:
                import shutil
                bak_dir = os.path.join(_BASE_DIR, 'data', 'backups')
                os.makedirs(bak_dir, exist_ok=True)
                stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                path = os.path.join(bak_dir, f'mbt_pos_{stamp}.db')
                src = DB_PATH
                if os.path.isfile(src):
                    shutil.copy2(src, path)
                    size_bytes = os.path.getsize(path)
                    detail = 'Local SQLite snapshot created'
                else:
                    status = 'error'
                    detail = f'DB not found at {src}'
            except Exception as e:
                status = 'error'
                detail = str(e)

        db.execute(
            "INSERT INTO cc_backup_history (status, reason, path, size_bytes, detail) "
            "VALUES (?,?,?,?,?)",
            (status, reason, path, size_bytes, detail),
        )
        sev = 'ok' if status == 'ok' else 'err'
        _push_notification(
            db, 'backup', f'Backup {status}', detail, sev, '/backup',
        )
        db.commit()
        return jsonify({
            'success': status in ('ok', 'queued'),
            'status': status,
            'path': path,
            'size_bytes': size_bytes,
            'detail': detail,
        })
    return _inner()


@web.route('/api/branches', methods=['GET'])
def list_branches():
    from backend.app import token_required
    @token_required
    def _inner():
        db = _get_db()
        _ensure_command_center_schema(db)
        rows = _trs(db.execute(
            "SELECT * FROM cc_branches WHERE is_active=1 ORDER BY is_current DESC, name"
        ).fetchall())
        # Attach lightweight comparison metrics for current shop (same DB)
        today = str(date.today())
        rev = float((db.execute(
            "SELECT COALESCE(SUM(total),0) FROM sales "
            "WHERE date(created_at)=? AND status='completed'",
            (today,),
        ).fetchone() or [0])[0])
        for r in rows:
            if r.get('is_current'):
                r['today_revenue'] = rev
                r['products'] = db.execute(
                    "SELECT COUNT(*) FROM products WHERE is_active=1"
                ).fetchone()[0]
            else:
                r['today_revenue'] = None
                r['products'] = None
        return jsonify({'branches': rows})
    return _inner()


@web.route('/api/branches/<int:bid>/select', methods=['POST'])
def select_branch(bid):
    from backend.app import token_required
    @token_required
    def _inner():
        db = _get_db()
        _ensure_command_center_schema(db)
        row = _tr(db.execute(
            "SELECT * FROM cc_branches WHERE id=? AND is_active=1", (bid,)
        ).fetchone())
        if not row:
            return jsonify({'error': 'Branch not found'}), 404
        db.execute("UPDATE cc_branches SET is_current=0")
        db.execute("UPDATE cc_branches SET is_current=1 WHERE id=?", (bid,))
        db.commit()
        return jsonify({'success': True, 'branch': row})
    return _inner()


@web.route('/api/ai/insights', methods=['GET'])
def ai_insights():
    from backend.app import token_required
    @token_required
    def _inner():
        snap = _cc_today_snapshot(g.current_user)
        cur = snap.get('currency') or 'KES'
        sales_n = snap['sales_count']
        rev = float(snap['revenue'] or 0)
        low = int(snap.get('low_stock') or 0)
        overdue = int(snap.get('overdue_invoices') or 0)
        alerts, recs = [], []
        if low and _user_can('inventory'):
            alerts.append(f'{low} product(s) at or below reorder level.')
            names = snap.get('low_stock_names') or []
            if names:
                alerts.append('Examples: ' + ', '.join(names[:4]))
            recs.append('Open Inventory and review low-stock items.')
        if overdue and _user_can('debt'):
            alerts.append(f'{overdue} overdue credit account(s).')
            recs.append('Review Debt Management for collections.')
        if sales_n == 0:
            alerts.append('No sales recorded yet today.')
            recs.append('Start a sale from Point of Sale when ready.')
        if snap.get('outstanding_debt') and float(snap['outstanding_debt']) > 0 and _user_can('debt'):
            recs.append(
                f"Outstanding credit: {cur} {float(snap['outstanding_debt']):,.2f}."
            )
        if not alerts:
            alerts.append('No urgent local alerts detected.')
        if not recs:
            recs.append('Keep recording sales; refresh for deeper insights.')
        summary = f"Today: {sales_n} sales · {cur} {rev:,.2f}"
        if snap.get('profit') is not None:
            summary += f" · est. profit {cur} {float(snap['profit']):,.2f}"
        summary += '.'
        source = 'local'
        try:
            from desktop.utils.ai.connectivity import get_connectivity
            from desktop.utils.ai.service import get_ai_service
            conn = get_connectivity()
            if conn.configured and conn.online:
                svc = get_ai_service()
                prompt = (
                    f'{_authorized_context_text(snap)}\n'
                    'Reply JSON only: {"summary":"...","alerts":["..."],"recommendations":["..."]}'
                )
                result = svc.chat(
                    user_message=prompt,
                    api=_WebPosApi(),
                    user=g.current_user,
                    module='dashboard',
                    history=[],
                    stream_callback=None,
                    use_stream=False,
                )
                text = (result.get('text') or '').strip()
                import re
                m = re.search(r'\{.*\}', text, re.S)
                if m:
                    parsed = json.loads(m.group(0))
                    summary = str(parsed.get('summary') or summary)
                    alerts = list(parsed.get('alerts') or alerts)[:5]
                    recs = list(parsed.get('recommendations') or recs)[:5]
                    source = 'ai'
        except Exception:
            pass
        return jsonify({
            'summary': summary,
            'alerts': alerts[:5],
            'recommendations': recs[:5],
            'source': source,
            'offline': source == 'local',
            'snapshot': snap,
        })
    return _inner()


@web.route('/api/ai/chat', methods=['POST'])
def ai_chat():
    from backend.app import token_required
    @token_required
    def _inner():
        data = request.json or {}
        message = (data.get('message') or '').strip()
        if not message:
            return jsonify({'error': 'message required'}), 400
        snap = _cc_today_snapshot(g.current_user)
        cur = snap.get('currency') or 'KES'
        ml = message.lower()

        def _sales_reply():
            parts = [
                f"Today's sales: {snap['sales_count']} transaction(s), "
                f"{cur} {float(snap['revenue']):,.2f} revenue"
            ]
            if snap.get('profit') is not None:
                parts.append(f"est. profit {cur} {float(snap['profit']):,.2f}")
            if snap.get('scope') == 'own_sales':
                parts.append('(your receipts only)')
            return '. '.join(parts) + '.'

        # Exact shop numbers always come from SQLite — never from the model alone
        factual = None
        if any(k in ml for k in ('sale', 'sales', 'revenue', 'turnover', 'transaction')) and not any(
            k in ml for k in ('why', 'how to', 'improve', 'forecast')
        ):
            factual = _sales_reply()
        elif any(k in ml for k in ('profit', 'margin')) and snap.get('profit') is not None:
            factual = f"Today's estimated profit: {cur} {float(snap['profit']):,.2f}."
        elif any(k in ml for k in ('stock', 'inventory', 'reorder')) and _user_can('inventory'):
            names = snap.get('low_stock_names') or []
            factual = (
                f"{snap.get('low_stock') or 0} product(s) at/below reorder. "
                + (f"Examples: {', '.join(names)}. " if names else '')
                + (
                    f"Inventory value {cur} {float(snap['inventory_value']):,.2f}."
                    if snap.get('inventory_value') is not None else ''
                )
            )
        elif any(k in ml for k in ('debt', 'credit', 'overdue', 'receivable')) and _user_can('debt'):
            factual = (
                f"Outstanding debt: {cur} {float(snap.get('outstanding_debt') or 0):,.2f}. "
                f"Overdue invoices: {snap.get('overdue_invoices') or 0}."
            )
        elif any(k in ml for k in ('payment', 'mpesa', 'cash', 'card')) and snap.get('by_payment'):
            bits = [
                f"{(p.get('payment_method') or 'cash')}: {cur} {float(p.get('total') or 0):,.2f}"
                for p in snap['by_payment']
            ]
            factual = 'Today by payment — ' + '; '.join(bits) + '.'
        elif any(k in ml for k in ('top product', 'best sell', 'bestseller', 'top sell')) and snap.get('top_products'):
            bits = [
                f"{t.get('product_name')} ({cur} {float(t.get('revenue') or 0):,.2f})"
                for t in snap['top_products'][:5]
            ]
            factual = 'Top products today: ' + '; '.join(bits) + '.'
        elif 'month' in ml and snap.get('monthly_revenue') is not None:
            factual = f"This month's revenue: {cur} {float(snap['monthly_revenue']):,.2f}."

        if factual:
            return jsonify({'reply': factual.strip(), 'source': 'local', 'snapshot': snap})

        ground = f"{_authorized_context_text(snap)}\n\nOperator question: {message}"
        reply = None
        source = 'local'
        try:
            from desktop.utils.ai.connectivity import get_connectivity
            from desktop.utils.ai.service import get_ai_service
            conn = get_connectivity()
            if conn.configured and conn.online:
                svc = get_ai_service()
                result = svc.chat(
                    user_message=ground,
                    api=_WebPosApi(),
                    user=g.current_user,
                    module=data.get('module') or 'dashboard',
                    history=data.get('history') or [],
                    stream_callback=None,
                    use_stream=False,
                )
                reply = (result.get('text') or '').strip()
                if reply and not result.get('error'):
                    source = 'ai'
                else:
                    reply = None
        except Exception:
            reply = None
        if not reply:
            if 'backup' in ml:
                reply = 'Open Backup Center to view last backup status or trigger a manual backup.'
            elif 'health' in ml or 'sync' in ml:
                reply = 'Open System Health for scored checks (DB, storage, cloud, sync, AI).'
            else:
                reply = (
                    f"{_sales_reply()} "
                    f"Ask about sales, profit, stock, debt, payments, or top products."
                )
            source = 'local'
        return jsonify({
            'reply': reply,
            'source': source,
            'snapshot': snap,
        })
    return _inner()


# ══════════════════════════════════════════════════════════════════════════
# REPORTS DATA / EXPORT / SEARCH / LICENSE
# ══════════════════════════════════════════════════════════════════════════

def _report_filters_from_request():
    start = (request.args.get('start') or str(date.today()))[:10]
    end = (request.args.get('end') or start)[:10]
    return {
        'start': start,
        'end': end,
        'employee': (request.args.get('employee') or '').strip(),
        'payment': (request.args.get('payment') or '').strip(),
        'category': (request.args.get('category') or '').strip(),
        'customer': (request.args.get('customer') or '').strip(),
        'q': (request.args.get('q') or '').strip(),
    }


def _sales_where(filt, alias='s'):
    """Build WHERE for completed sales with optional filters. Returns (sql, params)."""
    p = alias + '.' if alias else ''
    clauses = [
        f"date({p}created_at) BETWEEN ? AND ?",
        f"COALESCE({p}status,'completed')='completed'",
    ]
    params = [filt['start'], filt['end']]
    # Cashiers only see their own receipts unless they have reports tab
    try:
        user = getattr(g, 'current_user', None) or {}
        role = (user.get('role') or '').lower()
        if role == 'cashier' and user.get('id') and not _user_can('reports', user):
            clauses.append(f"{p}cashier_id=?")
            params.append(user['id'])
    except Exception:
        pass
    if filt.get('employee'):
        clauses.append(f"({p}cashier_name LIKE ? OR CAST({p}cashier_id AS TEXT)=?)")
        params.extend([f"%{filt['employee']}%", filt['employee']])
    if filt.get('payment'):
        clauses.append(f"LOWER(COALESCE({p}payment_method,'')) = LOWER(?)")
        params.append(filt['payment'])
    if filt.get('q'):
        clauses.append(f"({p}receipt_number LIKE ? OR {p}cashier_name LIKE ?)")
        like = f"%{filt['q']}%"
        params.extend([like, like])
    return ' AND '.join(clauses), params


def _query_report_bundle(db, filt):
    where, params = _sales_where(filt, 's')
    sales = _trs(db.execute(f"""
        SELECT s.id, s.receipt_number, s.cashier_id, s.cashier_name, s.total, s.discount,
               s.tax, s.payment_method, s.status, s.created_at, s.customer_id
        FROM sales s WHERE {where}
        ORDER BY s.created_at DESC LIMIT 5000
    """, params).fetchall())

    if filt.get('category'):
        cat = filt['category']
        ids = {
            r[0] for r in db.execute("""
                SELECT DISTINCT s.id FROM sales s
                JOIN sale_items si ON si.sale_id=s.id
                LEFT JOIN products p ON p.id=si.product_id
                WHERE """ + where.replace('s.', 's.') + """
                AND (LOWER(COALESCE(p.category,''))=LOWER(?)
                     OR LOWER(COALESCE(si.product_name,'')) LIKE ?)
            """, params + [cat, f'%{cat.lower()}%']).fetchall()
        }
        sales = [s for s in sales if s['id'] in ids]

    if filt.get('customer'):
        like = f"%{filt['customer']}%"
        cust_ids = {
            r[0] for r in db.execute(
                "SELECT id FROM customers WHERE name LIKE ? OR phone LIKE ?",
                (like, like),
            ).fetchall()
        }
        sales = [s for s in sales if s.get('customer_id') in cust_ids]

    summary = {
        'total_transactions': len(sales),
        'total_revenue': sum(float(s.get('total') or 0) for s in sales),
        'total_discounts': sum(float(s.get('discount') or 0) for s in sales),
        'total_tax': sum(float(s.get('tax') or 0) for s in sales),
        'avg_transaction': 0.0,
    }
    if summary['total_transactions']:
        summary['avg_transaction'] = summary['total_revenue'] / summary['total_transactions']

    # Rebuild aggregates from filtered sales ids when category/customer filters applied
    sale_ids = [s['id'] for s in sales]
    top_products, by_payment, hourly, cashiers = [], [], [], []
    if sale_ids:
        placeholders = ','.join('?' * len(sale_ids))
        top_products = _trs(db.execute(f"""
            SELECT si.product_name, SUM(si.quantity) as qty_sold, SUM(si.total) as revenue
            FROM sale_items si WHERE si.sale_id IN ({placeholders})
            GROUP BY si.product_name ORDER BY revenue DESC LIMIT 50
        """, sale_ids).fetchall())
        pay_map, hour_map, cash_map = {}, {}, {}
        for s in sales:
            pm = (s.get('payment_method') or 'cash').lower()
            pay_map.setdefault(pm, {'payment_method': pm, 'count': 0, 'total': 0.0})
            pay_map[pm]['count'] += 1
            pay_map[pm]['total'] += float(s.get('total') or 0)
            hr = str(s.get('created_at') or '')[11:13] or '00'
            hour_map.setdefault(hr, {'hour': hr, 'count': 0, 'total': 0.0})
            hour_map[hr]['count'] += 1
            hour_map[hr]['total'] += float(s.get('total') or 0)
            cn = s.get('cashier_name') or '—'
            cash_map.setdefault(cn, {'cashier_name': cn, 'count': 0, 'total': 0.0})
            cash_map[cn]['count'] += 1
            cash_map[cn]['total'] += float(s.get('total') or 0)
        by_payment = sorted(pay_map.values(), key=lambda x: -x['total'])
        hourly = [hour_map[k] for k in sorted(hour_map.keys())]
        cashiers = sorted(cash_map.values(), key=lambda x: -x['total'])
    else:
        where2, params2 = _sales_where(filt, '')
        top_products = _trs(db.execute(f"""
            SELECT si.product_name, SUM(si.quantity) as qty_sold, SUM(si.total) as revenue
            FROM sale_items si JOIN sales ON si.sale_id=sales.id
            WHERE {where2.replace('created_at', 'sales.created_at').replace('status', 'sales.status')}
            GROUP BY si.product_name ORDER BY revenue DESC LIMIT 50
        """, params2).fetchall()) if False else []

    employees = [r[0] for r in db.execute(
        "SELECT DISTINCT cashier_name FROM sales WHERE cashier_name IS NOT NULL "
        "AND cashier_name!='' ORDER BY cashier_name"
    ).fetchall()]
    payments = [r[0] for r in db.execute(
        "SELECT DISTINCT payment_method FROM sales WHERE payment_method IS NOT NULL "
        "ORDER BY payment_method"
    ).fetchall()]
    categories = []
    try:
        categories = [r[0] for r in db.execute(
            "SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category!='' "
            "ORDER BY category"
        ).fetchall()]
    except Exception:
        pass

    shop = 'MBT POS'
    try:
        row = db.execute("SELECT value FROM system_settings WHERE key='shop_name'").fetchone()
        if row and row[0]:
            shop = row[0]
    except Exception:
        pass

    return {
        'filters': filt,
        'shop_name': shop,
        'currency': _cfg_currency(db),
        'summary': summary,
        'sales': sales,
        'top_products': top_products,
        'by_payment': by_payment,
        'hourly': hourly,
        'cashiers': cashiers,
        'meta': {
            'employees': employees,
            'payment_methods': payments,
            'categories': categories,
        },
    }


def _build_simple_pdf(title, shop, period, lines, currency='KES'):
    """Minimal branded PDF (no extra deps) — valid PDF 1.4 text document."""
    import io

    def esc(s):
        return str(s).replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

    content_lines = [
        'BT',
        '/F1 16 Tf',
        '50 780 Td',
        f'({esc(shop)}) Tj',
        '0 -24 Td',
        '/F1 12 Tf',
        f'({esc(title)}) Tj',
        '0 -16 Td',
        f'({esc(period)}) Tj',
        '0 -28 Td',
        '/F1 10 Tf',
    ]
    y_steps = 0
    for line in lines[:70]:
        content_lines.append(f'({esc(line[:110])}) Tj')
        content_lines.append('0 -13 Td')
        y_steps += 1
    content_lines.append('ET')
    stream = '\n'.join(content_lines).encode('latin-1', 'replace')

    objs = []
    objs.append(b'1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n')
    objs.append(b'2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n')
    objs.append(
        b'3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
        b'/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n'
    )
    objs.append(
        f'4 0 obj<< /Length {len(stream)} >>stream\n'.encode()
        + stream + b'\nendstream\nendobj\n'
    )
    objs.append(b'5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n')

    out = io.BytesIO()
    out.write(b'%PDF-1.4\n')
    offsets = [0]
    for obj in objs:
        offsets.append(out.tell())
        out.write(obj)
    xref = out.tell()
    out.write(f'xref\n0 {len(offsets)}\n'.encode())
    out.write(b'0000000000 65535 f \n')
    for off in offsets[1:]:
        out.write(f'{off:010d} 00000 n \n'.encode())
    out.write(
        f'trailer<< /Size {len(offsets)} /Root 1 0 R >>\n'
        f'startxref\n{xref}\n%%EOF\n'.encode()
    )
    return out.getvalue()


@web.route('/api/reports/data', methods=['GET'])
def reports_data():
    from backend.app import token_required
    @token_required
    def _inner():
        if not _user_can('reports') and not _user_can('sales'):
            return jsonify({'error': 'Forbidden'}), 403
        db = _get_db()
        filt = _report_filters_from_request()
        bundle = _query_report_bundle(db, filt)
        # Cap sales in JSON for UI; full set available via export
        ui_sales = bundle['sales'][:500]
        return jsonify({
            **{k: v for k, v in bundle.items() if k != 'sales'},
            'sales': ui_sales,
            'sales_truncated': len(bundle['sales']) > 500,
            'sales_total': len(bundle['sales']),
        })
    return _inner()


@web.route('/api/reports/export', methods=['GET'])
def reports_export():
    from backend.app import token_required
    from flask import Response, send_file
    import io
    import tempfile

    @token_required
    def _inner():
        fmt = (request.args.get('format') or 'xlsx').lower().strip()
        if fmt not in ('xlsx', 'csv', 'pdf', 'html'):
            return jsonify({'error': 'format must be xlsx, csv, pdf, or html'}), 400
        db = _get_db()
        who = (g.current_user or {}).get('full_name') or (g.current_user or {}).get('username') or 'Web'
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        if (request.args.get('inventory') or '') in ('1', 'true', 'yes'):
            if not _user_can('inventory'):
                return jsonify({'error': 'Forbidden'}), 403
            products = _WebPosApi().get_products()
            shop = 'MBT POS'
            try:
                row = db.execute(
                    "SELECT value FROM system_settings WHERE key='shop_name'"
                ).fetchone()
                if row and row[0]:
                    shop = row[0]
            except Exception:
                pass
            cur = _cfg_currency(db)
            if fmt == 'csv':
                buf = io.StringIO()
                import csv as _csv
                w = _csv.writer(buf)
                w.writerow(['Name', 'SKU', 'Category', 'Price', 'Cost', 'Stock', 'Min', 'Unit'])
                for p in products:
                    w.writerow([
                        p.get('name'), p.get('sku'), p.get('category'),
                        p.get('price'), p.get('cost_price'), p.get('stock'),
                        p.get('min_stock'), p.get('unit') or 'pcs',
                    ])
                data = ('\ufeff' + buf.getvalue()).encode('utf-8')
                return Response(
                    data, mimetype='text/csv; charset=utf-8',
                    headers={
                        'Content-Disposition':
                            f'attachment; filename="MBT_Inventory_{stamp}.csv"'
                    },
                )
            try:
                from backend.report_export_service import export_inventory_snapshot
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
                tmp.close()
                path = export_inventory_snapshot(
                    products, shop_name=shop, currency=cur,
                    generated_by=who, output_path=tmp.name,
                )
            except Exception:
                from backend.report_export_service import export_tabular_xlsx
                rows = [
                    [
                        p.get('name'), p.get('sku'), p.get('category'),
                        float(p.get('price') or 0), float(p.get('cost_price') or 0),
                        float(p.get('stock') or 0), float(p.get('min_stock') or 0),
                        p.get('unit') or 'pcs',
                    ]
                    for p in products
                ]
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
                tmp.close()
                path = export_tabular_xlsx(
                    title='Inventory',
                    headers=['Name', 'SKU', 'Category', 'Price', 'Cost', 'Stock', 'Min', 'Unit'],
                    rows=rows,
                    kinds=['text', 'text', 'text', 'currency', 'currency', 'qty', 'qty', 'text'],
                    shop_name=shop, generated_by=who, currency=cur, output_path=tmp.name,
                )
            return send_file(
                path, as_attachment=True,
                download_name=f'MBT_Inventory_{stamp}.xlsx',
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )

        if not _user_can('reports') and not _user_can('sales'):
            return jsonify({'error': 'Forbidden'}), 403
        filt = _report_filters_from_request()
        bundle = _query_report_bundle(db, filt)
        shop = bundle['shop_name']
        cur = bundle['currency']
        period = f"{filt['start']} to {filt['end']}"
        filt_desc = ', '.join(
            f'{k}={v}' for k, v in filt.items()
            if v and k not in ('start', 'end')
        ) or 'All sales'
        summary = bundle['summary']
        sales = bundle['sales']

        if fmt == 'html':
            rows_html = ''.join(
                f"<tr><td>{s.get('receipt_number')}</td><td>{(s.get('created_at') or '')[:16]}</td>"
                f"<td>{s.get('cashier_name') or ''}</td><td>{s.get('payment_method') or ''}</td>"
                f"<td style='text-align:right'>{cur} {float(s.get('total') or 0):,.2f}</td></tr>"
                for s in sales[:2000]
            )
            html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Sales Report — {shop}</title>
<style>
body{{font-family:Segoe UI,sans-serif;background:#0f172a;color:#e2e8f0;padding:24px}}
h1{{color:#f8fafc}} table{{width:100%;border-collapse:collapse;margin-top:16px}}
th,td{{padding:8px 10px;border-bottom:1px solid #334155;font-size:13px}}
th{{text-align:left;color:#94a3b8;font-size:11px;text-transform:uppercase}}
.kpi{{display:inline-block;margin:8px 16px 8px 0}} .kpi b{{display:block;font-size:20px;color:#fbbf24}}
@media print{{body{{background:#fff;color:#111}} th,td{{border-color:#ccc}}}}
</style></head><body>
<h1>{shop}</h1>
<div>Sales Report · {period} · {filt_desc}</div>
<div class="kpi"><span>Revenue</span><b>{cur} {summary['total_revenue']:,.2f}</b></div>
<div class="kpi"><span>Transactions</span><b>{summary['total_transactions']}</b></div>
<div class="kpi"><span>Avg</span><b>{cur} {summary['avg_transaction']:,.2f}</b></div>
<table><thead><tr><th>Receipt</th><th>When</th><th>Cashier</th><th>Pay</th><th>Total</th></tr></thead>
<tbody>{rows_html or '<tr><td colspan=5>No sales</td></tr>'}</tbody></table>
<p style="margin-top:24px;font-size:12px;opacity:.6">MBT POS · Generated {datetime.now().isoformat(timespec='seconds')} · {who}</p>
<script>window.onload=function(){{if(location.search.indexOf('print=1')>=0)window.print()}}</script>
</body></html>"""
            return Response(
                html, mimetype='text/html',
                headers={'Content-Disposition': f'inline; filename="MBT_Report_{stamp}.html"'},
            )

        if fmt == 'csv':
            buf = io.StringIO()
            import csv as _csv
            w = _csv.writer(buf)
            w.writerow(['MBT POS Sales Report', shop, period, filt_desc])
            w.writerow([])
            w.writerow(['Receipt', 'Date', 'Cashier', 'Payment', 'Discount', 'Tax', 'Total', 'Status'])
            for s in sales:
                w.writerow([
                    s.get('receipt_number'), s.get('created_at'), s.get('cashier_name'),
                    s.get('payment_method'), s.get('discount'), s.get('tax'),
                    s.get('total'), s.get('status'),
                ])
            w.writerow([])
            w.writerow(['TOTAL', '', '', '', summary['total_discounts'], summary['total_tax'],
                        summary['total_revenue'], f"{summary['total_transactions']} txns"])
            data = ('\ufeff' + buf.getvalue()).encode('utf-8')
            return Response(
                data, mimetype='text/csv; charset=utf-8',
                headers={'Content-Disposition': f'attachment; filename="MBT_Sales_{stamp}.csv"'},
            )

        if fmt == 'pdf':
            lines = [
                f"Revenue: {cur} {summary['total_revenue']:,.2f}",
                f"Transactions: {summary['total_transactions']}",
                f"Average: {cur} {summary['avg_transaction']:,.2f}",
                f"Discounts: {cur} {summary['total_discounts']:,.2f}",
                f"Filters: {filt_desc}",
                '',
                'Top products:',
            ]
            for t in (bundle.get('top_products') or [])[:15]:
                lines.append(
                    f"  {t.get('product_name')}: qty {float(t.get('qty_sold') or 0):g} · "
                    f"{cur} {float(t.get('revenue') or 0):,.2f}"
                )
            lines.append('')
            lines.append('Recent receipts:')
            for s in sales[:40]:
                lines.append(
                    f"  {s.get('receipt_number')}  {(s.get('created_at') or '')[:16]}  "
                    f"{s.get('cashier_name') or ''}  {cur} {float(s.get('total') or 0):,.2f}"
                )
            lines.append('')
            lines.append(f'Generated by {who} · MBT POS')
            pdf = _build_simple_pdf('Sales Report', shop, period, lines, cur)
            return Response(
                pdf, mimetype='application/pdf',
                headers={'Content-Disposition': f'attachment; filename="MBT_Sales_{stamp}.pdf"'},
            )

        # xlsx — prefer shared export engine when possible
        try:
            from backend.export_engine import export_sales_report
            items_by_sale = {}
            if sales:
                ids = [s['id'] for s in sales]
                # chunk IN queries
                for i in range(0, len(ids), 400):
                    chunk = ids[i:i + 400]
                    ph = ','.join('?' * len(chunk))
                    for row in db.execute(
                        f"SELECT * FROM sale_items WHERE sale_id IN ({ph})", chunk
                    ).fetchall():
                        d = dict(row)
                        items_by_sale.setdefault(d['sale_id'], []).append(d)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
            tmp.close()
            path = export_sales_report(
                sales, items_by_sale, shop_name=shop,
                start_date=filt['start'], end_date=filt['end'],
                output_path=tmp.name, currency=cur,
                products_data=_WebPosApi().get_products() if _user_can('inventory') else None,
                generated_by=who, filters=filt_desc,
            )
            return send_file(
                path, as_attachment=True,
                download_name=f'MBT_Sales_{stamp}.xlsx',
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except Exception:
            from backend.report_export_service import export_tabular_xlsx
            rows = [
                [
                    s.get('receipt_number'), s.get('created_at'), s.get('cashier_name'),
                    s.get('payment_method'), float(s.get('discount') or 0),
                    float(s.get('tax') or 0), float(s.get('total') or 0),
                    s.get('status'),
                ]
                for s in sales
            ]
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
            tmp.close()
            path = export_tabular_xlsx(
                title='Sales Report',
                headers=['Receipt', 'Date', 'Cashier', 'Payment', 'Discount', 'Tax', 'Total', 'Status'],
                rows=rows,
                kinds=['text', 'datetime', 'text', 'text', 'currency', 'currency', 'currency', 'text'],
                shop_name=shop, period=period, generated_by=who, filters=filt_desc,
                currency=cur, output_path=tmp.name,
                total_cols={5: (summary['total_discounts'], 'currency'),
                            6: (summary['total_tax'], 'currency'),
                            7: (summary['total_revenue'], 'currency')},
            )
            return send_file(
                path, as_attachment=True,
                download_name=f'MBT_Sales_{stamp}.xlsx',
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
    return _inner()


@web.route('/api/search', methods=['GET'])
def global_search():
    from backend.app import token_required
    @token_required
    def _inner():
        q = (request.args.get('q') or '').strip()
        if len(q) < 2:
            return jsonify({'results': [], 'q': q})
        like = f'%{q}%'
        db = _get_db()
        results = []
        if _user_can('sales') or _user_can('reports'):
            for r in db.execute("""
                SELECT id, receipt_number, total, cashier_name, created_at
                FROM sales WHERE receipt_number LIKE ? OR cashier_name LIKE ?
                ORDER BY created_at DESC LIMIT 8
            """, (like, like)).fetchall():
                results.append({
                    'type': 'sale', 'id': r['id'],
                    'title': r['receipt_number'] or f"Sale #{r['id']}",
                    'subtitle': f"{r['cashier_name'] or ''} · {r['created_at']}",
                    'meta': float(r['total'] or 0),
                    'href': '/reports',
                })
        if _user_can('inventory'):
            for r in db.execute("""
                SELECT id, name, sku, stock, price FROM products
                WHERE COALESCE(is_active,1)=1 AND (name LIKE ? OR sku LIKE ? OR barcode LIKE ?)
                ORDER BY name LIMIT 8
            """, (like, like, like)).fetchall():
                results.append({
                    'type': 'product', 'id': r['id'],
                    'title': r['name'],
                    'subtitle': f"SKU {r['sku'] or '—'} · stock {r['stock']}",
                    'meta': float(r['price'] or 0),
                    'href': '/inventory',
                })
        if _user_can('customers') or _user_can('debt'):
            for r in db.execute("""
                SELECT id, name, phone FROM customers
                WHERE name LIKE ? OR phone LIKE ? OR email LIKE ?
                ORDER BY name LIMIT 8
            """, (like, like, like)).fetchall():
                results.append({
                    'type': 'customer', 'id': r['id'],
                    'title': r['name'],
                    'subtitle': r['phone'] or '',
                    'href': '/debt',
                })
        if _user_can('users'):
            for r in db.execute("""
                SELECT id, username, full_name, role FROM users
                WHERE username LIKE ? OR full_name LIKE ?
                LIMIT 5
            """, (like, like)).fetchall():
                results.append({
                    'type': 'user', 'id': r['id'],
                    'title': r['full_name'] or r['username'],
                    'subtitle': f"{r['role']} · @{r['username']}",
                    'href': '/users',
                })
        return jsonify({'results': results, 'q': q})
    return _inner()


@web.route('/api/license/status', methods=['GET'])
def license_status():
    from backend.app import token_required
    @token_required
    def _inner():
        role = (g.current_user or {}).get('role', '')
        if role not in ('admin', 'superadmin', 'manager'):
            return jsonify({'error': 'Forbidden'}), 403
        info = {
            'state': 'unknown',
            'is_valid': False,
            'plan': '—',
            'plan_name': 'Unavailable',
            'days_remaining': None,
            'expiry_date': None,
            'device_id': None,
            'source': 'fallback',
        }
        try:
            from licensing.license_engine import LicenseEngine
            engine = LicenseEngine(_BASE_DIR)
            engine.revalidate()
            info = engine.get_status_dict()
            info['source'] = 'license_engine'
        except Exception as e:
            info['error'] = str(e)
            # Soft fallback from version / settings
            ver = _app_version_info()
            info.update({
                'plan_name': 'MBT POS',
                'state': 'unknown',
                'version': ver.get('version'),
            })
        return jsonify(info)
    return _inner()
