"""Cashier requests to record sales on a previous business day.

Drafts and submitted requests do not create sales, stock movements, or debts.
Approval posts every sale in one database transaction, exactly once.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from desktop.utils.shop_time import business_day_iso, parse_sale_date, shop_today


class BackdateError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


_REQUEST_ROLES = {'cashier', 'manager', 'admin', 'superadmin'}
_REVIEW_ROLES = {'manager', 'admin', 'superadmin'}
_OPEN_FOR_CASHIER = {'draft', 'returned'}
_TERMINAL = {'approved', 'rejected', 'withdrawn'}
_CREDIT = {'credit', 'credit sale', 'part payment', 'part-payment'}
_MPESA = {'m-pesa', 'mpesa', 'airtel money'}
_BANK = {'card', 'bank', 'bank transfer', 'cheque'}


def ensure_schema(db) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS backdate_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            cashier_id INTEGER NOT NULL,
            cashier_name TEXT,
            business_date TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            review_note TEXT,
            reviewer_id INTEGER,
            reviewer_name TEXT,
            replaces_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            submitted_at TEXT,
            decided_at TEXT
        );
        CREATE TABLE IF NOT EXISTS backdate_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            sort_order INTEGER DEFAULT 0,
            customer_id INTEGER,
            customer_name TEXT,
            payment_method TEXT DEFAULT 'Cash',
            amount_paid REAL DEFAULT 0,
            cash_paid REAL DEFAULT 0,
            electronic_paid REAL DEFAULT 0,
            mpesa_ref TEXT,
            notes TEXT,
            due_date TEXT,
            posted_sale_id INTEGER,
            posted_receipt TEXT
        );
        CREATE TABLE IF NOT EXISTS backdate_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backdate_sale_id INTEGER NOT NULL,
            product_id INTEGER,
            product_name TEXT,
            quantity REAL NOT NULL,
            unit_price REAL NOT NULL,
            discount REAL DEFAULT 0,
            total REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS backdate_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            version INTEGER,
            action TEXT NOT NULL,
            actor_id INTEGER,
            actor_name TEXT,
            note TEXT,
            snapshot TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    cols = {row[1] for row in db.execute("PRAGMA table_info(sales)").fetchall()}
    if 'backdate_request_id' not in cols:
        db.execute("ALTER TABLE sales ADD COLUMN backdate_request_id INTEGER")
    if 'client_token' not in cols:
        db.execute("ALTER TABLE sales ADD COLUMN client_token TEXT")
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_client_token "
        "ON sales(client_token) WHERE client_token IS NOT NULL AND client_token != ''"
    )
    for name, ddl in (
        ('actor_role', 'TEXT'),
        ('previous_status', 'TEXT'),
        ('new_status', 'TEXT'),
        ('sale_reference', 'TEXT'),
        ('reversal_reference', 'TEXT'),
        ('bulk_id', 'TEXT'),
    ):
        _add_column(db, 'backdate_events', name, ddl)
    db.commit()


def create_request(db, actor: dict, data: dict) -> dict:
    ensure_schema(db)
    _require_request(actor)
    day = _past_day(data.get('business_date') or data.get('sale_date'))
    replaces = data.get('replaces_id')
    now = _now()
    db.execute('BEGIN IMMEDIATE')
    try:
        if replaces:
            prior = _locked(db, int(replaces))
            if not prior or prior['status'] not in ('rejected', 'withdrawn'):
                raise BackdateError('A new request can only follow a rejected or withdrawn one.')
            if not _can_review(actor) and int(prior['cashier_id']) != int(actor['id']):
                raise BackdateError('You cannot replace another cashier\'s request.', 403)
        blocked = _date_policy(db, day)
        if blocked:
            raise BackdateError(blocked)
        reference = _next_reference(db)
        name = actor.get('full_name') or actor.get('username') or ''
        db.execute(
            """INSERT INTO backdate_requests
               (reference, cashier_id, cashier_name, business_date, reason, status,
                version, replaces_id, created_at, updated_at)
               VALUES (?,?,?,?,?,'draft',1,?,?,?)""",
            (reference, actor['id'], name, day, (data.get('reason') or '').strip(),
             int(replaces) if replaces else None, now, now),
        )
        request_id = _last_id(db)
        _replace_sales(db, request_id, data.get('sales') or [])
        _event(db, request_id, 1, 'created', actor, data.get('reason') or '', None)
        _audit(db, actor, 'BACKDATE_CREATED', reference)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_request(db, actor, request_id)


def update_request(db, actor: dict, request_id: int, data: dict) -> dict:
    ensure_schema(db)
    db.execute('BEGIN IMMEDIATE')
    try:
        row = _locked(db, request_id)
        _editable(row, actor, data.get('version'))
        before = _snapshot(db, row)
        if row['status'] == 'submitted' and data.get('business_date'):
            requested = _past_day(data.get('business_date'))
            if requested != row['business_date']:
                raise BackdateError(
                    'The business date cannot change after the request is submitted.'
                )
        if data.get('business_date'):
            day = _past_day(data.get('business_date'))
        else:
            day = row['business_date']
        blocked = _date_policy(db, day)
        if blocked:
            raise BackdateError(blocked)
        reason = row['reason'] if data.get('reason') is None else (data.get('reason') or '').strip()
        version = int(row['version']) + 1
        db.execute(
            """UPDATE backdate_requests
               SET business_date=?, reason=?, version=?, updated_at=?
               WHERE id=?""",
            (day, reason, version, _now(), request_id),
        )
        if 'sales' in data:
            _replace_sales(db, request_id, data.get('sales') or [])
        action = 'admin_edited' if _can_review(actor) and int(row['cashier_id']) != int(actor['id']) else 'edited'
        _event(db, request_id, version, action, actor, '', before)
        _audit(db, actor, 'BACKDATE_EDITED', f"{row['reference']} v{version}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_request(db, actor, request_id)


def submit_request(db, actor: dict, request_id: int, data: dict | None = None) -> dict:
    ensure_schema(db)
    data = data or {}
    db.execute('BEGIN IMMEDIATE')
    try:
        row = _locked(db, request_id)
        if not row:
            raise BackdateError('Request was not found.', 404)
        if int(row['cashier_id']) != int(actor['id']) and not _can_review(actor):
            raise BackdateError('You cannot submit another cashier\'s request.', 403)
        if row['status'] not in ('draft', 'returned'):
            raise BackdateError('Only a draft or a returned request can be submitted.')
        _check_version(row, data.get('version'))
        problems = _blocking_problems(db, row)
        if problems:
            raise BackdateError(problems[0])
        version = int(row['version']) + 1
        now = _now()
        db.execute(
            """UPDATE backdate_requests
               SET status='submitted', version=?, submitted_at=?, updated_at=?, review_note=NULL
               WHERE id=?""",
            (version, now, now, request_id),
        )
        _event(db, request_id, version, 'submitted', actor, '', _snapshot(db, row))
        _audit(db, actor, 'BACKDATE_SUBMITTED', row['reference'])
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_request(db, actor, request_id)


def withdraw_request(db, actor: dict, request_id: int, data: dict | None = None) -> dict:
    ensure_schema(db)
    data = data or {}
    reason = (data.get('reason') or data.get('note') or '').strip()
    if not reason:
        raise BackdateError('Enter a reason for withdrawing the request.')
    db.execute('BEGIN IMMEDIATE')
    try:
        row = _locked(db, request_id)
        if not row:
            raise BackdateError('Request was not found.', 404)
        if int(row['cashier_id']) != int(actor['id']):
            raise BackdateError('Only the cashier who created the request can withdraw it.', 403)
        if row['status'] not in ('draft', 'submitted', 'returned'):
            raise BackdateError('This request can no longer be withdrawn.')
        _check_version(row, data.get('version'))
        version = int(row['version']) + 1
        now = _now()
        db.execute(
            """UPDATE backdate_requests
               SET status='withdrawn', version=?, review_note=?, decided_at=?, updated_at=?
               WHERE id=?""",
            (version, reason, now, now, request_id),
        )
        _event(db, request_id, version, 'withdrawn', actor, reason, None)
        _audit(db, actor, 'BACKDATE_WITHDRAWN', row['reference'])
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_request(db, actor, request_id)


def return_request(db, actor: dict, request_id: int, data: dict | None = None) -> dict:
    return _decide(db, actor, request_id, data or {}, 'returned', 'returned', 'BACKDATE_RETURNED')


def reject_request(db, actor: dict, request_id: int, data: dict | None = None) -> dict:
    return _decide(db, actor, request_id, data or {}, 'rejected', 'rejected', 'BACKDATE_REJECTED')


def approve_request(db, actor: dict, request_id: int, data: dict | None = None) -> dict:
    ensure_schema(db)
    _require_review(actor)
    data = data or {}
    db.execute('BEGIN IMMEDIATE')
    try:
        row = _locked(db, request_id)
        if not row:
            raise BackdateError('Request was not found.', 404)
        if row['status'] == 'approved':
            db.commit()
            body = get_request(db, actor, request_id)
            body['already_approved'] = True
            return body
        if row['status'] != 'submitted':
            raise BackdateError('Only a submitted request can be approved.')
        _check_version(row, data.get('version'))
        if int(row['cashier_id']) == int(actor['id']):
            raise BackdateError('You cannot approve your own request.', 403)
        problems = _blocking_problems(db, row)
        if problems:
            raise BackdateError(problems[0])
        posted = _post_all(db, actor, row)
        version = int(row['version']) + 1
        now = _now()
        note = (data.get('note') or '').strip()
        db.execute(
            """UPDATE backdate_requests
               SET status='approved', version=?, reviewer_id=?, reviewer_name=?,
                   review_note=?, decided_at=?, updated_at=?
               WHERE id=? AND status='submitted'""",
            (version, actor['id'], actor.get('full_name') or actor.get('username'),
             note, now, now, request_id),
        )
        if db.execute("SELECT changes()").fetchone()[0] != 1:
            raise BackdateError('This request was already decided.', 409)
        _event(
            db, request_id, version, 'approved', actor, note, None,
            previous_status='submitted', new_status='approved',
            sale_reference=','.join(posted), bulk_id=(data.get('bulk_id') or ''),
        )
        _audit(db, actor, 'BACKDATE_APPROVED', f"{row['reference']} receipts={','.join(posted)}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    body = get_request(db, actor, request_id)
    body['already_approved'] = False
    return body


def bulk_approve(db, actor: dict, data: dict | None = None) -> dict:
    """Approve each eligible pending request on its own. One failure does not undo the others."""
    ensure_schema(db)
    _require_review(actor)
    data = data or {}
    scope = (data.get('scope') or 'all').strip().lower()
    day = ''
    if scope == 'day':
        day = _filter_day(data.get('business_date'))
        if not day:
            raise BackdateError('Choose the requested sales date before approving that day.')
    elif scope not in ('all', 'pending'):
        raise BackdateError('Choose all pending requests, or one requested sales date.')
    bulk_id = uuid.uuid4().hex
    rows = _pending_rows(db, actor, day if scope == 'day' else '')
    results = []
    approved_total = 0.0
    for row in rows:
        try:
            body = approve_request(db, actor, int(row['id']), {
                'note': 'Approved with the other pending requests for this review.',
                'bulk_id': bulk_id,
            })
        except BackdateError as exc:
            results.append({
                'id': int(row['id']),
                'reference': row['reference'],
                'business_date': row['business_date'],
                'outcome': 'failed',
                'reason': exc.message,
            })
            continue
        if body.get('already_approved'):
            results.append({
                'id': int(row['id']),
                'reference': body.get('reference') or row['reference'],
                'business_date': body.get('business_date') or row['business_date'],
                'outcome': 'skipped',
                'reason': 'Already approved.',
            })
            continue
        amount = float((body.get('summary') or {}).get('total_sales') or 0)
        approved_total = round(approved_total + amount, 2)
        results.append({
            'id': int(body['id']),
            'reference': body.get('reference'),
            'business_date': body.get('business_date'),
            'outcome': 'approved',
            'amount': amount,
            'receipts': [
                sale.get('posted_receipt') for sale in (body.get('sales') or []) if sale.get('posted_receipt')
            ],
        })
    return {
        'bulk_id': bulk_id,
        'scope': 'day' if scope == 'day' else 'all',
        'business_date': day,
        'approved': sum(1 for item in results if item['outcome'] == 'approved'),
        'failed': sum(1 for item in results if item['outcome'] == 'failed'),
        'skipped': sum(1 for item in results if item['outcome'] == 'skipped'),
        'approved_total': approved_total,
        'results': results,
    }


def disapprove_request(db, actor: dict, request_id: int, data: dict | None = None) -> dict:
    """Reverse an approved posting and return the request to pending review."""
    ensure_schema(db)
    _require_review(actor)
    data = data or {}
    reason = (data.get('reason') or data.get('note') or '').strip()
    if len(reason) < 3:
        raise BackdateError('Enter a reason for disapproving this approved sale.')
    db.execute('BEGIN IMMEDIATE')
    try:
        row = _locked(db, request_id)
        if not row:
            raise BackdateError('Request was not found.', 404)
        if row['status'] != 'approved':
            raise BackdateError('Only an approved request can be disapproved.')
        if int(row['cashier_id']) == int(actor['id']):
            raise BackdateError('You cannot disapprove your own request.', 403)
        _check_version(row, data.get('version'))
        sales = _sales_for(db, row['id'])
        voided = []
        for sale in sales:
            posted_id = sale.get('posted_sale_id')
            if not posted_id:
                continue
            receipt = _reverse_posted_sale(db, actor, int(posted_id), reason, row['reference'])
            if receipt:
                voided.append(receipt)
        version = int(row['version']) + 1
        now = _now()
        changed = db.execute(
            """UPDATE backdate_requests
               SET status='submitted', version=?, review_note=?, updated_at=?
               WHERE id=? AND status='approved'""",
            (version, reason, now, request_id),
        )
        if changed.rowcount != 1:
            raise BackdateError('This request was already changed.', 409)
        _event(
            db, request_id, version, 'disapproved', actor, reason, None,
            previous_status='approved', new_status='submitted',
            sale_reference=','.join(voided),
            reversal_reference=','.join(voided),
        )
        _event(
            db, request_id, version, 'returned_to_pending', actor,
            'The posted sale was reversed. The request is waiting for review again.',
            None, previous_status='approved', new_status='submitted',
            sale_reference=','.join(voided), reversal_reference=','.join(voided),
        )
        _audit(db, actor, 'BACKDATE_DISAPPROVED', f"{row['reference']}: {reason} receipts={','.join(voided)}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_request(db, actor, request_id)


def get_request(db, actor: dict, request_id: int) -> dict:
    ensure_schema(db)
    row = db.execute("SELECT * FROM backdate_requests WHERE id=?", (int(request_id),)).fetchone()
    if not row:
        raise BackdateError('Request was not found.', 404)
    record = dict(row)
    if not _can_see(actor, record):
        raise BackdateError('Request was not found.', 404)
    sales = _sales_for(db, record['id'])
    record['sales'] = sales
    record['summary'] = _summary(sales)
    record['warnings'] = _warnings(db, record, sales)
    record['events'] = [
        dict(item) for item in db.execute(
            "SELECT * FROM backdate_events WHERE request_id=? ORDER BY id",
            (record['id'],),
        ).fetchall()
    ]
    for event in record['events']:
        event.pop('snapshot', None)
    record['disapproval'] = _disapproval_banner(record['events'], record['status'])
    return record


def list_requests(db, actor: dict, filters: dict | None = None) -> dict:
    ensure_schema(db)
    filters = filters or {}
    clauses = []
    params: list = []
    if not _can_review(actor):
        _require_request(actor)
        clauses.append('cashier_id=?')
        params.append(actor['id'])
    elif filters.get('cashier_id'):
        clauses.append('cashier_id=?')
        params.append(int(filters['cashier_id']))
    if filters.get('status'):
        clauses.append('status=?')
        params.append(str(filters['status']).strip().lower())
    day = _requested_day_filter(filters)
    if day:
        clauses.append('business_date=?')
        params.append(day)
    query = (filters.get('q') or filters.get('reference') or '').strip()
    if query:
        clauses.append('reference LIKE ?')
        params.append(f'%{query}%')
    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    rows = db.execute(
        f"SELECT * FROM backdate_requests {where} ORDER BY updated_at DESC, id DESC",
        params,
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        sales = _sales_for(db, item['id'])
        item['sale_count'] = len(sales)
        item['summary'] = _summary(sales)
        item.pop('sales', None)
        items.append(item)
    own_clause = '' if _can_review(actor) else ' AND cashier_id=?'
    own_params = () if _can_review(actor) else (actor['id'],)
    pending = db.execute(
        "SELECT COUNT(*) AS c FROM backdate_requests WHERE status='submitted'" + own_clause,
        own_params,
    ).fetchone()
    pending_total = db.execute(
        """SELECT COALESCE(SUM(l.total), 0) AS total
           FROM backdate_lines l
           JOIN backdate_sales s ON s.id = l.backdate_sale_id
           JOIN backdate_requests r ON r.id = s.request_id
           WHERE r.status='submitted'""" + own_clause.replace('cashier_id', 'r.cashier_id'),
        own_params,
    ).fetchone()
    groups = _pending_groups(items, actor)
    return {
        'requests': items,
        'pending_count': int(pending['c'] if pending else 0),
        'pending_total': round(float(pending_total['total'] if pending_total else 0), 2),
        'groups': groups,
        'date_filter': day or 'all',
    }


def _decide(db, actor, request_id, data, status, action, audit_action) -> dict:
    ensure_schema(db)
    _require_review(actor)
    note = (data.get('reason') or data.get('note') or '').strip()
    if not note:
        raise BackdateError('Enter a reason before returning or rejecting the request.')
    db.execute('BEGIN IMMEDIATE')
    try:
        row = _locked(db, request_id)
        if not row:
            raise BackdateError('Request was not found.', 404)
        if row['status'] != 'submitted':
            raise BackdateError('Only a submitted request can be reviewed.')
        if int(row['cashier_id']) == int(actor['id']):
            raise BackdateError('You cannot review your own request.', 403)
        _check_version(row, data.get('version'))
        version = int(row['version']) + 1
        now = _now()
        db.execute(
            """UPDATE backdate_requests
               SET status=?, version=?, reviewer_id=?, reviewer_name=?,
                   review_note=?, decided_at=?, updated_at=?
               WHERE id=? AND status='submitted'""",
            (status, version, actor['id'], actor.get('full_name') or actor.get('username'),
             note, now, now, request_id),
        )
        if db.execute("SELECT changes()").fetchone()[0] != 1:
            raise BackdateError('This request was already decided.', 409)
        _event(db, request_id, version, action, actor, note, None)
        _audit(db, actor, audit_action, f"{row['reference']}: {note}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_request(db, actor, request_id)


def _post_all(db, actor, row) -> list[str]:
    sales = _sales_for(db, row['id'])
    receipts = []
    from backend.sale_lines import fill_sale_line
    from desktop.utils.stock_layers import consume_fifo
    for sale in sales:
        token, existing = _claim_post(db, row['id'], sale['id'])
        if existing:
            db.execute(
                "UPDATE backdate_sales SET posted_sale_id=?, posted_receipt=? WHERE id=?",
                (existing['id'], existing['receipt_number'], sale['id']),
            )
            receipts.append(existing['receipt_number'])
            continue
        lines = []
        for line in sale['lines']:
            try:
                filled = fill_sale_line(db, line)
            except ValueError as exc:
                raise BackdateError(str(exc)) from exc
            if filled['quantity'] <= 0:
                raise BackdateError('Each product needs a quantity above zero.')
            if filled['total'] < 0:
                raise BackdateError('A line total cannot be negative.')
            lines.append(filled)
        total = round(sum(item['total'] for item in lines), 2)
        discount = round(sum(float(item['discount'] or 0) for item in lines), 2)
        kind = _kind(sale.get('payment_method'))
        amount_paid = round(float(sale.get('amount_paid') or 0), 2)
        if kind == 'cash' and amount_paid <= 0:
            amount_paid = total
        if kind in ('mpesa', 'bank') and amount_paid <= 0:
            amount_paid = total
        cash_paid, electronic_paid, method_name = _tenders(kind, sale, total, amount_paid)
        change = round(max(0, amount_paid - total), 2) if kind == 'cash' else 0
        day_key = str(row['business_date']).replace('-', '')
        count = db.execute(
            "SELECT COUNT(*) AS c FROM sales WHERE sale_date=?",
            (row['business_date'],),
        ).fetchone()['c']
        receipt = f"RCP-{day_key}-{int(count) + 1:04d}"
        notes = (sale.get('notes') or '').strip()
        notes = (notes + f" | Backdating request {row['reference']}").strip(' |')
        mpesa_ref = (sale.get('mpesa_ref') or '').strip()
        prepared = {}
        if mpesa_ref:
            from backend.mpesa_service import MpesaSaleError, prepare_sale_mpesa
            try:
                prepared = prepare_sale_mpesa(
                    db, {'mpesa_ref': mpesa_ref, 'payment_method': 'M-Pesa', 'amount_paid': amount_paid},
                    'M-Pesa', 0,
                )
            except MpesaSaleError as exc:
                raise BackdateError(str(exc)) from exc
            mpesa_ref = prepared.get('mpesa_ref') or mpesa_ref
            notes = (notes + f" | M-Pesa ref: {mpesa_ref} | Reference not verified by the till").strip(' |')
        created_at = _now()
        db.execute(
            """INSERT INTO sales
               (receipt_number, cashier_id, cashier_name, subtotal, discount, tax, total,
                original_total, payment_method, amount_paid, change_amount, notes, mpesa_ref,
                sale_date, created_at, customer_id, electronic_paid, electronic_method, cash_paid,
                client_token, backdate_request_id, status)
               VALUES (?,?,?,?,?,0,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'completed')""",
            (receipt, row['cashier_id'], row['cashier_name'], total, discount, total, total,
             method_name, amount_paid, change, notes, mpesa_ref or None, row['business_date'],
             created_at, sale.get('customer_id'), electronic_paid,
             'M-Pesa' if kind == 'mpesa' else ('Bank' if kind == 'bank' else None),
             cash_paid, token, row['id']),
        )
        sale_id = _last_id(db)
        if prepared:
            from backend.mpesa_service import attach_sale_mpesa
            attach_sale_mpesa(db, sale_id, prepared)
        for line in lines:
            db.execute(
                """INSERT INTO sale_items
                   (sale_id, product_id, product_name, sku, quantity, unit_price, discount, total)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (sale_id, line['product_id'], line['product_name'], line['sku'],
                 line['quantity'], line['unit_price'], line['discount'], line['total']),
            )
            _apply_stock(db, actor, row, line, receipt, sale_id, consume_fifo)
        if kind in ('credit', 'part'):
            _create_debt(db, row, sale, sale_id, receipt, total, amount_paid, notes)
        from desktop.utils.accounting_hooks import post_sale_journal
        posted_journal = post_sale_journal(
            db, sale_id,
            user_id=actor.get('id'),
            username=actor.get('username') or '',
            safe=False,
        )
        if not posted_journal.get('success'):
            raise BackdateError(
                posted_journal.get('error') or 'The sale could not be posted to the accounts.'
            )
        db.execute(
            "INSERT INTO sync_queue (action_type, payload) VALUES (?, ?)",
            ('sale', json.dumps({
                'receipt_number': receipt,
                'total': total,
                'sale_date': row['business_date'],
                'backdate_request': row['reference'],
                'created_at': created_at,
            })),
        )
        db.execute(
            "UPDATE backdate_sales SET posted_sale_id=?, posted_receipt=? WHERE id=?",
            (sale_id, receipt, sale['id']),
        )
        receipts.append(receipt)
    return receipts


