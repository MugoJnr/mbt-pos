"""Cashier backdating for records other than a sale.

A past date from someone who cannot post a business day is stored here.
Nothing in stock, cash, or the journals moves until a different authorised
user approves the same request once.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from desktop.utils.shop_time import business_day_iso, parse_sale_date, shop_today


class DatedActionError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


_REVIEW_ROLES = {"manager", "admin", "superadmin"}
_KINDS = {
    "consumption",
    "expense",
    "supplier_delivery",
    "supplier_payment",
    "debt_payment",
    "stock_adjustment",
    "customer_return",
    "supplier_return",
    "journal",
    "cash_transfer",
}
_DATE_KEYS = (
    "date", "expense_date", "effective_date", "paid_at",
    "payment_date", "business_date", "sale_date",
    "entry_date", "transfer_date",
)


def warning_for(day: str) -> str:
    parsed = parse_sale_date(str(day or "")[:10])
    if parsed is None:
        label = str(day or "").strip()
    else:
        label = f"{parsed.day} {parsed.strftime('%B')} {parsed.year}"
    return (
        f"You're recording this transaction for {label}, not today's date. "
        "This is a backdated transaction and requires administrator approval "
        "before it is posted."
    )


def offline_message() -> str:
    return (
        "This till is offline, so a backdated transaction cannot be approved "
        "safely. It was not recorded."
    )


def ensure_schema(db) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS dated_action_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            kind TEXT NOT NULL,
            requester_id INTEGER NOT NULL,
            requester_name TEXT,
            business_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            payload_json TEXT NOT NULL,
            client_token TEXT,
            review_note TEXT,
            reviewer_id INTEGER,
            reviewer_name TEXT,
            submitted_at TEXT NOT NULL,
            decided_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            claim_token TEXT,
            claim_at TEXT,
            result_json TEXT
        )"""
    )
    db.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_dated_action_token
           ON dated_action_requests(client_token)
           WHERE client_token IS NOT NULL AND client_token != ''"""
    )


def consider(db, actor: dict, kind: str, business_date: str, payload: dict, *, offline: bool = False):
    """Return a pending or error response, or None when the caller should post now."""
    ensure_schema(db)
    kind = (kind or "").strip().lower()
    if kind not in _KINDS:
        return {"error": "That record cannot be backdated.", "status": 400}
    supplied = str((payload or {}).get("client_token") or "").strip()
    if supplied:
        existing = db.execute(
            "SELECT * FROM dated_action_requests WHERE client_token=?",
            (supplied,),
        ).fetchone()
        if existing and not _release_closed_token(db, existing):
            return _public(existing, duplicate=True)
    day, problem = _day(business_date)
    if problem and business_date:
        return {"error": problem, "status": 400}
    if not day:
        day = shop_today().isoformat()
    if day > shop_today().isoformat():
        return {"error": "A business date cannot be in the future.", "status": 400}
    if day == shop_today().isoformat():
        return None
    closed = _closed(db, day)
    if closed:
        return {"error": closed, "status": 409}
    if _can_post(actor):
        return None
    if offline:
        return {"error": offline_message(), "status": 409}
    body = dict(payload or {})
    for secret in ("_dated_replay", "_requester_id", "_requester_name"):
        body.pop(secret, None)
    token = str(body.get("client_token") or "").strip() or uuid.uuid4().hex
    body["client_token"] = token
    body["_requester_id"] = actor.get("id")
    body["_requester_name"] = actor.get("full_name") or actor.get("username") or ""
    for key in _DATE_KEYS:
        if key in body:
            body[key] = day
    body["date"] = day
    backdate_reason = str(body.get("backdate_reason") or "").strip()
    if len(backdate_reason) < 3 or backdate_reason == "Other":
        return {"error": "Choose a reason for this past date. If you choose Other, write what happened.", "status": 400}
    existing = db.execute(
        "SELECT * FROM dated_action_requests WHERE client_token=?",
        (token,),
    ).fetchone()
    if existing and not _release_closed_token(db, existing):
        return _public(existing, duplicate=True)
    now = _now()
    reference = _next_reference(db)
    db.execute(
        """INSERT INTO dated_action_requests
           (reference, kind, requester_id, requester_name, business_date, status,
            payload_json, client_token, submitted_at, created_at, updated_at)
           VALUES (?,?,?,?,?,'pending',?,?,?,?,?)""",
        (
            reference, kind, int(actor.get("id") or 0),
            actor.get("full_name") or actor.get("username") or "",
            day, json.dumps(body, default=str), token, now, now, now,
        ),
    )
    db.commit()
    row = db.execute(
        "SELECT * FROM dated_action_requests WHERE reference=?",
        (reference,),
    ).fetchone()
    return _public(row, duplicate=False)


def approve(db, actor: dict, request_id: int, poster, note: str = "") -> dict:
    ensure_schema(db)
    db.execute("BEGIN IMMEDIATE")
    row = _locked(db, request_id)
    if not row:
        db.rollback()
        raise DatedActionError("Request was not found.", 404)
    if _blocks_own_review(actor, row["requester_id"]):
        db.rollback()
        raise DatedActionError("You cannot review your own request.", 403)
    try:
        _require_review(actor)
    except DatedActionError:
        db.rollback()
        raise
    if row["status"] == "approved":
        db.rollback()
        body = _public(row, duplicate=True)
        body["already_approved"] = True
        return body
    if row["status"] != "pending":
        db.rollback()
        raise DatedActionError("Only a pending request can be approved.", 409)
    if _claim_is_fresh(row):
        db.rollback()
        raise DatedActionError("This request is already being approved.", 409)
    closed = _closed(db, row["business_date"])
    if closed:
        db.rollback()
        raise DatedActionError(closed, 409)
    claim = uuid.uuid4().hex
    now = _now()
    changed = db.execute(
        """UPDATE dated_action_requests
           SET claim_token=?, claim_at=?, updated_at=?
           WHERE id=? AND status='pending'""",
        (claim, now, now, row["id"]),
    )
    if changed.rowcount != 1:
        db.rollback()
        raise DatedActionError("This request was already decided.", 409)
    db.commit()
    payload = json.loads(row["payload_json"] or "{}")
    if not isinstance(payload, dict):
        payload = {}
    day = row["business_date"]
    for key in _DATE_KEYS:
        if key in payload:
            payload[key] = day
    payload["date"] = day
    try:
        result = poster(row["kind"], payload, day) or {}
    except Exception as exc:
        _release_claim(db, row["id"], claim, str(exc))
        raise DatedActionError("The approval could not be posted.", 409) from exc
    if result.get("error"):
        _release_claim(db, row["id"], claim, result.get("error"))
        raise DatedActionError(str(result.get("error")), int(result.get("status") or 400))
    finished = _now()
    saved = db.execute(
        """UPDATE dated_action_requests
           SET status='approved', reviewer_id=?, reviewer_name=?, review_note=?,
               decided_at=?, updated_at=?, claim_token=NULL, claim_at=NULL, result_json=?
           WHERE id=? AND status='pending' AND claim_token=?""",
        (
            actor.get("id"), actor.get("full_name") or actor.get("username") or "",
            (note or "").strip(), finished, finished,
            json.dumps(result, default=str), row["id"], claim,
        ),
    )
    db.commit()
    if saved.rowcount != 1:
        current = db.execute(
            "SELECT * FROM dated_action_requests WHERE id=?", (row["id"],)
        ).fetchone()
        if current and current["status"] == "approved":
            body = _public(current, duplicate=True)
            body["already_approved"] = True
            return body
        raise DatedActionError("This request was already decided.", 409)
    fresh = db.execute(
        "SELECT * FROM dated_action_requests WHERE id=?", (row["id"],)
    ).fetchone()
    body = _public(fresh, duplicate=False)
    body["result"] = result
    body["already_approved"] = False
    return body


def reject(db, actor: dict, request_id: int, reason: str) -> dict:
    ensure_schema(db)
    _require_review(actor)
    reason = (reason or "").strip()
    if not reason:
        raise DatedActionError("Enter a reason before rejecting the request.")
    db.execute("BEGIN IMMEDIATE")
    row = _locked(db, request_id)
    if not row:
        db.rollback()
        raise DatedActionError("Request was not found.", 404)
    if _blocks_own_review(actor, row["requester_id"]):
        db.rollback()
        raise DatedActionError("You cannot review your own request.", 403)
    if row["status"] == "rejected":
        db.rollback()
        return _public(row, duplicate=True)
    if row["status"] != "pending":
        db.rollback()
        raise DatedActionError("Only a pending request can be rejected.", 409)
    now = _now()
    changed = db.execute(
        """UPDATE dated_action_requests
           SET status='rejected', reviewer_id=?, reviewer_name=?, review_note=?,
               decided_at=?, updated_at=?, claim_token=NULL, claim_at=NULL
           WHERE id=? AND status='pending'""",
        (
            actor.get("id"), actor.get("full_name") or actor.get("username") or "",
            reason, now, now, row["id"],
        ),
    )
    if changed.rowcount != 1:
        db.rollback()
        raise DatedActionError("This request was already decided.", 409)
    db.commit()
    fresh = db.execute(
        "SELECT * FROM dated_action_requests WHERE id=?", (row["id"],)
    ).fetchone()
    return _public(fresh, duplicate=False)


def cancel(db, actor: dict, request_id: int, reason: str = "") -> dict:
    ensure_schema(db)
    reason = (reason or "").strip()
    db.execute("BEGIN IMMEDIATE")
    row = _locked(db, request_id)
    if not row:
        db.rollback()
        raise DatedActionError("Request was not found.", 404)
    if int(row["requester_id"] or 0) != int(actor.get("id") or 0) and not _can_post(actor):
        db.rollback()
        raise DatedActionError("You cannot cancel this request.", 403)
    if row["status"] == "cancelled":
        db.rollback()
        return _public(row, duplicate=True)
    if row["status"] != "pending":
        db.rollback()
        raise DatedActionError("Only a pending request can be cancelled.", 409)
    now = _now()
    db.execute(
        """UPDATE dated_action_requests
           SET status='cancelled', review_note=?, updated_at=?, decided_at=?
           WHERE id=? AND status='pending'""",
        (reason, now, now, row["id"]),
    )
    db.commit()
    fresh = db.execute(
        "SELECT * FROM dated_action_requests WHERE id=?", (row["id"],)
    ).fetchone()
    return _public(fresh, duplicate=False)


def get_request(db, actor: dict, request_id: int) -> dict:
    ensure_schema(db)
    row = db.execute(
        "SELECT * FROM dated_action_requests WHERE id=?", (int(request_id),)
    ).fetchone()
    if not row:
        raise DatedActionError("Request was not found.", 404)
    if not _can_see(actor, row):
        raise DatedActionError("Request was not found.", 404)
    return _public(row, duplicate=False, detail=True, actor=actor)


def list_requests(db, actor: dict) -> list:
    ensure_schema(db)
    if _role(actor) in _REVIEW_ROLES:
        rows = db.execute(
            "SELECT * FROM dated_action_requests ORDER BY id DESC"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM dated_action_requests WHERE requester_id=? ORDER BY id DESC",
            (actor.get("id"),),
        ).fetchall()
    return [_public(row, duplicate=False, actor=actor) for row in rows]


def _release_closed_token(db, row) -> bool:
    """A rejected or cancelled request must not block the next attempt."""
    status = str(row["status"] or "")
    if status not in ("rejected", "cancelled"):
        return False
    db.execute(
        "UPDATE dated_action_requests SET client_token=NULL WHERE id=? AND status=?",
        (row["id"], status),
    )
    return True


def _release_claim(db, request_id, claim, message) -> None:
    db.execute(
        """UPDATE dated_action_requests
           SET claim_token=NULL, claim_at=NULL, review_note=?, updated_at=?
           WHERE id=? AND status='pending' AND claim_token=?""",
        (str(message or "")[:400], _now(), int(request_id), claim),
    )
    db.commit()


def _claim_is_fresh(row) -> bool:
    token = row["claim_token"] or ""
    if not token:
        return False
    try:
        started = datetime.fromisoformat(str(row["claim_at"] or ""))
    except ValueError:
        return False
    return datetime.now() - started < timedelta(seconds=60)


def _public(row, *, duplicate: bool, detail: bool = False, actor: dict | None = None) -> dict:
    record = dict(row)
    payload = {}
    try:
        payload = json.loads(record.get("payload_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if actor is not None:
        from desktop.utils.security import sees_product_cost
        if not sees_product_cost(actor):
            for item in payload.get("items") or payload.get("lines") or []:
                if isinstance(item, dict):
                    item.pop("unit_cost", None)
                    item.pop("total_cost", None)
                    item.pop("cost_price", None)
            payload.pop("unit_cost", None)
    result = None
    if record.get("result_json"):
        try:
            result = json.loads(record["result_json"])
        except json.JSONDecodeError:
            result = None
    body = {
        "id": record["id"],
        "reference": record["reference"],
        "kind": record["kind"],
        "type": record["kind"],
        "status": record["status"],
        "business_date": record["business_date"],
        "requester_id": record["requester_id"],
        "requester_name": record["requester_name"],
        "submitted_at": record["submitted_at"],
        "created_at": record["created_at"],
        "decided_at": record["decided_at"],
        "updated_at": record["updated_at"],
        "review_note": record["review_note"],
        "reviewer_id": record["reviewer_id"],
        "reviewer_name": record["reviewer_name"],
        "backdate_reason": str(payload.get("backdate_reason") or "").strip(),
        "pending_approval": record["status"] == "pending",
        "posted": record["status"] == "approved",
        "duplicate": duplicate,
        "warning": warning_for(record["business_date"]) if record["status"] == "pending" else "",
        "result": result,
    }
    if detail:
        body["payload"] = payload
    return body


def _day(raw: str):
    text = str(raw or "").strip()
    if not text:
        return shop_today().isoformat(), None
    parsed = parse_sale_date(text[:10])
    if parsed is None:
        return None, "Enter a valid business date."
    return business_day_iso(parsed), None


def _closed(db, day: str):
    try:
        from desktop.utils.accounting_engine import PeriodClosedError, assert_period_open
        assert_period_open(db, str(day))
    except PeriodClosedError as exc:
        return str(exc)
    except Exception:
        return None
    return None


def _can_post(actor: dict) -> bool:
    from desktop.utils.security import has_permission
    return has_permission(actor or {}, "sales.business_day")


def _blocks_own_review(actor: dict, requester_id) -> bool:
    """A Super Admin may decide a request they created. Other roles may not."""
    if _role(actor) == "superadmin":
        return False
    return int(requester_id or 0) == int((actor or {}).get("id") or 0)


def _require_review(actor: dict) -> None:
    if _role(actor) not in _REVIEW_ROLES:
        raise DatedActionError("Manager or admin access required.", 403)


def _can_see(actor, row) -> bool:
    if _role(actor) in _REVIEW_ROLES:
        return True
    return int(row["requester_id"] or 0) == int((actor or {}).get("id") or 0)


def _role(actor: dict) -> str:
    return str((actor or {}).get("role") or "").strip().lower()


def _locked(db, request_id: int):
    return db.execute(
        "SELECT * FROM dated_action_requests WHERE id=?",
        (int(request_id),),
    ).fetchone()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _next_reference(db) -> str:
    stamp = datetime.now().strftime("%Y%m%d")
    prefix = f"DAR-{stamp}-"
    count = db.execute(
        "SELECT COUNT(*) AS c FROM dated_action_requests WHERE reference LIKE ?",
        (prefix + "%",),
    ).fetchone()
    number = int(count["c"] if hasattr(count, "keys") else count[0]) + 1
    return f"{prefix}{number:04d}"
