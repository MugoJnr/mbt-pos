"""One list of the request workflows this shop actually stores.

Creation and approval stay in the existing backdating, void, approval, and
stock-adjustment paths. This module only reads them.
"""
from __future__ import annotations

_REVIEW_ROLES = {"manager", "admin", "superadmin"}
_STAFF_ROLES = _REVIEW_ROLES | {"cashier"}
_AWAITING = {"submitted", "pending", "escalated"}
_TYPE_LABELS = {
    "backdated_sale": "Backdated sale",
    "void": "Sale void",
    "consumption_void": "Consumption void",
    "refund": "Refund",
    "large_discount": "Large discount",
    "price_override": "Price change",
    "expense": "Expense",
    "credit": "Credit",
    "stock_adjust": "Stock adjustment",
    "stock_adjustment": "Stock adjustment",
    "supplier_void": "Supplier delivery void",
    "supplier_backdate": "Supplier delivery backdate",
}
_STATUS_LABELS = {
    "submitted": "Pending approval",
    "pending": "Pending approval",
    "draft": "Draft",
    "approved": "Approved",
    "rejected": "Rejected",
    "returned": "Returned for correction",
    "withdrawn": "Withdrawn",
    "escalated": "Escalated",
}


def _role(actor: dict) -> str:
    return str((actor or {}).get("role") or "").strip().lower()


def _tables(db) -> set[str]:
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _label(status: str) -> str:
    key = (status or "").strip().lower()
    return _STATUS_LABELS.get(key, key.replace("_", " ").title() or "Unknown")


def _reviewers_for(kind: str) -> set[str]:
    if kind in ("supplier_void", "supplier_backdate"):
        return {"admin", "superadmin"}
    return _REVIEW_ROLES


def _next_action(actor: dict, requester_id, status: str, kind: str = "") -> str:
    key = (status or "").strip().lower()
    own = requester_id is not None and int(requester_id or 0) == int((actor or {}).get("id") or 0)
    if key in _AWAITING:
        if _role(actor) in _reviewers_for(kind) and not own:
            return "Awaiting your review"
        if own:
            return "Waiting for another reviewer"
        return "Awaiting review"
    if key in {"returned", "draft"} and own:
        return "Needs your correction"
    if key == "approved":
        return "Completed"
    if key in {"rejected", "withdrawn"}:
        return "Closed"
    if key == "escalated":
        return "Escalated"
    return ""


def _row(**fields) -> dict:
    status = str(fields.get("status") or "")
    kind = str(fields.get("type") or "")
    return {
        "source": fields.get("source"),
        "source_id": fields.get("source_id"),
        "reference": fields.get("reference") or "",
        "type": kind,
        "type_label": _TYPE_LABELS.get(kind, kind.replace("_", " ").title()),
        "subject": fields.get("subject") or "",
        "requester": fields.get("requester") or "",
        "requester_id": fields.get("requester_id"),
        "submitted_at": fields.get("submitted_at") or "",
        "business_date": fields.get("business_date") or "",
        "amount": fields.get("amount"),
        "impact": fields.get("impact") or "",
        "reason": fields.get("reason") or "",
        "status": status,
        "status_label": _label(status),
        "next_action": _next_action(fields.get("actor") or {}, fields.get("requester_id"), status, kind),
        "updated_at": fields.get("updated_at") or fields.get("submitted_at") or "",
    }


def _matches(item: dict, filters: dict, actor: dict) -> bool:
    queue = (filters.get("queue") or "all").strip().lower()
    kind = (filters.get("type") or "").strip().lower()
    status = (filters.get("status") or "").strip().lower()
    query = (filters.get("q") or "").strip().lower()
    if kind and item["type"] != kind and item["type_label"].lower() != kind:
        return False
    if status and item["status"] != status:
        return False
    own = int(item.get("requester_id") or 0) == int((actor or {}).get("id") or 0)
    if queue == "mine" and not own:
        return False
    if queue == "action":
        if _role(actor) in _reviewers_for(item.get("type") or ""):
            if item["status"] not in _AWAITING or own:
                return False
        elif item["status"] not in {"returned", "draft"} or not own:
            return False
    elif queue == "pending" and item["status"] not in _AWAITING:
        return False
    elif queue in {"approved", "rejected", "returned", "withdrawn", "draft"} and item["status"] != queue:
        return False
    if query:
        blob = " ".join(
            str(item.get(key) or "")
            for key in ("reference", "type_label", "subject", "requester", "reason", "impact")
        ).lower()
        if query not in blob:
            return False
    return True


