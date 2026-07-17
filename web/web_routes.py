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
