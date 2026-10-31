"""Shop payables. A stock receipt is the supplier invoice. Payments are separate.

Customer debt is never read or written here.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime


def money(value) -> float:
    try:
        number = round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return number


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now().date().isoformat()


def _day(value) -> str:
    text = str(value or "").strip()
    return text[:10]


def ensure_schema(conn) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS supplier_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_number TEXT UNIQUE,
        supplier_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        method TEXT,
        reference TEXT,
        notes TEXT,
        user_id INTEGER,
        username TEXT,
        client_token TEXT UNIQUE,
        status TEXT DEFAULT 'posted',
        paid_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        reversed INTEGER DEFAULT 0,
        reversed_at TEXT,
        reverse_reason TEXT
    );
    CREATE TABLE IF NOT EXISTS supplier_payment_allocations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id INTEGER NOT NULL,
        receipt_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        UNIQUE(payment_id, receipt_id)
    );
    CREATE TABLE IF NOT EXISTS supplier_delivery_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_number TEXT UNIQUE,
        receipt_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        requested_date TEXT,
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
    CREATE TABLE IF NOT EXISTS supplier_delivery_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_id INTEGER,
        kind TEXT NOT NULL,
        detail TEXT,
        user_id INTEGER,
        username TEXT,
        client_token TEXT UNIQUE,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    receipt_cols = {row[1] for row in conn.execute("PRAGMA table_info(stock_receipts)").fetchall()}
    if receipt_cols:
        if "due_date" not in receipt_cols:
            conn.execute("ALTER TABLE stock_receipts ADD COLUMN due_date TEXT")
        if "effective_date" not in receipt_cols:
            conn.execute("ALTER TABLE stock_receipts ADD COLUMN effective_date TEXT")
        if "void_reason" not in receipt_cols:
            conn.execute("ALTER TABLE stock_receipts ADD COLUMN void_reason TEXT")
    line_cols = {row[1] for row in conn.execute("PRAGMA table_info(stock_receipt_lines)").fetchall()}
    if line_cols and "returned_qty" not in line_cols:
        conn.execute("ALTER TABLE stock_receipt_lines ADD COLUMN returned_qty REAL DEFAULT 0")


def payment_status(total, paid, due, delivery_status, today=None) -> str:
    if str(delivery_status or "posted").lower() == "reversed":
        return "VOIDED"
    outstanding = money(money(total) - money(paid))
    if outstanding <= 0.009:
        return "PAID"
    if due and _day(due) < (today or _today()) and outstanding > 0.009:
        return "OVERDUE"
    if money(paid) > 0.009:
        return "PARTIALLY PAID"
    return "UNPAID"


def _paid_by_receipt(conn) -> dict:
    rows = conn.execute(
        "SELECT a.receipt_id, COALESCE(SUM(a.amount),0) AS paid "
        "FROM supplier_payment_allocations a "
        "JOIN supplier_payments p ON p.id=a.payment_id "
        "WHERE COALESCE(p.reversed,0)=0 AND COALESCE(p.status,'posted')!='reversed' "
        "GROUP BY a.receipt_id"
    ).fetchall()
    return {int(row["receipt_id"]): money(row["paid"]) for row in rows}


def decorate_header(header: dict, paid: float, today=None) -> dict:
    total = money(header.get("grand_total"))
    paid = money(paid)
    if paid > total:
        paid = total
    outstanding = 0.0 if str(header.get("status") or "posted").lower() == "reversed" else money(total - paid)
    header["amount_paid"] = paid if str(header.get("status") or "").lower() != "reversed" else money(paid)
    if str(header.get("status") or "posted").lower() == "reversed":
        header["amount_paid"] = paid
        header["outstanding"] = 0.0
    else:
        header["outstanding"] = outstanding
    header["payment_status"] = payment_status(
        total, paid, header.get("due_date"), header.get("status"), today,
    )
    header["effective_date"] = _day(header.get("effective_date") or header.get("created_at"))
    return header


def annotate_receipts(conn, rows: list) -> list:
    ensure_schema(conn)
    paid = _paid_by_receipt(conn)
    today = _today()
    out = []
    for row in rows or []:
        item = dict(row)
        out.append(decorate_header(item, paid.get(int(item.get("id") or 0), 0), today))
    return out


def _open_invoices(conn, supplier_id: int) -> list:
    rows = conn.execute(
        "SELECT id, receipt_number, grand_total, due_date, effective_date, created_at, "
        "COALESCE(status,'posted') AS status, reference_note "
        "FROM stock_receipts WHERE supplier_id=? ORDER BY "
        "COALESCE(effective_date, substr(created_at,1,10)), id",
        (int(supplier_id),),
    ).fetchall()
    paid = _paid_by_receipt(conn)
    open_rows = []
    for row in rows:
        item = dict(row)
        if str(item.get("status") or "posted").lower() == "reversed":
            continue
        owed = money(money(item.get("grand_total")) - paid.get(int(item["id"]), 0))
        if owed <= 0.009:
            continue
        item["outstanding"] = owed
        open_rows.append(item)
    return open_rows


def _next_number(conn, table: str, column: str, prefix: str) -> str:
    latest = conn.execute(
        f"SELECT {column} FROM {table} WHERE {column} LIKE ? ORDER BY {column} DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    seq = 1
    if latest and latest[0]:
        tail = str(latest[0]).rsplit("-", 1)[-1]
        try:
            seq = int(tail) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:04d}"


def _insert_payment(conn, *, supplier_id, amount, method, reference, notes,
                    user_id, username, allocations, client_token, paid_at) -> dict:
    now = _now()
    day = datetime.now().strftime("%Y%m%d")
    number = _next_number(conn, "supplier_payments", "payment_number", f"SPY-{day}-")
    applied = money(sum(money(item[1]) for item in allocations))
    conn.execute(
        "INSERT INTO supplier_payments "
        "(payment_number,supplier_id,amount,method,reference,notes,user_id,username,"
        "client_token,status,paid_at,created_at,reversed) "
        "VALUES (?,?,?,?,?,?,?,?,?,'posted',?,?,0)",
        (number, int(supplier_id), money(amount), (method or "cash").strip() or "cash",
         (reference or "").strip(), (notes or "").strip(), user_id, username or "",
         (client_token or None) or None, paid_at or now, now),
    )
    payment_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    saved = []
    for receipt_id, part in allocations:
        part = money(part)
        if part <= 0:
            continue
        conn.execute(
            "INSERT INTO supplier_payment_allocations (payment_id,receipt_id,amount) VALUES (?,?,?)",
            (payment_id, int(receipt_id), part),
        )
        saved.append({"receipt_id": int(receipt_id), "amount": part})
    unapplied = money(money(amount) - applied)
    return {
        "success": True,
        "payment_id": payment_id,
        "payment_number": number,
        "amount": money(amount),
        "applied": applied,
        "unapplied": unapplied,
        "allocations": saved,
        "method": (method or "cash").strip() or "cash",
        "reference": (reference or "").strip(),
    }


def _actor(api) -> dict:
    from desktop.utils.security import client_actor
    return client_actor(api)


def record_payment(api, supplier_id, amount, *, method="cash", reference="", notes="",
                   mode="oldest", allocations=None, client_token="", paid_at="") -> dict:
    from desktop.utils.security import has_permission
    if not has_permission(_actor(api), "supplier.pay"):
        return {"error": "You cannot record a supplier payment.", "status": 403}
    amount = money(amount)
    if amount <= 0 or amount > 99999999:
        return {"error": "Enter a payment amount greater than zero.", "status": 400}
    try:
        supplier_id = int(supplier_id)
    except (TypeError, ValueError):
        return {"error": "Select a supplier.", "status": 400}
    from desktop.utils.api_client import _db, _audit
    db = _db()
    try:
        ensure_schema(db)
        token = (client_token or "").strip()
        db.execute("BEGIN IMMEDIATE")
        if token:
            prior = db.execute(
                "SELECT id, payment_number, amount FROM supplier_payments WHERE client_token=?",
                (token,),
            ).fetchone()
            if prior:
                db.rollback()
                return {
                    "success": True, "duplicate": True,
                    "payment_id": prior["id"], "payment_number": prior["payment_number"],
                    "amount": money(prior["amount"]),
                }
        supplier = db.execute(
            "SELECT id, name FROM suppliers WHERE id=? AND COALESCE(is_active,1)=1",
            (supplier_id,),
        ).fetchone()
        if not supplier:
            db.rollback()
            return {"error": "Supplier not found.", "status": 404}
        chosen = []
        if (mode or "oldest") == "manual":
            open_rows = {int(row["id"]): row for row in _open_invoices(db, supplier_id)}
            requested = 0.0
            for raw in allocations or []:
                try:
                    receipt_id = int(raw.get("receipt_id"))
                    part = money(raw.get("amount"))
                except (TypeError, ValueError, AttributeError):
                    db.rollback()
                    return {"error": "Each allocation needs an invoice and an amount.", "status": 400}
                if part <= 0:
                    continue
                invoice = open_rows.get(receipt_id)
                if not invoice:
                    db.rollback()
                    return {"error": "That invoice is not an open bill for this supplier.", "status": 400}
                if part - invoice["outstanding"] > 0.009:
                    db.rollback()
                    return {"error": "An allocation is larger than the invoice balance.", "status": 400}
                chosen.append((receipt_id, part))
                requested = money(requested + part)
            if requested - amount > 0.009:
                db.rollback()
                return {"error": "The allocations are larger than the payment.", "status": 400}
        else:
            left = amount
            for invoice in _open_invoices(db, supplier_id):
                if left <= 0.009:
                    break
                part = money(min(left, invoice["outstanding"]))
                if part <= 0:
                    continue
                chosen.append((int(invoice["id"]), part))
                left = money(left - part)
        saved = _insert_payment(
            db, supplier_id=supplier_id, amount=amount, method=method,
            reference=reference, notes=notes, user_id=getattr(api, "_user_id", None),
            username=getattr(api, "_username", "") or role, allocations=chosen,
            client_token=token, paid_at=(paid_at or "").strip(),
        )
        db.execute(
            "INSERT INTO supplier_delivery_events (receipt_id,kind,detail,user_id,username,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (None, "payment", f"{saved['payment_number']} {amount}",
             getattr(api, "_user_id", None), getattr(api, "_username", "") or role, _now()),
        )
        db.commit()
        _audit(getattr(api, "_user_id", None), getattr(api, "_username", ""),
               "SUPPLIER_PAYMENT", "inventory",
               f"payment={saved['payment_number']} supplier={supplier_id} amount={amount}")
        saved["supplier_id"] = supplier_id
        saved["supplier_name"] = supplier["name"]
        saved["balances"] = [
            decorate_header(dict(row), _paid_by_receipt(db).get(int(row["id"]), 0))
            for row in db.execute(
                "SELECT * FROM stock_receipts WHERE supplier_id=?", (supplier_id,)
            ).fetchall()
        ]
        return saved
    except sqlite3.IntegrityError:
        try:
            db.rollback()
        except Exception:
            pass
        return {"error": "That payment was already recorded.", "status": 409}
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        return {"error": "Could not record that supplier payment.", "status": 500, "detail": str(exc)}
    finally:
        db.close()


def apply_receipt_payment(conn, api, receipt_id, supplier_id, amount, method, reference) -> dict:
    """Record a payment inside the delivery transaction. Caller owns BEGIN/COMMIT."""
    amount = money(amount)
    if amount <= 0:
        return {"applied": 0, "unapplied": 0}
    header = conn.execute(
        "SELECT grand_total FROM stock_receipts WHERE id=?", (int(receipt_id),)
    ).fetchone()
    total = money(header["grand_total"] if header else 0)
    applied = money(min(amount, total))
    allocations = [(int(receipt_id), applied)] if applied > 0 else []
    return _insert_payment(
        conn, supplier_id=supplier_id, amount=amount, method=method or "cash",
        reference=reference, notes="Paid when the delivery was recorded",
        user_id=getattr(api, "_user_id", None),
        username=getattr(api, "_username", ""), allocations=allocations,
        client_token="", paid_at=_now(),
    )


def release_allocations(conn, receipt_id: int) -> float:
    """A voided invoice no longer holds payments. The money stays as supplier credit."""
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT COALESCE(SUM(amount),0) AS paid FROM supplier_payment_allocations WHERE receipt_id=?",
        (int(receipt_id),),
    ).fetchone()
    released = money(rows["paid"] if rows else 0)
    conn.execute(
        "DELETE FROM supplier_payment_allocations WHERE receipt_id=?",
        (int(receipt_id),),
    )
    return released


def trim_allocations(conn, receipt_id: int, new_total) -> None:
    """If an edit drops the invoice below what was already paid, free the excess."""
    ensure_schema(conn)
    new_total = money(new_total)
    rows = conn.execute(
        "SELECT id, amount FROM supplier_payment_allocations WHERE receipt_id=? ORDER BY id DESC",
        (int(receipt_id),),
    ).fetchall()
    paid = money(sum(money(row["amount"]) for row in rows))
    excess = money(paid - new_total)
    if excess <= 0.009:
        return
    for row in rows:
        if excess <= 0.009:
            break
        part = money(row["amount"])
        take = money(min(excess, part))
        left = money(part - take)
        if left <= 0.009:
            conn.execute("DELETE FROM supplier_payment_allocations WHERE id=?", (row["id"],))
        else:
            conn.execute(
                "UPDATE supplier_payment_allocations SET amount=? WHERE id=?",
                (left, row["id"]),
            )
        excess = money(excess - take)


def shop_summary(conn, start=None, end=None) -> dict:
    ensure_schema(conn)
    today = _today()
    paid = _paid_by_receipt(conn)
    invoices = conn.execute(
        "SELECT r.id, r.supplier_id, r.receipt_number, r.reference_note, r.grand_total, "
        "r.due_date, r.effective_date, r.created_at, COALESCE(r.status,'posted') AS status, "
        "s.name AS supplier_name, s.phone AS supplier_phone "
        "FROM stock_receipts r LEFT JOIN suppliers s ON s.id=r.supplier_id "
        "ORDER BY r.id DESC"
    ).fetchall()
    outstanding = 0.0
    unpaid = partial = overdue_count = 0
    overdue_amount = 0.0
    invoiced_period = 0.0
    by_supplier = {}
    invoice_rows = []
    start_day = _day(start) if start else ""
    end_day = _day(end) if end else ""
    for row in invoices:
        item = decorate_header(dict(row), paid.get(int(row["id"]), 0), today)
        invoice_rows.append(item)
        if item["payment_status"] == "VOIDED":
            continue
        outstanding = money(outstanding + item["outstanding"])
        if item["payment_status"] == "UNPAID":
            unpaid += 1
        elif item["payment_status"] == "PARTIALLY PAID":
            partial += 1
        elif item["payment_status"] == "OVERDUE":
            overdue_count += 1
            overdue_amount = money(overdue_amount + item["outstanding"])
        day = item.get("effective_date") or ""
        if (not start_day or day >= start_day) and (not end_day or day <= end_day):
            if item["payment_status"] != "VOIDED":
                invoiced_period = money(invoiced_period + money(item.get("grand_total")))
        sid = int(item.get("supplier_id") or 0)
        bucket = by_supplier.setdefault(sid, {
            "supplier_id": sid,
            "supplier_name": item.get("supplier_name") or "Supplier",
            "outstanding": 0.0,
            "invoice_count": 0,
        })
        bucket["outstanding"] = money(bucket["outstanding"] + item["outstanding"])
        bucket["invoice_count"] += 1
    pay_sql = (
        "SELECT COALESCE(SUM(amount),0) AS paid FROM supplier_payments "
        "WHERE COALESCE(reversed,0)=0"
    )
    params = []
    if start_day:
        pay_sql += " AND substr(COALESCE(paid_at, created_at),1,10)>=?"
        params.append(start_day)
    if end_day:
        pay_sql += " AND substr(COALESCE(paid_at, created_at),1,10)<=?"
        params.append(end_day)
    paid_period = money(conn.execute(pay_sql, params).fetchone()["paid"])
    advance = money(conn.execute(
        "SELECT COALESCE(SUM(p.amount),0) - COALESCE(("
        "SELECT SUM(a.amount) FROM supplier_payment_allocations a "
        "JOIN supplier_payments pp ON pp.id=a.payment_id "
        "WHERE COALESCE(pp.reversed,0)=0),0) "
        "FROM supplier_payments p WHERE COALESCE(p.reversed,0)=0"
    ).fetchone()[0])
    suppliers = sorted(by_supplier.values(), key=lambda item: item["outstanding"], reverse=True)
    return {
        "outstanding": outstanding,
        "unpaid_count": unpaid,
        "partial_count": partial,
        "overdue_count": overdue_count,
        "overdue_amount": overdue_amount,
        "invoiced_period": invoiced_period,
        "paid_period": paid_period,
        "advance": advance if advance > 0.009 else 0.0,
        "suppliers": suppliers,
        "invoices": invoice_rows,
    }


def statement(conn, supplier_id: int) -> dict:
    ensure_schema(conn)
    supplier = conn.execute(
        "SELECT id, name, phone, email, address, notes FROM suppliers WHERE id=?",
        (int(supplier_id),),
    ).fetchone()
    if not supplier:
        return {"error": "Supplier not found.", "status": 404}
    summary = shop_summary(conn)
    invoices = [row for row in summary["invoices"] if int(row.get("supplier_id") or 0) == int(supplier_id)]
    payments = []
    for row in conn.execute(
        "SELECT * FROM supplier_payments WHERE supplier_id=? ORDER BY id",
        (int(supplier_id),),
    ).fetchall():
        item = dict(row)
        allocs = conn.execute(
            "SELECT receipt_id, amount FROM supplier_payment_allocations WHERE payment_id=?",
            (item["id"],),
        ).fetchall()
        item["allocations"] = [dict(alloc) for alloc in allocs]
        item["applied"] = money(sum(money(alloc["amount"]) for alloc in allocs))
        item["unapplied"] = 0.0 if int(item.get("reversed") or 0) else money(money(item["amount"]) - item["applied"])
        payments.append(item)
    charged = money(sum(money(row.get("grand_total")) for row in invoices if row.get("payment_status") != "VOIDED"))
    outstanding = money(sum(money(row.get("outstanding")) for row in invoices))
    return {
        "supplier": dict(supplier),
        "invoices": invoices,
        "payments": payments,
        "charged": charged,
        "outstanding": outstanding,
        "advance": money(sum(money(row.get("unapplied")) for row in payments)),
    }


def receipt_money(conn, receipt_id: int) -> dict:
    ensure_schema(conn)
    header = conn.execute("SELECT * FROM stock_receipts WHERE id=?", (int(receipt_id),)).fetchone()
    if not header:
        return {"error": "Delivery was not found.", "status": 404}
    paid = _paid_by_receipt(conn).get(int(receipt_id), 0)
    item = decorate_header(dict(header), paid)
    payments = []
    for row in conn.execute(
        "SELECT p.*, a.amount AS allocated "
        "FROM supplier_payment_allocations a "
        "JOIN supplier_payments p ON p.id=a.payment_id "
        "WHERE a.receipt_id=? ORDER BY p.id",
        (int(receipt_id),),
    ).fetchall():
        payments.append(dict(row))
    events = [
        dict(row) for row in conn.execute(
            "SELECT * FROM supplier_delivery_events WHERE receipt_id=? ORDER BY id",
            (int(receipt_id),),
        ).fetchall()
    ]
    item["payments"] = payments
    item["events"] = events
    return item


def _admin(api) -> dict | None:
    from desktop.utils.security import has_permission
    if not has_permission(_actor(api), "supplier.manage"):
        return {"error": "Only an administrator can change a supplier delivery.", "status": 403}
    return None


def backdate_receipt(api, receipt_id, effective_date, reason="") -> dict:
    denied = _admin(api)
    if denied:
        return denied
    day = _day(effective_date)
    if len(day) != 10:
        return {"error": "Enter the delivery date as YYYY-MM-DD.", "status": 400}
    from desktop.utils.api_client import _db, _audit
    db = _db()
    try:
        ensure_schema(db)
        row = db.execute(
            "SELECT id, receipt_number, created_at, effective_date, COALESCE(status,'posted') AS status "
            "FROM stock_receipts WHERE id=?",
            (int(receipt_id),),
        ).fetchone()
        if not row:
            return {"error": "Delivery was not found.", "status": 404}
        if row["status"] == "reversed":
            return {"error": "A reversed delivery cannot be backdated.", "status": 409}
        previous = _day(row["effective_date"] or row["created_at"])
        db.execute(
            "UPDATE stock_receipts SET effective_date=? WHERE id=?",
            (day, int(receipt_id)),
        )
        db.execute(
            "INSERT INTO supplier_delivery_events (receipt_id,kind,detail,user_id,username,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (int(receipt_id), "backdate",
             f"{previous} -> {day}. Recorded at {row['created_at']}. {(reason or '').strip()}",
             getattr(api, "_user_id", None), getattr(api, "_username", ""), _now()),
        )
        db.commit()
        _audit(getattr(api, "_user_id", None), getattr(api, "_username", ""),
               "BACKDATE_RECEIPT", "inventory", f"receipt={row['receipt_number']} {previous}->{day}")
        return {
            "success": True, "receipt_id": int(receipt_id),
            "effective_date": day, "created_at": row["created_at"], "previous": previous,
        }
    finally:
        db.close()


def update_receipt_header(api, receipt_id, *, reference=None, notes=None, due_date=None) -> dict:
    denied = _admin(api)
    if denied:
        return denied
    from desktop.utils.api_client import _db, _audit
    db = _db()
    try:
        ensure_schema(db)
        row = db.execute(
            "SELECT id, receipt_number, COALESCE(status,'posted') AS status FROM stock_receipts WHERE id=?",
            (int(receipt_id),),
        ).fetchone()
        if not row:
            return {"error": "Delivery was not found.", "status": 404}
        if row["status"] == "reversed":
            return {"error": "A reversed delivery cannot be edited.", "status": 409}
        fields = []
        values = []
        if reference is not None:
            fields.append("reference_note=?")
            values.append(str(reference).strip())
        if notes is not None:
            fields.append("notes=?")
            values.append(str(notes).strip())
        if due_date is not None:
            due = _day(due_date)
            fields.append("due_date=?")
            values.append(due or None)
        if not fields:
            return {"error": "Nothing to change.", "status": 400}
        values.append(int(receipt_id))
        db.execute(f"UPDATE stock_receipts SET {', '.join(fields)} WHERE id=?", values)
        db.execute(
            "INSERT INTO supplier_delivery_events (receipt_id,kind,detail,user_id,username,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (int(receipt_id), "edit", "Invoice details updated",
             getattr(api, "_user_id", None), getattr(api, "_username", ""), _now()),
        )
        db.commit()
        _audit(getattr(api, "_user_id", None), getattr(api, "_username", ""),
               "EDIT_RECEIPT", "inventory", f"receipt={row['receipt_number']}")
        return {"success": True, "receipt_id": int(receipt_id)}
    finally:
        db.close()


def request_delivery_action(api, receipt_id, kind, reason, requested_date="") -> dict:
    from desktop.utils.security import has_permission
    role = (getattr(api, "_role", "") or "").lower()
    if not has_permission(_actor(api), "supplier.request"):
        return {"error": "You cannot request that.", "status": 403}
    kind = (kind or "").strip().lower()
    if kind not in ("void", "backdate"):
        return {"error": "Request a void or a backdate.", "status": 400}
    reason = (reason or "").strip()
    if not reason:
        return {"error": "A reason is required.", "status": 400}
    if kind == "backdate" and len(_day(requested_date)) != 10:
        return {"error": "Enter the requested date as YYYY-MM-DD.", "status": 400}
    from desktop.utils.api_client import _db, _audit
    db = _db()
    try:
        ensure_schema(db)
        row = db.execute(
            "SELECT id, receipt_number, COALESCE(status,'posted') AS status FROM stock_receipts WHERE id=?",
            (int(receipt_id),),
        ).fetchone()
        if not row:
            return {"error": "Delivery was not found.", "status": 404}
        if row["status"] == "reversed":
            return {"error": "This delivery is already voided.", "status": 409}
        existing = db.execute(
            "SELECT id, request_number FROM supplier_delivery_requests "
            "WHERE receipt_id=? AND kind=? AND status='pending'",
            (int(receipt_id), kind),
        ).fetchone()
        if existing:
            return {
                "success": True, "duplicate": True,
                "request_id": existing["id"], "request_number": existing["request_number"],
            }
        day = datetime.now().strftime("%Y%m%d")
        number = _next_number(db, "supplier_delivery_requests", "request_number", f"SDR-{day}-")
        db.execute(
            "INSERT INTO supplier_delivery_requests "
            "(request_number,receipt_id,kind,requested_date,reason,status,user_id,username,created_at) "
            "VALUES (?,?,?,?,?,'pending',?,?,?)",
            (number, int(receipt_id), kind, _day(requested_date) or None, reason,
             getattr(api, "_user_id", None), getattr(api, "_username", "") or role, _now()),
        )
        request_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        _audit(getattr(api, "_user_id", None), getattr(api, "_username", ""),
               "REQUEST_DELIVERY", "inventory", f"{kind} {number} receipt={row['receipt_number']}")
        return {"success": True, "request_id": request_id, "request_number": number, "status": "pending"}
    finally:
        db.close()


def list_delivery_requests(conn, status="pending") -> list:
    ensure_schema(conn)
    sql = (
        "SELECT q.*, r.receipt_number, r.grand_total, s.name AS supplier_name "
        "FROM supplier_delivery_requests q "
        "JOIN stock_receipts r ON r.id=q.receipt_id "
        "LEFT JOIN suppliers s ON s.id=r.supplier_id "
    )
    params = []
    if status and status != "all":
        sql += "WHERE q.status=? "
        params.append(status)
    sql += "ORDER BY q.id DESC"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def review_delivery_request(api, request_id, decision, note="", pin="") -> dict:
    denied = _admin(api)
    if denied:
        return denied
    decision = (decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        return {"error": "Approve or reject the request.", "status": 400}
    from desktop.utils.api_client import _db, _audit
    db = _db()
    try:
        ensure_schema(db)
        found = db.execute(
            "SELECT * FROM supplier_delivery_requests WHERE id=?", (int(request_id),)
        ).fetchone()
        if not found:
            return {"error": "Request was not found.", "status": 404}
        row = dict(found)
        if row["status"] != "pending":
            return {"error": "This request was already decided.", "status": 409}
        if int(row["user_id"] or 0) == int(getattr(api, "_user_id", 0) or 0):
            return {"error": "You cannot approve your own request.", "status": 403}
    finally:
        db.close()
    if decision == "reject":
        db = _db()
        try:
            db.execute(
                "UPDATE supplier_delivery_requests SET status='rejected', reviewer_id=?, "
                "reviewer_name=?, review_note=?, reviewed_at=? WHERE id=? AND status='pending'",
                (getattr(api, "_user_id", None), getattr(api, "_username", ""),
                 (note or "").strip(), _now(), int(request_id)),
            )
            db.commit()
            return {"success": True, "status": "rejected", "request_id": int(request_id)}
        finally:
            db.close()
    if row["kind"] == "backdate":
        saved = backdate_receipt(api, row["receipt_id"], row["requested_date"], row["reason"])
        if not saved.get("success"):
            return saved
    elif row["kind"] == "void":
        saved = api.reverse_stock_receipt(
            int(row["receipt_id"]), reason=row["reason"] or "Void request approved", pin=pin,
        )
        if not saved.get("success"):
            return saved
    else:
        return {"error": "This request cannot be applied.", "status": 400}
    db = _db()
    try:
        changed = db.execute(
            "UPDATE supplier_delivery_requests SET status='approved', reviewer_id=?, "
            "reviewer_name=?, review_note=?, reviewed_at=? WHERE id=? AND status='pending'",
            (getattr(api, "_user_id", None), getattr(api, "_username", ""),
             (note or "").strip(), _now(), int(request_id)),
        )
        if changed.rowcount != 1:
            return {"error": "This request was already decided.", "status": 409}
        db.commit()
        _audit(getattr(api, "_user_id", None), getattr(api, "_username", ""),
               "REVIEW_DELIVERY", "inventory", f"approved {row['request_number']}")
        return {"success": True, "status": "approved", "request_id": int(request_id)}
    finally:
        db.close()


def return_receipt_line(api, receipt_id, product_id, quantity, *, reason="", pin="", client_token="") -> dict:
    denied = _admin(api)
    if denied:
        return denied
    try:
        qty = round(float(quantity), 4)
    except (TypeError, ValueError):
        return {"error": "Enter the quantity being returned.", "status": 400}
    if qty <= 0 or qty != qty:
        return {"error": "Enter the quantity being returned.", "status": 400}
    reason = (reason or "").strip() or "Returned to supplier"
    from desktop.utils.api_client import _db, _audit
    db = _db()
    try:
        ensure_schema(db)
        token = (client_token or "").strip()
        if token:
            prior = db.execute(
                "SELECT id FROM supplier_delivery_events WHERE client_token=?", (token,)
            ).fetchone()
            if prior:
                return {"success": True, "duplicate": True, "event_id": prior["id"]}
        denied_pin = api._stock_reduce_authorized(db, pin, "supplier_return")
        if denied_pin:
            return denied_pin
        db.execute("BEGIN IMMEDIATE")
        header = db.execute("SELECT * FROM stock_receipts WHERE id=?", (int(receipt_id),)).fetchone()
        if not header:
            db.rollback()
            return {"error": "Delivery was not found.", "status": 404}
        if (header["status"] or "posted") == "reversed":
            db.rollback()
            return {"error": "A reversed delivery cannot be returned.", "status": 409}
        line = db.execute(
            "SELECT * FROM stock_receipt_lines WHERE receipt_id=? AND product_id=?",
            (int(receipt_id), int(product_id)),
        ).fetchone()
        if not line:
            db.rollback()
            return {"error": "That product is not on this delivery.", "status": 404}
        received = round(float(line["quantity"] or 0), 4)
        already = round(float(line["returned_qty"] or 0), 4)
        if already + qty - received > 0.0001:
            db.rollback()
            return {"error": "You cannot return more than was received.", "status": 400}
        prod = db.execute(
            "SELECT id, name, stock FROM products WHERE id=?", (int(product_id),)
        ).fetchone()
        if not prod:
            db.rollback()
            return {"error": "Product not found", "status": 404}
        old_stock = round(float(prod["stock"] or 0), 4)
        new_stock = round(old_stock - qty, 4)
        if new_stock < -0.0001:
            db.rollback()
            return {"error": f"Not enough {prod['name']} left to return.", "status": 409}
        source = f"{header['receipt_number']}:{prod['id']}"
        shifted = api._shift_purchase_layer(db, prod["id"], source, -qty, close=True)
        if shifted.get("error"):
            db.rollback()
            return shifted
        now = _now()
        changed = db.execute(
            "UPDATE products SET stock=?, updated_at=? WHERE id=? AND COALESCE(stock,0)=?",
            (new_stock, now, prod["id"], float(prod["stock"] or 0)),
        )
        if changed.rowcount != 1:
            db.rollback()
            return {"error": "Stock changed while returning. Try again.", "status": 409}
        new_returned = round(already + qty, 4)
        net = round(received - new_returned, 4)
        line_total = money(net * float(line["unit_cost"] or 0))
        db.execute(
            "UPDATE stock_receipt_lines SET returned_qty=?, line_total=? WHERE id=?",
            (new_returned, line_total, line["id"]),
        )
        total = db.execute(
            "SELECT COALESCE(SUM(line_total),0) FROM stock_receipt_lines WHERE receipt_id=?",
            (header["id"],),
        ).fetchone()[0]
        grand = money(total)
        db.execute("UPDATE stock_receipts SET grand_total=? WHERE id=?", (grand, header["id"]))
        trim_allocations(db, header["id"], grand)
        db.execute(
            "INSERT INTO stock_movements "
            "(product_id,product_name,movement_type,qty_before,qty_change,qty_after,"
            "reference,reason,user_id,username) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (prod["id"], prod["name"], "PURCHASE_RETURN", old_stock, -qty, new_stock,
             f"RETURN|{header['receipt_number']}|{prod['id']}|{now}",
             f"Returned {qty:g} from {header['receipt_number']} — {reason}",
             getattr(api, "_user_id", None), getattr(api, "_username", "")),
        )
        db.execute(
            "INSERT INTO supplier_delivery_events "
            "(receipt_id,kind,detail,user_id,username,client_token,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (header["id"], "return",
             f"{prod['name']} returned {qty:g}. Received stays {received:g}. Net {net:g}.",
             getattr(api, "_user_id", None), getattr(api, "_username", ""), token or None, now),
        )
        db.commit()
        _audit(getattr(api, "_user_id", None), getattr(api, "_username", ""),
               "SUPPLIER_RETURN", "inventory", f"receipt={header['receipt_number']} qty={qty}")
        return {
            "success": True, "receipt_id": header["id"],
            "quantity_received": received, "returned_qty": new_returned,
            "net_quantity": net, "grand_total": grand,
            "old_stock": old_stock, "new_stock": new_stock,
        }
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        return {"error": "Could not record that supplier return.", "status": 500, "detail": str(exc)}
    finally:
        db.close()