def _backdates(db, actor) -> list[dict]:
    own = "" if _role(actor) in _REVIEW_ROLES else "WHERE cashier_id=?"
    params = () if not own else (actor.get("id"),)
    rows = db.execute(f"SELECT * FROM backdate_requests {own} ORDER BY id DESC", params).fetchall()
    items = []
    for row in rows:
        record = dict(row)
        total = None
        try:
            sales = db.execute(
                "SELECT amount_paid FROM backdate_sales WHERE request_id=?",
                (record["id"],),
            ).fetchall()
            total = round(sum(float(item["amount_paid"] or 0) for item in sales), 2)
        except Exception:
            total = None
        items.append(_row(
            actor=actor,
            source="backdate",
            source_id=record["id"],
            reference=record.get("reference"),
            type="backdated_sale",
            subject=record.get("business_date") or "",
            requester=record.get("cashier_name"),
            requester_id=record.get("cashier_id"),
            submitted_at=record.get("submitted_at") or record.get("created_at"),
            business_date=record.get("business_date"),
            amount=total,
            impact="" if total is None else f"KES {total:,.2f}",
            reason=record.get("reason"),
            status=record.get("status"),
            updated_at=record.get("updated_at"),
        ))
    return items


def _approvals(db, actor) -> list[dict]:
    own = "" if _role(actor) in _REVIEW_ROLES else "WHERE requested_by_id=?"
    params = () if not own else (actor.get("id"),)
    rows = db.execute(f"SELECT * FROM cc_approvals {own} ORDER BY id DESC", params).fetchall()
    items = []
    for row in rows:
        record = dict(row)
        kind = str(record.get("type") or "approval")
        amount = record.get("amount")
        items.append(_row(
            actor=actor,
            source="approval",
            source_id=record["id"],
            reference=record.get("title") or f"APR-{record['id']}",
            type=kind,
            subject=record.get("title") or "",
            requester=record.get("requested_by"),
            requester_id=record.get("requested_by_id"),
            submitted_at=record.get("created_at"),
            amount=amount,
            impact="" if amount in (None, "") else f"KES {float(amount):,.2f}",
            reason=record.get("details") or record.get("review_note") or "",
            status=record.get("status"),
            updated_at=record.get("updated_at"),
        ))
    return items


def _stock(db, actor) -> list[dict]:
    own = "" if _role(actor) in _REVIEW_ROLES else "WHERE user_id=?"
    params = () if not own else (actor.get("id"),)
    rows = db.execute(
        f"SELECT * FROM stock_adjustment_requests {own} ORDER BY id DESC",
        params,
    ).fetchall()
    items = []
    for row in rows:
        record = dict(row)
        qty = record.get("requested_qty")
        items.append(_row(
            actor=actor,
            source="stock",
            source_id=record["id"],
            reference=record.get("request_number") or f"STK-{record['id']}",
            type="stock_adjustment",
            subject=record.get("product_name") or "",
            requester=record.get("username"),
            requester_id=record.get("user_id"),
            submitted_at=record.get("created_at"),
            amount=None,
            impact="" if qty is None else f"Qty {qty}",
            reason=record.get("reason"),
            status=record.get("status"),
            updated_at=record.get("reviewed_at") or record.get("created_at"),
        ))
    return items


def _deliveries(db, actor) -> list[dict]:
    if "supplier_delivery_requests" not in _tables(db):
        return []
    own = "" if _role(actor) in _REVIEW_ROLES else "WHERE q.user_id=?"
    params = () if not own else (actor.get("id"),)
    rows = db.execute(
        "SELECT q.*, r.receipt_number, r.grand_total, s.name AS supplier_name "
        "FROM supplier_delivery_requests q "
        "JOIN stock_receipts r ON r.id=q.receipt_id "
        "LEFT JOIN suppliers s ON s.id=r.supplier_id "
        f"{own} ORDER BY q.id DESC",
        params,
    ).fetchall()
    items = []
    for row in rows:
        record = dict(row)
        kind = "supplier_void" if record.get("kind") == "void" else "supplier_backdate"
        total = record.get("grand_total")
        items.append(_row(
            actor=actor,
            source="delivery",
            source_id=record["id"],
            reference=record.get("request_number") or f"SDR-{record['id']}",
            type=kind,
            subject=f"{record.get('receipt_number') or ''} · {record.get('supplier_name') or ''}".strip(" ·"),
            requester=record.get("username"),
            requester_id=record.get("user_id"),
            submitted_at=record.get("created_at"),
            business_date=record.get("requested_date") or "",
            amount=total,
            impact="" if total in (None, "") else f"KES {float(total):,.2f}",
            reason=record.get("reason"),
            status=record.get("status"),
            updated_at=record.get("reviewed_at") or record.get("created_at"),
        ))
    return items


