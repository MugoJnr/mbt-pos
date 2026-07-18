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


class _WebPosApi:
    """Minimal API so desktop AI context builder can read live POS data over Flask."""

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
            "SELECT id, receipt_number, cashier_id, cashier_name, total, status, created_at "
            "FROM sales WHERE COALESCE(status,'completed')='completed'"
        )
        params = []
        if start:
            q += " AND date(created_at)>=?"
            params.append(str(start)[:10])
        if end:
            q += " AND date(created_at)<=?"
            params.append(str(end)[:10])
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
        db = _get_db()
        try:
            rows = db.execute(
                "SELECT id, name, sku, barcode, stock, min_stock, quantity, reorder_level, is_active "
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


def _cc_today_snapshot():
    """Authoritative today stats for Command Center AI (never invent numbers)."""
    db = _get_db()
    today = str(date.today())
    sales_n = int(db.execute(
        "SELECT COUNT(*) FROM sales WHERE date(created_at)=? AND COALESCE(status,'completed')='completed'",
        (today,),
    ).fetchone()[0])
    rev = float((db.execute(
        "SELECT COALESCE(SUM(total),0) FROM sales "
        "WHERE date(created_at)=? AND COALESCE(status,'completed')='completed'",
        (today,),
    ).fetchone() or [0])[0])
    try:
        low = int(db.execute(
            "SELECT COUNT(*) FROM products WHERE COALESCE(is_active,1)=1 AND stock<=min_stock"
        ).fetchone()[0])
    except Exception:
        low = 0
    return {
        'today': today,
        'sales_count': sales_n,
        'revenue': rev,
        'low_stock': low,
        'currency': 'KES',
    }


@web.route('/api/customers', methods=['GET'])
def list_customers():
    from backend.app import token_required
    @token_required
    def _inner():
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
        return jsonify(_trs(rows))
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
        sales = _tr(db.execute("""
            SELECT COUNT(*) as txns, COALESCE(SUM(total),0) as revenue,
                   COALESCE(AVG(total),0) as avg_txn,
                   COALESCE(SUM(discount),0) as discounts
            FROM sales WHERE date(created_at)=? AND status='completed'
        """, (today,)).fetchone()) or {}
        debt = _tr(db.execute(
            "SELECT COALESCE(SUM(balance),0) as total FROM debt_invoices "
            "WHERE status NOT IN ('paid','cancelled')"
        ).fetchone()) or {}
        profit = _today_profit(db, today)
        inv_val = _inventory_value(db)
        month_rev = _month_revenue(db)
        expenses = _month_expenses_proxy(db)
        cash_flow = float(sales.get('revenue') or 0) - expenses / max(date.today().day, 1)
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
            'outstanding_debts': float(debt.get('total') or 0),
            'cash_flow': cash_flow,
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
        db = _get_db()
        today = str(date.today())
        sales_n = db.execute(
            "SELECT COUNT(*) FROM sales WHERE date(created_at)=? AND status='completed'",
            (today,),
        ).fetchone()[0]
        rev = float((db.execute(
            "SELECT COALESCE(SUM(total),0) FROM sales "
            "WHERE date(created_at)=? AND status='completed'",
            (today,),
        ).fetchone() or [0])[0])
        low = db.execute(
            "SELECT COUNT(*) FROM products WHERE is_active=1 AND stock<=min_stock"
        ).fetchone()[0]
        overdue = db.execute(
            "SELECT COUNT(*) FROM debt_invoices WHERE status NOT IN ('paid','cancelled') "
            "AND due_date IS NOT NULL AND due_date < date('now')"
        ).fetchone()[0]
        alerts, recs = [], []
        if low:
            alerts.append(f'{low} product(s) at or below reorder level.')
            recs.append('Open Inventory and review low-stock items.')
        if overdue:
            alerts.append(f'{overdue} overdue credit account(s).')
            recs.append('Review Debt Management for collections.')
        if sales_n == 0:
            alerts.append('No sales recorded yet today.')
            recs.append('Start a sale from Point of Sale when ready.')
        if not alerts:
            alerts.append('No urgent local alerts detected.')
        if not recs:
            recs.append('Keep recording sales; refresh for deeper insights.')
        summary = f'Today: {sales_n} sales · revenue {rev:,.2f}.'
        # Attempt real AI if available
        source = 'local'
        try:
            from desktop.utils.ai.connectivity import get_connectivity
            from desktop.utils.ai.service import get_ai_service
            conn = get_connectivity()
            if conn.configured and conn.online:
                svc = get_ai_service()
                prompt = (
                    f'POS context: {summary} Low stock: {low}. Overdue debts: {overdue}. '
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
        snap = _cc_today_snapshot()
        ml = message.lower()
        factual_sales = any(k in ml for k in (
            'sale', 'sales', 'revenue', 'today', 'transaction', 'turnover',
        )) and not any(k in ml for k in ('why', 'how to', 'improve', 'forecast', 'trend'))

        def _sales_reply():
            return (
                f"Today's sales: {snap['sales_count']} transaction(s), "
                f"{snap['currency']} {snap['revenue']:,.2f} revenue."
            )

        # Exact shop numbers always come from SQLite — never from the model alone
        if factual_sales:
            return jsonify({
                'reply': _sales_reply(),
                'source': 'local',
                'snapshot': snap,
            })

        ground = (
            f"GROUND TRUTH (authoritative POS DB for {snap['today']}; "
            f"use these exact numbers — do not invent):\n"
            f"- Today's sales count: {snap['sales_count']}\n"
            f"- Today's revenue: {snap['currency']} {snap['revenue']:,.2f}\n"
            f"- Low-stock products: {snap['low_stock']}\n\n"
            f"Operator question: {message}"
        )
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
            low = snap['low_stock']
            if 'stock' in ml or 'inventory' in ml:
                reply = f'{low} product(s) are at or below reorder level. Open Inventory to review.'
            elif 'backup' in ml:
                reply = 'Open Backup Center to view last backup status or trigger a manual backup.'
            elif 'debt' in ml or 'credit' in ml:
                reply = 'Open Debt Management for outstanding balances and collections.'
            else:
                reply = (
                    f"{_sales_reply()} "
                    f'{low} low-stock item(s). Ask about sales, stock, debt, or backup.'
                )
            source = 'local'
        return jsonify({
            'reply': reply,
            'source': source,
            'snapshot': snap,
        })
    return _inner()