def _apply_stock(db, actor, row, line, receipt, sale_id, consume_fifo) -> None:
    pid = line['product_id']
    if not pid:
        raise BackdateError('Each line needs a product.')
    product = db.execute(
        "SELECT id, name, stock, is_active FROM products WHERE id=?",
        (int(pid),),
    ).fetchone()
    if not product or int(product['is_active'] or 0) != 1:
        raise BackdateError(f"{line['product_name'] or 'A product'} is no longer available.")
    qty = float(line['quantity'])
    current = float(product['stock'] or 0)
    if current < qty:
        raise BackdateError(
            f"Insufficient stock for '{product['name']}': requested {qty}, available {current}."
        )
    new_stock = current - qty
    db.execute("UPDATE products SET stock=? WHERE id=?", (new_stock, product['id']))
    db.execute(
        """INSERT INTO stock_movements
           (product_id, product_name, movement_type, qty_before, qty_change, qty_after,
            reference, reason, user_id, username)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (product['id'], product['name'], 'SALE', current, -qty, new_stock, receipt,
         f"Backdating {row['reference']} business day {row['business_date']}",
         actor['id'], actor.get('username') or ''),
    )
    from desktop.utils.stock_layers import record_sale_cost
    layer = record_sale_cost(db, int(pid), qty, sale_id=sale_id, reference=receipt)
    if layer.get('error'):
        raise BackdateError(layer['error'])


def _create_debt(db, row, sale, sale_id, receipt, total, paid, notes) -> None:
    customer_id = sale.get('customer_id')
    customer = db.execute("SELECT * FROM customers WHERE id=?", (int(customer_id),)).fetchone()
    if not customer:
        raise BackdateError('The customer for a credit sale was not found.')
    existing = db.execute(
        "SELECT id FROM debt_invoices WHERE sale_id=? AND status!='cancelled'",
        (sale_id,),
    ).fetchone()
    if existing:
        return
    balance = round(total - paid, 2)
    status = 'paid' if balance <= 0 else ('partial' if paid > 0 else 'pending')
    count = db.execute("SELECT COUNT(*) AS c FROM debt_invoices").fetchone()['c']
    invoice = f"INV-BD-{int(count) + 1:05d}"
    db.execute(
        """INSERT INTO debt_invoices
           (invoice_number, sale_id, receipt_number, customer_id, customer_name, customer_phone,
            total_amount, amount_paid, balance, status, due_date, cashier_id, cashier_name, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (invoice, sale_id, receipt, int(customer_id), customer['name'], customer['phone'] if 'phone' in customer.keys() else '',
         total, paid, balance, status, sale.get('due_date') or None,
         row['cashier_id'], row['cashier_name'], notes),
    )
    if paid > 0:
        invoice_id = _last_id(db)
        pay_count = db.execute("SELECT COUNT(*) AS c FROM debt_payments").fetchone()['c']
        db.execute(
            """INSERT INTO debt_payments
               (payment_receipt, invoice_id, customer_id, amount, payment_method,
                balance_before, balance_after, cashier_id, cashier_name, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (f"PAY-BD-{int(pay_count) + 1:05d}", invoice_id, int(customer_id), paid,
             sale.get('payment_method') or 'Cash', total, balance,
             row['cashier_id'], row['cashier_name'], f"Deposit on {receipt}"),
        )


def _blocking_problems(db, row) -> list[str]:
    policy = _date_policy(db, row['business_date'])
    if policy:
        return [policy]
    reason = (row['reason'] or '').strip()
    if len(reason) < 3 or reason == 'Other':
        return ['Choose a reason for this past date. If you choose Other, write what happened.']
    sales = _sales_for(db, row['id'])
    if not sales:
        return ['Add at least one sale before submitting.']
    for sale in sales:
        if not sale['lines']:
            return ['Every sale needs at least one product.']
        kind = _kind(sale.get('payment_method'))
        total = round(sum(float(line['total']) for line in sale['lines']), 2)
        if total < 0:
            return ['A sale total cannot be negative.']
        paid = round(float(sale.get('amount_paid') or 0), 2)
        if kind in ('credit', 'part') and not sale.get('customer_id'):
            return ['A credit sale needs a customer.']
        if kind == 'part' and not (0 < paid < total):
            return ['A part payment needs a deposit that is less than the sale total.']
        if kind == 'credit' and paid >= total > 0:
            return ['This sale is paid in full. Choose Cash, M-Pesa, or Bank instead of credit.']
        if kind == 'cash' and 0 < paid < total:
            return ['The cash received does not cover the sale. Use Part Payment for a deposit.']
        if kind == 'mixed':
            covered = round(float(sale.get('cash_paid') or 0) + float(sale.get('electronic_paid') or 0), 2)
            if covered + 0.009 < total:
                return ['A mixed sale needs the cash amount and the second payment to cover the total.']
        for line in sale['lines']:
            try:
                from backend.sale_lines import fill_sale_line
                fill_sale_line(db, line)
            except ValueError as exc:
                return [str(exc)]
            if float(line['quantity']) <= 0:
                return ['Each product needs a quantity above zero.']
            if float(line['unit_price']) < 0 or float(line['discount']) < 0:
                return ['Price and discount cannot be negative.']
    return []


def _warnings(db, row, sales) -> list[str]:
    warnings = []
    needed: dict[int, float] = {}
    names: dict[int, str] = {}
    for sale in sales:
        kind = _kind(sale.get('payment_method'))
        if kind == 'mpesa' and not (sale.get('mpesa_ref') or '').strip():
            warnings.append('An M-Pesa sale has no reference. Approval will not mark it as verified.')
        for line in sale['lines']:
            pid = line.get('product_id')
            if not pid:
                warnings.append(f"{line.get('product_name') or 'A line'} has no product.")
                continue
            needed[int(pid)] = needed.get(int(pid), 0) + float(line['quantity'])
            names[int(pid)] = line.get('product_name') or ''
    for pid, qty in needed.items():
        product = db.execute(
            "SELECT name, stock, is_active FROM products WHERE id=?", (pid,)
        ).fetchone()
        if not product or int(product['is_active'] or 0) != 1:
            warnings.append(f"{names.get(pid) or 'A product'} is not an active product.")
            continue
        if float(product['stock'] or 0) < qty:
            warnings.append(
                f"Not enough stock for {product['name']}: the request needs {qty}, "
                f"and {product['stock']} are in stock now. Approval will be refused until stock covers it."
            )
    twin = db.execute(
        """SELECT reference FROM backdate_requests
           WHERE id!=? AND cashier_id=? AND business_date=? AND status IN ('submitted','approved')""",
        (row['id'], row['cashier_id'], row['business_date']),
    ).fetchall()
    for item in twin:
        warnings.append(f"This cashier already has request {item['reference']} for the same business day.")
    return warnings


def _summary(sales) -> dict:
    total = cash = mpesa = bank = credit = paid = outstanding = discounts = 0.0
    for sale in sales:
        kind = _kind(sale.get('payment_method'))
        sale_total = round(sum(float(line['total']) for line in sale['lines']), 2)
        amount_paid = round(float(sale.get('amount_paid') or 0), 2)
        discounts += sum(float(line['discount'] or 0) for line in sale['lines'])
        total += sale_total
        if kind == 'cash':
            cash += sale_total
            paid += sale_total
        elif kind == 'mpesa':
            mpesa += sale_total
            paid += sale_total
        elif kind == 'bank':
            bank += sale_total
            paid += sale_total
        elif kind == 'mixed':
            cash_part = round(float(sale.get('cash_paid') or 0), 2)
            electronic = round(float(sale.get('electronic_paid') or 0), 2)
            cash += cash_part
            mpesa += electronic
            paid += cash_part + electronic
        else:
            credit += sale_total
            deposit = min(amount_paid, sale_total)
            paid += deposit
            outstanding += round(sale_total - deposit, 2)
            if (sale.get('mpesa_ref') or '').strip():
                mpesa += deposit
            else:
                cash += deposit
    return {
        'sale_count': len(sales),
        'total_sales': round(total, 2),
        'cash_sales': round(cash, 2),
        'mpesa_sales': round(mpesa, 2),
        'bank_sales': round(bank, 2),
        'credit_sales': round(credit, 2),
        'payments_received': round(paid, 2),
        'outstanding_debt': round(outstanding, 2),
        'discounts': round(discounts, 2),
    }


def _sales_for(db, request_id: int) -> list[dict]:
    sales = []
    rows = db.execute(
        "SELECT * FROM backdate_sales WHERE request_id=? ORDER BY sort_order, id",
        (int(request_id),),
    ).fetchall()
    for row in rows:
        sale = dict(row)
        sale['lines'] = [
            dict(line) for line in db.execute(
                """SELECT l.id, l.backdate_sale_id, l.product_id, l.product_name,
                          l.quantity, l.unit_price, l.discount, l.total, p.sku
                   FROM backdate_lines l
                   LEFT JOIN products p ON p.id = l.product_id
                   WHERE l.backdate_sale_id=?
                   ORDER BY l.id""",
                (sale['id'],),
            ).fetchall()
        ]
        sale['total'] = round(sum(float(line['total']) for line in sale['lines']), 2)
        sales.append(sale)
    return sales


def _replace_sales(db, request_id: int, sales) -> None:
    old = db.execute("SELECT id FROM backdate_sales WHERE request_id=?", (request_id,)).fetchall()
    for item in old:
        db.execute("DELETE FROM backdate_lines WHERE backdate_sale_id=?", (item['id'],))
    db.execute("DELETE FROM backdate_sales WHERE request_id=?", (request_id,))
    for index, sale in enumerate(sales or []):
        lines = sale.get('lines') or sale.get('items') or []
        if not lines:
            continue
        customer_id = sale.get('customer_id') or None
        customer_name = (sale.get('customer_name') or '').strip()
        if customer_id and not customer_name:
            customer = db.execute("SELECT name FROM customers WHERE id=?", (int(customer_id),)).fetchone()
            customer_name = customer['name'] if customer else ''
        db.execute(
            """INSERT INTO backdate_sales
               (request_id, sort_order, customer_id, customer_name, payment_method,
                amount_paid, cash_paid, electronic_paid, mpesa_ref, notes, due_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (request_id, index, int(customer_id) if customer_id else None, customer_name,
             (sale.get('payment_method') or 'Cash').strip() or 'Cash',
             float(sale.get('amount_paid') or 0), float(sale.get('cash_paid') or 0),
             float(sale.get('electronic_paid') or 0), (sale.get('mpesa_ref') or '').strip(),
             (sale.get('notes') or '').strip(), (sale.get('due_date') or '').strip() or None),
        )
        sale_id = _last_id(db)
        for line in lines:
            qty = float(line.get('quantity') or 0)
            price = line.get('unit_price')
            product_id = line.get('product_id')
            name = (line.get('product_name') or '').strip()
            if product_id and (price is None or price == '' or not name):
                product = db.execute(
                    "SELECT name, price FROM products WHERE id=?", (int(product_id),)
                ).fetchone()
                if product:
                    name = name or product['name']
                    if price is None or price == '':
                        price = product['price']
            price = float(price or 0)
            discount = float(line.get('discount') or 0)
            if discount > round(qty * price, 2):
                raise BackdateError('A discount cannot be more than the line amount.')
            total = round(qty * price - discount, 2)
            db.execute(
                """INSERT INTO backdate_lines
                   (backdate_sale_id, product_id, product_name, quantity, unit_price, discount, total)
                   VALUES (?,?,?,?,?,?,?)""",
                (sale_id, int(product_id) if product_id else None, name, qty, price, discount, total),
            )


def _editable(row, actor, version) -> None:
    if not row:
        raise BackdateError('Request was not found.', 404)
    if row['status'] in _TERMINAL or row['status'] == 'approved':
        raise BackdateError('This request is closed and cannot be edited.')
    _check_version(row, version)
    owner = int(row['cashier_id']) == int(actor['id'])
    if owner and row['status'] in _OPEN_FOR_CASHIER and _may_request(actor):
        return
    if _can_review(actor) and row['status'] in ('draft', 'submitted', 'returned'):
        return
    if owner and row['status'] == 'submitted':
        raise BackdateError('This request is with the administrator. Wait for it to be returned before editing.')
    raise BackdateError('You cannot edit this request.', 403)


def _snapshot(db, row) -> str:
    body = dict(row)
    body['sales'] = _sales_for(db, row['id'])
    return json.dumps(body, default=str)


def _event(db, request_id, version, action, actor, note, snapshot, *,
           previous_status='', new_status='', sale_reference='',
           reversal_reference='', bulk_id='') -> None:
    db.execute(
        """INSERT INTO backdate_events
           (request_id, version, action, actor_id, actor_name, note, snapshot, created_at,
            actor_role, previous_status, new_status, sale_reference, reversal_reference, bulk_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (request_id, version, action, actor.get('id'),
         actor.get('full_name') or actor.get('username') or '',
         note or '', snapshot, _now(),
         (actor.get('role') or ''), previous_status, new_status,
         sale_reference, reversal_reference, bulk_id),
    )


def _audit(db, actor, action, details) -> None:
    try:
        db.execute(
            """INSERT INTO audit_log (user_id, username, action, module, details, ip_address)
               VALUES (?,?,?,?,?,?)""",
            (actor.get('id'), actor.get('username') or '', action, 'backdate', details, ''),
        )
    except Exception:
        pass


def _locked(db, request_id: int):
    return db.execute(
        "SELECT * FROM backdate_requests WHERE id=?", (int(request_id),)
    ).fetchone()


def _check_version(row, version) -> None:
    if version is None or version == '':
        return
    if int(version) != int(row['version']):
        raise BackdateError('This request changed while you had it open. Reload it and try again.', 409)


def _setting(db, key: str) -> str:
    try:
        row = db.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
    except Exception:
        return ''
    if not row:
        return ''
    value = row['value'] if hasattr(row, 'keys') else row[0]
    return str(value or '').strip()


def _date_policy(db, day: str) -> str | None:
    """Reject dates outside the shop's opening, limit, or a closed period."""
    opened = _setting(db, 'shop_opened_on') or _setting(db, 'business_start_date')
    opened_day = parse_sale_date(opened) if opened else None
    if opened_day and str(day) < opened_day.isoformat():
        return 'That date is before this shop opened.'
    raw_limit = _setting(db, 'backdate_max_days')
    if raw_limit:
        try:
            limit = int(raw_limit)
        except ValueError:
            limit = 0
        if limit > 0:
            from datetime import timedelta
            oldest = (shop_today() - timedelta(days=limit)).isoformat()
            if str(day) < oldest:
                return f'That date is more than {limit} days ago.'
    try:
        from desktop.utils.accounting_engine import PeriodClosedError, assert_period_open
        assert_period_open(db, str(day))
    except PeriodClosedError as exc:
        return str(exc)
    except Exception:
        return None
    return None


def _past_day(raw) -> str:
    day = parse_sale_date(str(raw or '').strip())
    if day is None:
        raise BackdateError('Enter the business date as YYYY-MM-DD.')
    today = shop_today()
    if day > today:
        raise BackdateError('A business date cannot be in the future.')
    if day == today:
        raise BackdateError('Today\'s sales are recorded on the sales screen. Choose an earlier date.')
    return business_day_iso(day)


def _next_reference(db) -> str:
    stamp = datetime.now().strftime('%Y%m%d')
    prefix = f"BDR-{stamp}-"
    count = db.execute(
        "SELECT COUNT(*) AS c FROM backdate_requests WHERE reference LIKE ?",
        (prefix + '%',),
    ).fetchone()['c']
    return f"{prefix}{int(count) + 1:04d}"


def _kind(method: str) -> str:
    name = (method or 'cash').strip().lower()
    if name in _CREDIT and 'part' in name:
        return 'part'
    if name in ('credit', 'credit sale'):
        return 'credit'
    if name in _MPESA:
        return 'mpesa'
    if name in _BANK:
        return 'bank'
    if name == 'mixed':
        return 'mixed'
    return 'cash'


def _tenders(kind, sale, total, amount_paid):
    if kind == 'cash':
        return total, 0, 'Cash'
    if kind == 'mpesa':
        return 0, total, 'M-Pesa'
    if kind == 'bank':
        return 0, total, sale.get('payment_method') or 'Bank Transfer'
    if kind == 'mixed':
        return (
            round(float(sale.get('cash_paid') or 0), 2),
            round(float(sale.get('electronic_paid') or 0), 2),
            'Mixed',
        )
    return 0, 0, 'Credit Sale' if kind == 'credit' else 'Part Payment'


def _add_column(db, table: str, name: str, ddl: str) -> None:
    cols = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if name not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _requested_day_filter(filters: dict) -> str:
    raw = str(filters.get('date') or '').strip().lower()
    explicit = str(filters.get('business_date') or '').strip()
    if raw in ('', 'all') and not explicit:
        return ''
    if raw == 'today':
        return shop_today().isoformat()
    if raw == 'yesterday':
        return (shop_today() - timedelta(days=1)).isoformat()
    chosen = explicit or raw
    if not chosen or chosen == 'all':
        return ''
    day = parse_sale_date(chosen)
    if day is None:
        raise BackdateError('Enter the requested sales date as YYYY-MM-DD.')
    return business_day_iso(day)


def _filter_day(raw) -> str:
    day = parse_sale_date(str(raw or '').strip())
    if day is None:
        return ''
    return business_day_iso(day)


def _pending_groups(items, actor) -> list:
    groups = {}
    actor_id = int(actor.get('id') or 0)
    for item in items:
        if item.get('status') != 'submitted':
            continue
        day = item.get('business_date') or ''
        bucket = groups.setdefault(day, {
            'business_date': day,
            'count': 0,
            'total': 0.0,
            'eligible_count': 0,
            'eligible_total': 0.0,
            'request_ids': [],
        })
        amount = float((item.get('summary') or {}).get('total_sales') or 0)
        bucket['count'] += 1
        bucket['total'] = round(bucket['total'] + amount, 2)
        bucket['request_ids'].append(item['id'])
        if _can_review(actor) and int(item.get('cashier_id') or 0) != actor_id:
            bucket['eligible_count'] += 1
            bucket['eligible_total'] = round(bucket['eligible_total'] + amount, 2)
    return [groups[key] for key in sorted(groups, reverse=True)]


def _pending_rows(db, actor, day: str):
    sql = "SELECT * FROM backdate_requests WHERE status='submitted' AND cashier_id!=?"
    params: list = [int(actor['id'])]
    if day:
        sql += " AND business_date=?"
        params.append(day)
    sql += " ORDER BY business_date, id"
    return db.execute(sql, params).fetchall()


def _claim_post(db, request_id: int, backdate_sale_id: int):
    base = f"backdate-{int(request_id)}-{int(backdate_sale_id)}"
    rows = db.execute(
        """SELECT id, receipt_number, status, client_token FROM sales
           WHERE client_token=? OR client_token LIKE ?""",
        (base, base + '-r%'),
    ).fetchall()
    for row in rows:
        if (row['status'] or 'completed') != 'voided':
            return row['client_token'], row
    used = {row['client_token'] for row in rows}
    if base not in used:
        return base, None
    cycle = 2
    while f"{base}-r{cycle}" in used:
        cycle += 1
    return f"{base}-r{cycle}", None


def _disapproval_banner(events, status: str):
    if status != 'submitted':
        return None
    approved = None
    disapproved = None
    for event in events or []:
        action = event.get('action')
        if action == 'approved':
            approved = event
        elif action == 'disapproved':
            disapproved = event
    if not disapproved or not approved:
        return None
    if (approved.get('id') or 0) > (disapproved.get('id') or 0):
        return None
    return {
        'headline': 'PREVIOUSLY APPROVED — SUBSEQUENTLY DISAPPROVED',
        'approved_at': approved.get('created_at') or '',
        'approved_by': approved.get('actor_name') or '',
        'disapproved_at': disapproved.get('created_at') or '',
        'disapproved_by': disapproved.get('actor_name') or '',
        'reason': disapproved.get('note') or '',
        'sale_reference': disapproved.get('sale_reference') or '',
        'reversal_reference': disapproved.get('reversal_reference') or '',
        'reversed': True,
    }


def _reverse_posted_sale(db, actor, sale_id: int, reason: str, reference: str) -> str:
    sale = db.execute("SELECT * FROM sales WHERE id=?", (int(sale_id),)).fetchone()
    if not sale:
        raise BackdateError('The posted sale for this request was not found.')
    if (sale['status'] or '') == 'voided':
        return sale['receipt_number'] or ''
    _block_later_debt(db, sale)
    _restore_sale_stock(db, actor, sale, reason)
    from desktop.utils.stock_layers import restore_sale_layers
    restore_sale_layers(db, int(sale['id']))
    _cancel_sale_debt(db, sale, reason)
    from desktop.utils.accounting_hooks import reverse_sale_journal
    reversed_journal = reverse_sale_journal(
        db, int(sale['id']), reason=reason,
        user_id=actor.get('id'), username=actor.get('username') or '',
        safe=False,
    )
    if reversed_journal.get('error'):
        raise BackdateError(reversed_journal['error'])
    updated = db.execute(
        "UPDATE sales SET status='voided', notes=? WHERE id=? AND COALESCE(status,'completed')!='voided'",
        (
            f"VOIDED by {actor.get('username') or 'administrator'}: disapproval of {reference}. {reason}",
            sale['id'],
        ),
    )
    if updated.rowcount != 1:
        raise BackdateError('This sale was already reversed.', 409)
    try:
        db.execute(
            """INSERT INTO sale_edits
               (sale_id, edited_by_id, edited_by_name, edit_type, field_name, old_value, new_value, reason)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sale['id'], actor.get('id'), actor.get('username') or '',
             'VOID', 'status', 'completed', 'voided', reason),
        )
    except Exception:
        pass
    return sale['receipt_number'] or ''


def _block_later_debt(db, sale) -> None:
    try:
        payments = db.execute(
            """SELECT dp.notes, dp.payment_receipt
               FROM debt_payments dp
               JOIN debt_invoices di ON di.id = dp.invoice_id
               WHERE di.sale_id=?""",
            (sale['id'],),
        ).fetchall()
    except Exception:
        return
    for payment in payments:
        note = payment['notes'] or ''
        slip = payment['payment_receipt'] or ''
        if note.startswith('Deposit on') and slip.startswith('PAY-BD-'):
            continue
        raise BackdateError(
            'This sale has a later customer payment. Disapproval is blocked so that payment is not deleted. '
            'Refund or reallocate it first, then disapprove the request.'
        )


def _restore_sale_stock(db, actor, sale, reason: str) -> None:
    ref = f"VOID_sale={int(sale['id'])}"
    already = db.execute(
        "SELECT 1 FROM stock_movements WHERE movement_type='VOID_RESTORE' AND reference=? LIMIT 1",
        (ref,),
    ).fetchone()
    if already:
        return
    items = db.execute(
        "SELECT product_id, product_name, quantity FROM sale_items WHERE sale_id=?",
        (sale['id'],),
    ).fetchall()
    for item in items:
        pid = item['product_id']
        qty = float(item['quantity'] or 0)
        if not pid or qty <= 0:
            continue
        product = db.execute("SELECT name, stock FROM products WHERE id=?", (int(pid),)).fetchone()
        if not product:
            raise BackdateError(
                f"{item['product_name'] or 'A product'} no longer exists, so the stock cannot be restored."
            )
        current = float(product['stock'] or 0)
        new_stock = round(current + qty, 4)
        db.execute("UPDATE products SET stock=? WHERE id=?", (new_stock, int(pid)))
        db.execute(
            """INSERT INTO stock_movements
               (product_id, product_name, movement_type, qty_before, qty_change, qty_after,
                reference, reason, user_id, username)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (int(pid), product['name'], 'VOID_RESTORE', current, qty, new_stock, ref,
             f"Stock restored: disapproval of {sale['receipt_number']}. {reason}",
             actor.get('id'), actor.get('username') or ''),
        )


def _cancel_sale_debt(db, sale, reason: str) -> None:
    try:
        rows = db.execute(
            """SELECT id, amount_paid FROM debt_invoices
               WHERE sale_id=? AND status!='cancelled'""",
            (sale['id'],),
        ).fetchall()
    except Exception:
        return
    now = _now()
    for inv in rows:
        paid = float(inv['amount_paid'] or 0)
        note = f"CANCELLED: sale {sale['receipt_number']} disapproved — {reason}"
        if paid > 0.009:
            note += f" | Deposit already recorded: {paid:,.2f}. It stays in the payment history and is not a cash refund."
        try:
            db.execute(
                "UPDATE debt_invoices SET status='cancelled', balance=0, notes=?, updated_at=? WHERE id=?",
                (note, now, inv['id']),
            )
        except Exception:
            db.execute(
                "UPDATE debt_invoices SET status='cancelled', balance=0, notes=? WHERE id=?",
                (note, inv['id']),
            )


def _can_review(actor) -> bool:
    return (actor.get('role') or '') in _REVIEW_ROLES


def _request_role(actor) -> bool:
    return (actor.get('role') or '') in _REQUEST_ROLES


def _may_request(actor) -> bool:
    from desktop.utils.security import has_permission
    return has_permission(actor, 'sales.request_backdate')


def _require_request(actor) -> None:
    if not _may_request(actor):
        raise BackdateError('You cannot create a backdating request.', 403)


def _require_review(actor) -> None:
    from desktop.utils.security import has_permission
    if not _can_review(actor) or not has_permission(actor, 'sales.void'):
        raise BackdateError('Only a manager or administrator can review a backdating request.', 403)


def _can_see(actor, row) -> bool:
    if _can_review(actor):
        return True
    return _may_request(actor) and int(row['cashier_id']) == int(actor.get('id') or 0)


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _last_id(db) -> int:
    return int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