def list_centre(db, actor: dict, filters: dict | None = None) -> dict:
    filters = filters or {}
    if _role(actor) not in _STAFF_ROLES:
        return {"error": "You cannot view requests.", "requests": [], "counts": {}, "total": 0}
    tables = _tables(db)
    items: list[dict] = []
    if "backdate_requests" in tables:
        items.extend(_backdates(db, actor))
    if "cc_approvals" in tables:
        items.extend(_approvals(db, actor))
    if "stock_adjustment_requests" in tables:
        items.extend(_stock(db, actor))
    if "supplier_delivery_requests" in tables:
        items.extend(_deliveries(db, actor))
    visible = [item for item in items if _matches(item, {**filters, "queue": "all", "status": ""}, actor)]
    queued = [item for item in visible if _matches(item, filters, actor)]
    queued.sort(key=lambda item: str(item.get("updated_at") or item.get("submitted_at") or ""), reverse=True)
    counts = {
        "all": len(visible),
        "action": sum(1 for item in visible if _matches(item, {**filters, "queue": "action", "status": ""}, actor)),
        "pending": sum(1 for item in visible if item["status"] in _AWAITING),
        "approved": sum(1 for item in visible if item["status"] == "approved"),
        "rejected": sum(1 for item in visible if item["status"] == "rejected"),
        "returned": sum(1 for item in visible if item["status"] == "returned"),
    }
    try:
        limit = min(100, max(1, int(filters.get("limit") or 80)))
    except (TypeError, ValueError):
        limit = 80
    return {"requests": queued[:limit], "counts": counts, "total": len(queued)}


def get_centre_item(db, actor: dict, source: str, source_id: int) -> dict:
    if _role(actor) not in _STAFF_ROLES:
        return {"error": "You cannot view requests."}
    source = (source or "").strip().lower()
    if source == "backdate":
        from backend.backdate_requests import get_request
        detail = get_request(db, actor, int(source_id))
        detail["source"] = "backdate"
        detail["type_label"] = "Backdated sale"
        return detail
    if source == "approval":
        row = db.execute("SELECT * FROM cc_approvals WHERE id=?", (int(source_id),)).fetchone()
        if not row:
            return {"error": "That request is not in this shop."}
        record = dict(row)
        if _role(actor) not in _REVIEW_ROLES and int(record.get("requested_by_id") or 0) != int(actor.get("id") or 0):
            return {"error": "You cannot view this request."}
        if record.get("type") == "void":
            from backend.void_requests import get_void_request
            detail = get_void_request(db, actor, int(source_id))
            detail["source"] = "approval"
            detail["type_label"] = "Sale void"
            return detail
        if record.get("type") == "consumption_void":
            import json
            try:
                meta = json.loads(record.get("meta_json") or "{}")
            except json.JSONDecodeError:
                meta = {}
            try:
                consumption_id = int((meta or {}).get("consumption_id") or 0)
            except (TypeError, ValueError):
                consumption_id = 0
            record["consumption_id"] = consumption_id
            record["kind"] = "consumption"
            if consumption_id:
                header = db.execute(
                    "SELECT c.*, d.name AS department_name FROM stock_consumptions c "
                    "LEFT JOIN departments d ON d.id=c.department_id WHERE c.id=?",
                    (consumption_id,),
                ).fetchone()
                lines = db.execute(
                    "SELECT sci.product_name, sci.quantity, sci.unit_cost, sci.total_cost, "
                    "p.sku, p.unit FROM stock_consumption_items sci "
                    "LEFT JOIN products p ON p.id=sci.product_id "
                    "WHERE sci.consumption_id=? ORDER BY sci.id",
                    (consumption_id,),
                ).fetchall()
                if header:
                    record["consumption"] = dict(header)
                    record["lines"] = [dict(line) for line in lines]
                    record["receipt_note"] = "INTERNAL CONSUMPTION. This is not a customer sale."
        record["source"] = "approval"
        record["type_label"] = _TYPE_LABELS.get(record.get("type"), "Request")
        record["status_label"] = _label(record.get("status"))
        return record
    if source == "stock":
        row = db.execute("SELECT * FROM stock_adjustment_requests WHERE id=?", (int(source_id),)).fetchone()
        if not row:
            return {"error": "That request is not in this shop."}
        record = dict(row)
        if _role(actor) not in _REVIEW_ROLES and int(record.get("user_id") or 0) != int(actor.get("id") or 0):
            return {"error": "You cannot view this request."}
        record["source"] = "stock"
        record["type_label"] = "Stock adjustment"
        record["status_label"] = _label(record.get("status"))
        return record
    if source == "delivery":
        row = db.execute(
            "SELECT q.*, r.receipt_number, r.grand_total, r.status AS receipt_status, "
            "s.name AS supplier_name FROM supplier_delivery_requests q "
            "JOIN stock_receipts r ON r.id=q.receipt_id "
            "LEFT JOIN suppliers s ON s.id=r.supplier_id WHERE q.id=?",
            (int(source_id),),
        ).fetchone()
        if not row:
            return {"error": "That request is not in this shop."}
        record = dict(row)
        if _role(actor) not in _REVIEW_ROLES and int(record.get("user_id") or 0) != int(actor.get("id") or 0):
            return {"error": "You cannot view this request."}
        kind = "supplier_void" if record.get("kind") == "void" else "supplier_backdate"
        record["source"] = "delivery"
        record["type"] = kind
        record["type_label"] = _TYPE_LABELS.get(kind, "Supplier delivery")
        record["status_label"] = _label(record.get("status"))
        record["reference"] = record.get("request_number") or ""
        record["requester"] = record.get("username") or ""
        record["requester_id"] = record.get("user_id")
        return record
    return {"error": "That request type is not supported."}
