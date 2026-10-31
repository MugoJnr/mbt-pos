"""Void-request viewing and correction. Approving still uses the existing approval path."""
import json
from datetime import datetime


OPEN_STATUSES = ("pending", "returned", "escalated")
EDIT_STATUSES = ("pending", "returned")


def _history(meta: dict) -> list:
    history = meta.get("history")
    return history if isinstance(history, list) else []


def _load_meta(raw) -> dict:
    try:
        meta = json.loads(raw or "{}")
    except json.JSONDecodeError:
        meta = {}
    return meta if isinstance(meta, dict) else {}


def _stamp(meta: dict, action: str, actor: str, **extra) -> dict:
    entry = {"at": datetime.now().isoformat(timespec="seconds"), "action": action, "by": actor}
    entry.update({key: value for key, value in extra.items() if value})
    history = _history(meta)
    history.append(entry)
    meta["history"] = history[-30:]
    return meta


def list_void_requests(db, user: dict, filters: dict) -> dict:
    role = (user.get("role") or "").lower()
    if role not in ("cashier", "manager", "admin", "superadmin"):
        return {"error": "You cannot view void requests.", "http_status": 403}
    clauses = ["type='void'"]
    params = []
    if role == "cashier":
        clauses.append("requested_by_id=?")
        params.append(user.get("id"))
    status = (filters.get("status") or "").strip().lower()
    if status and status != "all":
        clauses.append("status=?")
        params.append(status)
    query = (filters.get("q") or "").strip()
    if query:
        clauses.append("(title LIKE ? OR details LIKE ? OR requested_by LIKE ? OR meta_json LIKE ?)")
        like = f"%{query}%"
        params.extend([like, like, like, like])
    start = (filters.get("start") or "").strip()
    end = (filters.get("end") or "").strip()
    if start:
        clauses.append("date(created_at)>=?")
        params.append(start)
    if end:
        clauses.append("date(created_at)<=?")
        params.append(end)
    where = " WHERE " + " AND ".join(clauses)
    total = db.execute(f"SELECT COUNT(*) FROM cc_approvals{where}", params).fetchone()[0]
    try:
        limit = min(100, max(1, int(filters.get("limit") or 50)))
        offset = max(0, int(filters.get("offset") or 0))
    except (TypeError, ValueError):
        limit, offset = 50, 0
    rows = db.execute(
        f"SELECT * FROM cc_approvals{where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return {"requests": [_public(row) for row in rows], "total": int(total)}


def get_void_request(db, user: dict, request_id: int) -> dict:
    role = (user.get("role") or "").lower()
    row = db.execute("SELECT * FROM cc_approvals WHERE id=? AND type='void'", (int(request_id),)).fetchone()
    if not row:
        return {"error": "That void request is not in this shop.", "http_status": 404}
    if role == "cashier" and int(row["requested_by_id"] or 0) != int(user.get("id") or 0):
        return {"error": "You cannot view this void request.", "http_status": 403}
    if role not in ("cashier", "manager", "admin", "superadmin"):
        return {"error": "You cannot view void requests.", "http_status": 403}
    body = _public(row)
    meta = _load_meta(row["meta_json"])
    sale_id = int(meta.get("sale_id") or 0)
    sale = db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone() if sale_id else None
    if not sale:
        body["receipt"] = None
        body["receipt_note"] = "The linked receipt is not in this shop."
        body["lines"] = []
    else:
        body["receipt"] = {
            "id": sale["id"],
            "receipt_number": sale["receipt_number"],
            "status": sale["status"],
            "total": sale["total"],
            "subtotal": sale["subtotal"] if "subtotal" in sale.keys() else sale["total"],
            "discount": sale["discount"] if "discount" in sale.keys() else 0,
            "tax": sale["tax"] if "tax" in sale.keys() else 0,
            "amount_paid": sale["amount_paid"] if "amount_paid" in sale.keys() else sale["total"],
            "change_amount": sale["change_amount"] if "change_amount" in sale.keys() else 0,
            "payment_method": sale["payment_method"] if "payment_method" in sale.keys() else "",
            "cashier_name": sale["cashier_name"] if "cashier_name" in sale.keys() else "",
            "customer_name": sale["customer_name"] if "customer_name" in sale.keys() else "",
            "customer_phone": sale["customer_phone"] if "customer_phone" in sale.keys() else "",
            "sale_date": sale["sale_date"] if "sale_date" in sale.keys() else "",
            "created_at": sale["created_at"] if "created_at" in sale.keys() else "",
            "notes": sale["notes"] if "notes" in sale.keys() else "",
        }
        from desktop.utils.payment_tenders import explain_sale_payments
        body["payments"] = explain_sale_payments(dict(sale))
        body["receipt"]["payments"] = body["payments"]
        if not body["receipt"]["customer_name"] and "customer_id" in sale.keys() and sale["customer_id"]:
            customer = db.execute(
                "SELECT name, phone FROM customers WHERE id=?",
                (sale["customer_id"],),
            ).fetchone()
            if customer:
                body["receipt"]["customer_name"] = customer["name"] or ""
                body["receipt"]["customer_phone"] = customer["phone"] or ""
        body["receipt_note"] = ""
        lines = db.execute(
            "SELECT product_name, quantity, unit_price, total FROM sale_items WHERE sale_id=?",
            (sale["id"],),
        ).fetchall()
        body["lines"] = [dict(line) for line in lines]
    body["audit"] = []
    try:
        events = db.execute(
            "SELECT id, action, username, details, created_at FROM audit_log "
            "WHERE module='sales' AND (details LIKE ? OR details LIKE ?) "
            "ORDER BY id DESC LIMIT 8",
            (f"%sale_id={sale_id}%", f"%approval={request_id}%"),
        ).fetchall()
        body["audit"] = [dict(event) for event in events]
    except Exception:
        body["audit"] = []
    return body


def correct_void_request(db, user: dict, request_id: int, reason: str) -> dict:
    reason = (reason or "").strip()
    if len(reason) < 3:
        return {"error": "Enter a reason.", "http_status": 400}
    row = _editable(db, user, request_id)
    if isinstance(row, dict):
        return row
    meta = _load_meta(row["meta_json"])
    meta.setdefault("original_reason", row["details"] or "")
    meta["current_reason"] = reason
    actor = user.get("username") or user.get("full_name") or ""
    meta = _stamp(meta, "corrected", actor, reason=reason)
    db.execute(
        "UPDATE cc_approvals SET details=?, meta_json=?, updated_at=? WHERE id=? AND status IN ('pending','returned')",
        (reason, json.dumps(meta), datetime.now().isoformat(timespec="seconds"), int(request_id)),
    )
    return {"success": True, "id": int(request_id), "status": row["status"]}


def resubmit_void_request(db, user: dict, request_id: int) -> dict:
    row = _editable(db, user, request_id)
    if isinstance(row, dict):
        return row
    if (row["status"] or "") != "returned":
        return {"error": "Only a returned request can be sent back for review.", "http_status": 409}
    meta = _load_meta(row["meta_json"])
    if not str(meta.get("current_reason") or "").strip():
        return {"error": "Correct the reason before sending it back.", "http_status": 400}
    actor = user.get("username") or user.get("full_name") or ""
    meta = _stamp(meta, "resubmitted", actor, reason=meta.get("current_reason"))
    db.execute(
        "UPDATE cc_approvals SET status='pending', meta_json=?, updated_at=? "
        "WHERE id=? AND status='returned'",
        (json.dumps(meta), datetime.now().isoformat(timespec="seconds"), int(request_id)),
    )
    return {"success": True, "id": int(request_id), "status": "pending"}


def return_void_request(db, user: dict, request_id: int, note: str) -> dict:
    role = (user.get("role") or "").lower()
    if role not in ("manager", "admin", "superadmin"):
        return {"error": "You cannot return a void request.", "http_status": 403}
    note = (note or "").strip()
    if len(note) < 3:
        return {"error": "Enter a comment for the requester.", "http_status": 400}
    row = db.execute(
        "SELECT * FROM cc_approvals WHERE id=? AND type='void'", (int(request_id),)
    ).fetchone()
    if not row:
        return {"error": "That void request is not in this shop.", "http_status": 404}
    if (row["status"] or "") not in ("pending", "escalated"):
        return {"error": "This request is no longer waiting for review.", "http_status": 409}
    meta = _stamp(_load_meta(row["meta_json"]), "returned", user.get("username") or "", note=note)
    db.execute(
        "UPDATE cc_approvals SET status='returned', reviewed_by=?, reviewed_by_id=?, "
        "review_note=?, meta_json=?, updated_at=? WHERE id=? AND status IN ('pending','escalated')",
        (
            user.get("username") or user.get("full_name") or "",
            user.get("id"),
            note,
            json.dumps(meta),
            datetime.now().isoformat(timespec="seconds"),
            int(request_id),
        ),
    )
    return {"success": True, "id": int(request_id), "status": "returned"}


def close_open_for_sale(db, sale_id: int, actor: str) -> int:
    """Close requests that would otherwise void an already-voided receipt."""
    closed = 0
    rows = db.execute(
        "SELECT id, meta_json, status FROM cc_approvals WHERE type='void' AND status IN ('pending','returned','escalated')"
    ).fetchall()
    now = datetime.now().isoformat(timespec="seconds")
    for row in rows:
        meta = _load_meta(row["meta_json"])
        try:
            linked = int(meta.get("sale_id") or 0)
        except (TypeError, ValueError):
            linked = 0
        if linked != int(sale_id):
            continue
        meta = _stamp(meta, "closed", actor, note="The receipt was voided directly.")
        db.execute(
            "UPDATE cc_approvals SET status='cancelled', review_note=?, meta_json=?, updated_at=? WHERE id=?",
            ("The receipt was voided directly. This request was not run again.", json.dumps(meta), now, row["id"]),
        )
        closed += 1
    return closed


def _editable(db, user: dict, request_id: int):
    role = (user.get("role") or "").lower()
    row = db.execute(
        "SELECT * FROM cc_approvals WHERE id=? AND type='void'", (int(request_id),)
    ).fetchone()
    if not row:
        return {"error": "That void request is not in this shop.", "http_status": 404}
    if (row["status"] or "") not in EDIT_STATUSES:
        return {"error": "This request can no longer be edited.", "http_status": 409}
    owner = int(row["requested_by_id"] or 0) == int(user.get("id") or 0)
    if role == "superadmin" or owner:
        return row
    return {"error": "You cannot edit this void request.", "http_status": 403}


def _public(row) -> dict:
    meta = _load_meta(row["meta_json"])
    original = meta.get("original_reason") or row["details"] or ""
    current = meta.get("current_reason") or original
    return {
        "id": row["id"],
        "receipt_number": meta.get("receipt_number") or "",
        "sale_id": meta.get("sale_id"),
        "requested_by": row["requested_by"] or "",
        "requested_by_id": row["requested_by_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"] if "updated_at" in row.keys() else "",
        "amount": row["amount"],
        "status": row["status"],
        "original_reason": original,
        "current_reason": current,
        "reviewed_by": row["reviewed_by"] or "",
        "review_note": row["review_note"] or "",
        "history": _history(meta),
    }
