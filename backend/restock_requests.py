"""Restocking requests.

A list says what the shop wants someone to buy. Recording a purchase does not
change stock. Stock changes only when the existing supplier delivery is posted.
"""
from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime

from desktop.utils.quantities import QuantityError, format_quantity, parse_quantity
from desktop.utils.security import has_permission

PRIORITIES = ("normal", "urgent")
STATUSES = (
    "draft", "ready", "assigned", "partial_purchased", "purchased",
    "partial_received", "received", "cancelled", "archived",
)
PURCHASE_STATUSES = {"partial_purchased", "purchased", "partial_received", "received"}
RECEIPT_STATUSES = {"partial_received", "received"}


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS restock_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id TEXT NOT NULL DEFAULT 'local',
            reference TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            priority TEXT NOT NULL DEFAULT 'normal',
            created_by INTEGER,
            created_name TEXT DEFAULT '',
            updated_by INTEGER,
            updated_name TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            buyer_user_id INTEGER,
            buyer_name TEXT DEFAULT '',
            external_buyer TEXT DEFAULT '',
            desired_date TEXT DEFAULT '',
            supplier_id INTEGER,
            instructions TEXT DEFAULT '',
            submitted_at TEXT,
            submitted_by INTEGER,
            submitted_name TEXT DEFAULT '',
            current_revision INTEGER NOT NULL DEFAULT 0,
            archived_at TEXT,
            archived_by INTEGER,
            previous_status TEXT DEFAULT '',
            cancel_reason TEXT DEFAULT '',
            complete_reason TEXT DEFAULT '',
            explicit_complete INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            client_token TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS restock_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            sku TEXT DEFAULT '',
            barcode TEXT DEFAULT '',
            quantity REAL NOT NULL,
            unit TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            position INTEGER NOT NULL DEFAULT 0,
            added_by INTEGER,
            added_at TEXT NOT NULL,
            updated_by INTEGER,
            updated_at TEXT NOT NULL,
            removed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS restock_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            revision_no INTEGER NOT NULL,
            name TEXT NOT NULL,
            instructions TEXT DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'normal',
            desired_date TEXT DEFAULT '',
            buyer_user_id INTEGER,
            buyer_name TEXT DEFAULT '',
            external_buyer TEXT DEFAULT '',
            supplier_id INTEGER,
            submitted_by INTEGER,
            submitted_name TEXT DEFAULT '',
            submitted_at TEXT NOT NULL,
            change_summary TEXT DEFAULT '',
            UNIQUE(request_id, revision_no)
        );
        CREATE TABLE IF NOT EXISTS restock_revision_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision_id INTEGER NOT NULL,
            line_id INTEGER,
            product_id INTEGER,
            product_name TEXT NOT NULL,
            sku TEXT DEFAULT '',
            barcode TEXT DEFAULT '',
            quantity REAL NOT NULL,
            unit TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            position INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS restock_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            revision_id INTEGER NOT NULL,
            revision_line_id INTEGER NOT NULL,
            purchased_qty REAL NOT NULL DEFAULT 0,
            unavailable_qty REAL NOT NULL DEFAULT 0,
            purchase_date TEXT DEFAULT '',
            unit_price REAL,
            supplier_id INTEGER,
            invoice_ref TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            override INTEGER NOT NULL DEFAULT 0,
            updated_by INTEGER,
            updated_name TEXT DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(revision_line_id)
        );
        CREATE TABLE IF NOT EXISTS restock_purchase_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            revision_line_id INTEGER NOT NULL,
            purchased_qty REAL,
            unavailable_qty REAL,
            unit_price REAL,
            notes TEXT DEFAULT '',
            actor_id INTEGER,
            actor_name TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS restock_receipt_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            revision_id INTEGER,
            line_id INTEGER,
            receipt_id INTEGER NOT NULL,
            receipt_number TEXT DEFAULT '',
            supplier_id INTEGER,
            product_id INTEGER,
            qty_received REAL NOT NULL,
            qty_accepted REAL NOT NULL,
            qty_rejected REAL NOT NULL DEFAULT 0,
            linked_by INTEGER,
            linked_name TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS restock_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            detail TEXT DEFAULT '',
            before_value TEXT DEFAULT '',
            after_value TEXT DEFAULT '',
            user_id INTEGER,
            username TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_restock_shop_ref
            ON restock_requests(shop_id, reference);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_restock_token
            ON restock_requests(shop_id, client_token)
            WHERE client_token IS NOT NULL AND client_token != '';
        CREATE UNIQUE INDEX IF NOT EXISTS ux_restock_active_product
            ON restock_lines(request_id, product_id) WHERE removed = 0;
        CREATE INDEX IF NOT EXISTS ix_restock_status ON restock_requests(shop_id, status);
        CREATE INDEX IF NOT EXISTS ix_restock_lines_req ON restock_lines(request_id);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_restock_link_receipt
            ON restock_receipt_links(line_id, receipt_id);
        """
    )
    _protect_revisions(conn)


def _protect_revisions(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS restock_revisions_no_update
        BEFORE UPDATE ON restock_revisions
        BEGIN
            SELECT RAISE(ABORT, 'A submitted restock revision cannot be changed.');
        END;
        CREATE TRIGGER IF NOT EXISTS restock_revisions_no_delete
        BEFORE DELETE ON restock_revisions
        BEGIN
            SELECT RAISE(ABORT, 'A submitted restock revision cannot be removed.');
        END;
        CREATE TRIGGER IF NOT EXISTS restock_revision_lines_no_update
        BEFORE UPDATE ON restock_revision_lines
        BEGIN
            SELECT RAISE(ABORT, 'A submitted restock line cannot be changed.');
        END;
        CREATE TRIGGER IF NOT EXISTS restock_revision_lines_no_delete
        BEFORE DELETE ON restock_revision_lines
        BEGIN
            SELECT RAISE(ABORT, 'A submitted restock line cannot be removed.');
        END;
        """
    )


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _shop(actor: dict) -> str:
    return str((actor or {}).get("shop_id") or "local")


def _name(actor: dict) -> str:
    return str((actor or {}).get("username") or (actor or {}).get("full_name") or "")


def _uid(actor: dict):
    try:
        return int(actor.get("id")) if actor and actor.get("id") not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _fail(message: str, status: int = 400, **extra) -> dict:
    body = {"error": message, "status": status}
    body.update(extra)
    return body


def _can(actor, action: str) -> bool:
    return has_permission(actor or {}, action)


def _sees_shop(actor) -> bool:
    return _can(actor, "restock.view") or _can(actor, "restock.manage") or _can(actor, "restock.purchase")


def _owns(row, actor) -> bool:
    return _uid(actor) is not None and int(row["created_by"] or 0) == _uid(actor)


def _visible(row, actor) -> bool:
    if row["shop_id"] != _shop(actor):
        return False
    if _sees_shop(actor):
        return True
    return _can(actor, "restock.create") and _owns(row, actor)


def _editable(row) -> bool:
    return row["status"] == "draft"


def _check_version(row, expected) -> dict | None:
    if expected in (None, ""):
        return _fail("Reload this list before saving it.", 409, conflict=True, version=int(row["version"]))
    try:
        got = int(expected)
    except (TypeError, ValueError):
        return _fail("Reload this list before saving it.", 409, conflict=True, version=int(row["version"]))
    if got != int(row["version"]):
        return _fail(
            "Someone else saved this list. Reload it and try again.",
            409, conflict=True, version=int(row["version"]),
        )
    return None


def _event(conn, request_id, kind, actor, detail="", before="", after="") -> None:
    conn.execute(
        "INSERT INTO restock_events (request_id,kind,detail,before_value,after_value,user_id,username,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (request_id, kind, str(detail or "")[:1000], str(before or "")[:500], str(after or "")[:500],
         _uid(actor), _name(actor), _now()),
    )
    try:
        from desktop.utils.api_client import _audit
        _audit(_uid(actor), _name(actor), kind, "restock", str(detail or "")[:500], conn=conn)
    except Exception:
        pass


def _notify_assignment(conn, row, actor, revision_no: int) -> None:
    """One notification per buyer and revision. Refreshing the page does not add another."""
    buyer = int(row["buyer_user_id"] or 0)
    if not buyer:
        return
    marker = f"buyer:{buyer}:rev:{revision_no}"
    existing = conn.execute(
        "SELECT id FROM restock_events WHERE request_id=? AND kind='notified' AND detail=?",
        (row["id"], marker),
    ).fetchone()
    if existing:
        return
    _event(conn, row["id"], "notified", actor, marker)
    tables = {item[0] for item in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "cc_notifications" not in tables:
        return
    conn.execute(
        "INSERT INTO cc_notifications (type, title, body, severity, link) VALUES (?,?,?,?,?)",
        (
            "restock",
            f"Restock list assigned: {row['name']}",
            f"{row['reference']} is ready for purchasing.",
            "info",
            "/restock",
        ),
    )


def _next_reference(conn, shop_id: str) -> str:
    year = datetime.now().year
    prefix = f"RST-{year}-"
    row = conn.execute(
        "SELECT reference FROM restock_requests WHERE shop_id=? AND reference LIKE ? "
        "ORDER BY reference DESC LIMIT 1",
        (shop_id, prefix + "%"),
    ).fetchone()
    seq = 1
    if row and row[0]:
        tail = str(row[0]).rsplit("-", 1)[-1]
        try:
            seq = int(tail) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:06d}"


def _product(conn, product_id: int):
    return conn.execute(
        "SELECT id, name, sku, barcode, unit, is_active FROM products WHERE id=?",
        (int(product_id),),
    ).fetchone()


def _load(conn, request_id: int, actor):
    row = conn.execute("SELECT * FROM restock_requests WHERE id=?", (int(request_id),)).fetchone()
    if not row or not _visible(row, actor):
        return None
    return row


def _lines(conn, request_id: int, include_removed=False):
    sql = "SELECT * FROM restock_lines WHERE request_id=?"
    if not include_removed:
        sql += " AND removed=0"
    sql += " ORDER BY position, id"
    return conn.execute(sql, (int(request_id),)).fetchall()


def _current_revision(conn, row):
    if not row or int(row["current_revision"] or 0) <= 0:
        return None
    return conn.execute(
        "SELECT * FROM restock_revisions WHERE request_id=? AND revision_no=?",
        (row["id"], int(row["current_revision"])),
    ).fetchone()


def _revision_lines(conn, revision_id: int):
    return conn.execute(
        "SELECT * FROM restock_revision_lines WHERE revision_id=? ORDER BY position, id",
        (int(revision_id),),
    ).fetchall()


def _purchase_map(conn, revision_id: int) -> dict:
    rows = conn.execute(
        "SELECT * FROM restock_purchases WHERE revision_id=?",
        (int(revision_id),),
    ).fetchall()
    return {int(row["revision_line_id"]): row for row in rows}


def _received_map(conn, request_id: int) -> dict:
    rows = conn.execute(
        "SELECT line_id, COALESCE(SUM(qty_accepted),0) AS accepted, "
        "COALESCE(SUM(qty_rejected),0) AS rejected, COALESCE(SUM(qty_received),0) AS received "
        "FROM restock_receipt_links WHERE request_id=? GROUP BY line_id",
        (int(request_id),),
    ).fetchall()
    return {int(row["line_id"]): row for row in rows if row["line_id"] is not None}


def _qty_summary(lines) -> dict:
    units = {}
    for line in lines:
        unit = str(line["unit"] or "units")
        units[unit] = units.get(unit, 0) + float(line["quantity"] or 0)
    return {
        "product_count": len(lines),
        "quantity_by_unit": {key: float(value) for key, value in units.items()},
        "single_unit_total": float(next(iter(units.values()))) if len(units) == 1 else None,
        "unit": next(iter(units)) if len(units) == 1 else "",
    }


def _progress(conn, row) -> dict:
    revision = _current_revision(conn, row)
    received = _received_map(conn, row["id"])
    awaiting = partial = complete = 0
    purchased_waiting = 0.0
    if revision:
        purchases = _purchase_map(conn, revision["id"])
        source = _revision_lines(conn, revision["id"])
        for line in source:
            requested = float(line["quantity"] or 0)
            purchase = purchases.get(int(line["id"]))
            bought = float(purchase["purchased_qty"] or 0) if purchase else 0.0
            accepted = float((received.get(int(line["line_id"] or 0)) or {"accepted": 0})["accepted"] or 0)
            if bought <= 0 and accepted <= 0:
                awaiting += 1
            elif bought + 0.00001 < requested or accepted + 0.00001 < requested:
                partial += 1
            else:
                complete += 1
            if bought > accepted:
                purchased_waiting += bought - accepted
    else:
        source = [line for line in _lines(conn, row["id"])]
        awaiting = len(source)
    return {
        "awaiting_purchase": awaiting,
        "partial_lines": partial,
        "complete_lines": complete,
        "purchased_not_received": purchased_waiting,
    }


def _public_line(line, purchase=None, received=None, see_cost=False) -> dict:
    requested = float(line["quantity"] or 0)
    bought = float(purchase["purchased_qty"] or 0) if purchase else 0.0
    unavailable = float(purchase["unavailable_qty"] or 0) if purchase else 0.0
    accepted = float(received["accepted"] or 0) if received else 0.0
    rejected = float(received["rejected"] or 0) if received else 0.0
    outstanding = max(0.0, requested - bought)
    body = {
        "id": int(line["id"]),
        "line_id": int(line["line_id"]) if "line_id" in line.keys() and line["line_id"] else int(line["id"]),
        "product_id": line["product_id"],
        "product_name": line["product_name"],
        "sku": line["sku"] or "",
        "barcode": line["barcode"] or "",
        "quantity": requested,
        "quantity_text": format_quantity(requested),
        "unit": line["unit"] or "",
        "notes": line["notes"] or "",
        "purchased_qty": bought,
        "unavailable_qty": unavailable,
        "outstanding_qty": outstanding,
        "received_qty": accepted,
        "rejected_qty": rejected,
        "purchased_not_received": max(0.0, bought - accepted),
        "purchase_notes": (purchase["notes"] if purchase else "") or "",
        "purchase_date": (purchase["purchase_date"] if purchase else "") or "",
        "invoice_ref": (purchase["invoice_ref"] if purchase else "") or "",
        "supplier_id": purchase["supplier_id"] if purchase else None,
    }
    if see_cost and purchase is not None and purchase["unit_price"] is not None:
        body["unit_price"] = float(purchase["unit_price"])
    return body


def _header(conn, row, actor) -> dict:
    lines = _lines(conn, row["id"])
    summary = _qty_summary(lines)
    progress = _progress(conn, row)
    return {
        "id": int(row["id"]),
        "reference": row["reference"],
        "name": row["name"],
        "description": row["description"] or "",
        "status": row["status"],
        "status_label": _status_label(row["status"]),
        "priority": row["priority"],
        "created_by": row["created_by"],
        "created_name": row["created_name"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "updated_name": row["updated_name"] or "",
        "buyer_user_id": row["buyer_user_id"],
        "buyer_name": row["buyer_name"] or "",
        "external_buyer": row["external_buyer"] or "",
        "desired_date": row["desired_date"] or "",
        "supplier_id": row["supplier_id"],
        "instructions": row["instructions"] or "",
        "submitted_at": row["submitted_at"] or "",
        "submitted_name": row["submitted_name"] or "",
        "current_revision": int(row["current_revision"] or 0),
        "version": int(row["version"] or 1),
        "cancel_reason": row["cancel_reason"] or "",
        "complete_reason": row["complete_reason"] or "",
        "explicit_complete": int(row["explicit_complete"] or 0),
        "product_count": summary["product_count"],
        "quantity_by_unit": summary["quantity_by_unit"],
        "single_unit_total": summary["single_unit_total"],
        "unit": summary["unit"],
        **progress,
    }


def _status_label(status: str) -> str:
    return {
        "draft": "Draft",
        "ready": "Ready for Purchase",
        "assigned": "Assigned",
        "partial_purchased": "Partially Purchased",
        "purchased": "Purchased",
        "partial_received": "Partially Received",
        "received": "Received",
        "cancelled": "Cancelled",
        "archived": "Archived",
    }.get(status or "", status or "")


def _detail(conn, row, actor) -> dict:
    body = _header(conn, row, actor)
    see_cost = _can(actor, "inventory.view_cost")
    revision = _current_revision(conn, row)
    received = _received_map(conn, row["id"])
    if row["status"] == "draft" or not revision:
        body["lines"] = [_public_line(line, received=received.get(int(line["id"]))) for line in _lines(conn, row["id"])]
        body["snapshot"] = None
    else:
        purchases = _purchase_map(conn, revision["id"])
        snap_lines = []
        for line in _revision_lines(conn, revision["id"]):
            snap_lines.append(_public_line(
                line,
                purchases.get(int(line["id"])),
                received.get(int(line["line_id"] or 0)),
                see_cost,
            ))
        body["lines"] = snap_lines
        body["working_lines"] = [
            _public_line(line, received=received.get(int(line["id"]))) for line in _lines(conn, row["id"])
        ]
        body["snapshot"] = {
            "revision_no": int(revision["revision_no"]),
            "name": revision["name"],
            "submitted_at": revision["submitted_at"],
            "submitted_name": revision["submitted_name"] or "",
            "buyer_name": revision["buyer_name"] or "",
            "external_buyer": revision["external_buyer"] or "",
            "instructions": revision["instructions"] or "",
            "priority": revision["priority"],
            "desired_date": revision["desired_date"] or "",
            "lines": snap_lines,
        }
    events = conn.execute(
        "SELECT kind, detail, before_value, after_value, username, created_at "
        "FROM restock_events WHERE request_id=? ORDER BY id",
        (row["id"],),
    ).fetchall()
    body["history"] = [dict(item) for item in events]
    links = conn.execute(
        "SELECT receipt_id, receipt_number, product_id, qty_accepted, qty_rejected, created_at "
        "FROM restock_receipt_links WHERE request_id=? ORDER BY id",
        (row["id"],),
    ).fetchall()
    body["receipts"] = [dict(item) for item in links]
    return body


def _touch(conn, row, actor) -> None:
    conn.execute(
        "UPDATE restock_requests SET updated_at=?, updated_by=?, updated_name=?, version=version+1 WHERE id=?",
        (_now(), _uid(actor), _name(actor), row["id"]),
    )


def _recompute(conn, row) -> str:
    if row["status"] in ("draft", "cancelled", "archived"):
        return row["status"]
    if int(row["explicit_complete"] or 0) == 1:
        return "received"
    revision = _current_revision(conn, row)
    if not revision:
        return row["status"]
    lines = _revision_lines(conn, revision["id"])
    if not lines:
        return row["status"]
    purchases = _purchase_map(conn, revision["id"])
    received = _received_map(conn, row["id"])
    any_bought = False
    all_bought = True
    any_received = False
    all_received = True
    for line in lines:
        requested = float(line["quantity"] or 0)
        purchase = purchases.get(int(line["id"]))
        bought = float(purchase["purchased_qty"] or 0) if purchase else 0.0
        accepted = float((received.get(int(line["line_id"] or 0)) or {"accepted": 0})["accepted"] or 0)
        if bought > 0:
            any_bought = True
        if bought + 0.00001 < requested:
            all_bought = False
        if accepted > 0:
            any_received = True
        if accepted + 0.00001 < requested:
            all_received = False
    if all_received and any_received:
        status = "received"
    elif any_received:
        status = "partial_received"
    elif all_bought and any_bought:
        status = "purchased"
    elif any_bought:
        status = "partial_purchased"
    elif row["buyer_user_id"] or (row["external_buyer"] or "").strip():
        status = "assigned"
    else:
        status = "ready"
    if status != row["status"]:
        conn.execute("UPDATE restock_requests SET status=? WHERE id=?", (status, row["id"]))
    return status


def create_request(conn, actor, payload: dict) -> dict:
    if not (_can(actor, "restock.create") or _can(actor, "restock.manage")):
        return _fail("You cannot create a restock list.", 403)
    ensure_schema(conn)
    name = str((payload or {}).get("name") or "").strip()
    if not name:
        return _fail("Give the list a name.")
    if len(name) > 120:
        return _fail("The list name is too long.")
    priority = str((payload or {}).get("priority") or "normal").strip().lower()
    if priority not in PRIORITIES:
        return _fail("Priority must be Normal or Urgent.")
    token = str((payload or {}).get("client_token") or "").strip()
    shop = _shop(actor)
    if token:
        found = conn.execute(
            "SELECT id FROM restock_requests WHERE shop_id=? AND client_token=?",
            (shop, token),
        ).fetchone()
        if found:
            row = _load(conn, found["id"], actor)
            return {"success": True, "duplicate": True, "request": _detail(conn, row, actor)}
    description = str((payload or {}).get("description") or "").strip()[:1000]
    instructions = str((payload or {}).get("instructions") or "").strip()[:2000]
    desired = str((payload or {}).get("desired_date") or "").strip()[:10]
    now = _now()
    reference = _next_reference(conn, shop)
    conn.execute(
        "INSERT INTO restock_requests (shop_id,reference,name,description,status,priority,"
        "created_by,created_name,updated_by,updated_name,created_at,updated_at,desired_date,"
        "instructions,version,client_token) VALUES (?,?,?,?, 'draft', ?,?,?,?,?,?,?,?,?,1,?)",
        (shop, reference, name, description, priority, _uid(actor), _name(actor), _uid(actor),
         _name(actor), now, now, desired, instructions, token),
    )
    request_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    _event(conn, request_id, "created", actor, reference, "", name)
    row = _load(conn, request_id, actor)
    return {"success": True, "request": _detail(conn, row, actor)}


def list_requests(conn, actor, filters: dict | None = None) -> dict:
    if not (_sees_shop(actor) or _can(actor, "restock.create")):
        return _fail("You cannot view restock lists.", 403)
    ensure_schema(conn)
    filters = filters or {}
    sql = "SELECT * FROM restock_requests WHERE shop_id=?"
    args: list = [_shop(actor)]
    if not _sees_shop(actor):
        sql += " AND created_by=?"
        args.append(_uid(actor))
    include_archived = str(filters.get("archived") or "") in ("1", "true", "yes")
    status = str(filters.get("status") or "").strip().lower()
    if status:
        sql += " AND status=?"
        args.append(status)
    elif not include_archived:
        sql += " AND status!='archived'"
    creator = filters.get("creator")
    if creator not in (None, ""):
        sql += " AND created_by=?"
        args.append(int(creator))
    buyer = filters.get("buyer")
    if buyer not in (None, ""):
        sql += " AND buyer_user_id=?"
        args.append(int(buyer))
    date_from = str(filters.get("date_from") or "").strip()[:10]
    date_to = str(filters.get("date_to") or "").strip()[:10]
    if date_from:
        sql += " AND substr(created_at,1,10)>=?"
        args.append(date_from)
    if date_to:
        sql += " AND substr(created_at,1,10)<=?"
        args.append(date_to)
    query = str(filters.get("q") or "").strip().lower()
    sql += " ORDER BY updated_at DESC, id DESC"
    rows = []
    for row in conn.execute(sql, args).fetchall():
        if query and query not in (row["name"] or "").lower() and query not in (row["reference"] or "").lower():
            continue
        rows.append(_header(conn, row, actor))
    return {"success": True, "requests": rows}


def get_request(conn, actor, request_id: int) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    return {"success": True, "request": _detail(conn, row, actor)}


def update_request(conn, actor, request_id: int, payload: dict) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if not _editable(row):
        return _fail("This list has already been sent. Return it to a draft before changing it.")
    if not (_can(actor, "restock.manage") or (_can(actor, "restock.create") and _owns(row, actor))):
        return _fail("You cannot edit this restock list.", 403)
    conflict = _check_version(row, (payload or {}).get("version"))
    if conflict:
        return conflict
    fields = []
    values = []
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            return _fail("Give the list a name.")
        if len(name) > 120:
            return _fail("The list name is too long.")
        if name != row["name"]:
            _event(conn, row["id"], "renamed", actor, "", row["name"], name)
        fields.append("name=?")
        values.append(name)
    if "description" in payload:
        fields.append("description=?")
        values.append(str(payload.get("description") or "").strip()[:1000])
    if "instructions" in payload:
        before = row["instructions"] or ""
        after = str(payload.get("instructions") or "").strip()[:2000]
        if before != after:
            _event(conn, row["id"], "notes_changed", actor, "instructions", before, after)
        fields.append("instructions=?")
        values.append(after)
    if "priority" in payload:
        priority = str(payload.get("priority") or "").strip().lower()
        if priority not in PRIORITIES:
            return _fail("Priority must be Normal or Urgent.")
        if priority != row["priority"]:
            _event(conn, row["id"], "priority_changed", actor, "", row["priority"], priority)
        fields.append("priority=?")
        values.append(priority)
    if "desired_date" in payload:
        desired = str(payload.get("desired_date") or "").strip()[:10]
        if desired != (row["desired_date"] or ""):
            _event(conn, row["id"], "date_changed", actor, "", row["desired_date"] or "", desired)
        fields.append("desired_date=?")
        values.append(desired)
    if "supplier_id" in payload and _can(actor, "restock.manage"):
        raw = payload.get("supplier_id")
        supplier_id = None if raw in (None, "", 0, "0") else int(raw)
        if supplier_id:
            found = conn.execute("SELECT id FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
            if not found:
                return _fail("That supplier was not found.")
        fields.append("supplier_id=?")
        values.append(supplier_id)
    if not fields:
        return {"success": True, "request": _detail(conn, row, actor)}
    fields.extend(["updated_at=?", "updated_by=?", "updated_name=?", "version=version+1"])
    values.extend([_now(), _uid(actor), _name(actor), row["id"]])
    conn.execute(f"UPDATE restock_requests SET {', '.join(fields)} WHERE id=?", values)
    fresh = _load(conn, request_id, actor)
    return {"success": True, "request": _detail(conn, fresh, actor)}


def add_line(conn, actor, request_id: int, payload: dict) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if not _editable(row):
        return _fail("This list has already been sent. Return it to a draft before adding products.")
    if not (_can(actor, "restock.manage") or (_can(actor, "restock.create") and _owns(row, actor))):
        return _fail("You cannot edit this restock list.", 403)
    conflict = _check_version(row, (payload or {}).get("version"))
    if conflict:
        return conflict
    try:
        product_id = int(payload.get("product_id"))
    except (TypeError, ValueError):
        return _fail("Choose a product from the catalogue.")
    product = _product(conn, product_id)
    if not product:
        return _fail("That product is not in the catalogue.")
    if int(product["is_active"] or 0) != 1:
        return _fail(f"{product['name']} is no longer sold. It was not added.")
    try:
        quantity = parse_quantity(payload.get("quantity"), product["unit"])
    except QuantityError as exc:
        message = str(exc)
        if "whole units" in message:
            message = f"{product['name']} is counted in whole {product['unit'] or 'units'}."
        return _fail(message)
    notes = str(payload.get("notes") or "").strip()[:500]
    existing = conn.execute(
        "SELECT * FROM restock_lines WHERE request_id=? AND product_id=? AND removed=0",
        (row["id"], product_id),
    ).fetchone()
    merge = bool(payload.get("merge"))
    now = _now()
    if existing:
        if not merge:
            return _fail(
                f"{product['name']} is already on this list. Increase that line instead of adding it twice.",
                409, existing_line_id=int(existing["id"]),
            )
        new_qty = float(existing["quantity"] or 0) + quantity
        try:
            new_qty = parse_quantity(new_qty, product["unit"])
        except QuantityError as exc:
            return _fail(str(exc))
        conn.execute(
            "UPDATE restock_lines SET quantity=?, notes=CASE WHEN ?!='' THEN ? ELSE notes END, "
            "updated_by=?, updated_at=? WHERE id=?",
            (new_qty, notes, notes, _uid(actor), now, existing["id"]),
        )
        _event(conn, row["id"], "quantity_changed", actor, product["name"],
               format_quantity(existing["quantity"]), format_quantity(new_qty))
    else:
        position = conn.execute(
            "SELECT COALESCE(MAX(position),0)+1 FROM restock_lines WHERE request_id=?",
            (row["id"],),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO restock_lines (request_id,product_id,product_name,sku,barcode,quantity,unit,"
            "notes,position,added_by,added_at,updated_by,updated_at,removed) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (row["id"], product["id"], product["name"], product["sku"] or "", product["barcode"] or "",
             quantity, product["unit"] or "", notes, position, _uid(actor), now, _uid(actor), now),
        )
        _event(conn, row["id"], "product_added", actor,
               f"{product['name']} {format_quantity(quantity)} {product['unit'] or ''}".strip())
    _touch(conn, row, actor)
    fresh = _load(conn, request_id, actor)
    return {"success": True, "request": _detail(conn, fresh, actor)}


def update_line(conn, actor, request_id: int, line_id: int, payload: dict) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if not _editable(row):
        return _fail("This list has already been sent. Return it to a draft before changing quantities.")
    if not (_can(actor, "restock.manage") or (_can(actor, "restock.create") and _owns(row, actor))):
        return _fail("You cannot edit this restock list.", 403)
    conflict = _check_version(row, (payload or {}).get("version"))
    if conflict:
        return conflict
    line = conn.execute(
        "SELECT * FROM restock_lines WHERE id=? AND request_id=? AND removed=0",
        (int(line_id), row["id"]),
    ).fetchone()
    if not line:
        return _fail("That product is not on this list.")
    product = _product(conn, line["product_id"])
    unit = (product["unit"] if product else line["unit"]) or ""
    try:
        quantity = parse_quantity(payload.get("quantity", line["quantity"]), unit)
    except QuantityError as exc:
        return _fail(str(exc))
    notes = line["notes"] or ""
    if "notes" in (payload or {}):
        notes = str(payload.get("notes") or "").strip()[:500]
        if notes != (line["notes"] or ""):
            _event(conn, row["id"], "line_notes_changed", actor, line["product_name"], line["notes"] or "", notes)
    if abs(quantity - float(line["quantity"] or 0)) > 0.00001:
        _event(conn, row["id"], "quantity_changed", actor, line["product_name"],
               format_quantity(line["quantity"]), format_quantity(quantity))
    conn.execute(
        "UPDATE restock_lines SET quantity=?, notes=?, updated_by=?, updated_at=? WHERE id=?",
        (quantity, notes, _uid(actor), _now(), line["id"]),
    )
    _touch(conn, row, actor)
    fresh = _load(conn, request_id, actor)
    return {"success": True, "request": _detail(conn, fresh, actor)}


def remove_line(conn, actor, request_id: int, line_id: int, expected_version) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if not _editable(row):
        return _fail("This list has already been sent. Return it to a draft before removing products.")
    if not (_can(actor, "restock.manage") or (_can(actor, "restock.create") and _owns(row, actor))):
        return _fail("You cannot edit this restock list.", 403)
    conflict = _check_version(row, expected_version)
    if conflict:
        return conflict
    line = conn.execute(
        "SELECT * FROM restock_lines WHERE id=? AND request_id=? AND removed=0",
        (int(line_id), row["id"]),
    ).fetchone()
    if not line:
        return _fail("That product is not on this list.")
    conn.execute(
        "UPDATE restock_lines SET removed=1, updated_by=?, updated_at=? WHERE id=?",
        (_uid(actor), _now(), line["id"]),
    )
    _event(conn, row["id"], "product_removed", actor, line["product_name"])
    _touch(conn, row, actor)
    fresh = _load(conn, request_id, actor)
    return {"success": True, "request": _detail(conn, fresh, actor)}


def _validate_for_submit(conn, row) -> dict | None:
    lines = _lines(conn, row["id"])
    if not lines:
        return _fail("Add at least one product before sending this list.")
    missing = []
    for line in lines:
        product = _product(conn, line["product_id"])
        if not product or int(product["is_active"] or 0) != 1:
            missing.append(line["product_name"])
        else:
            try:
                parse_quantity(line["quantity"], product["unit"])
            except QuantityError as exc:
                return _fail(f"{line['product_name']}: {exc}")
    if missing:
        names = ", ".join(missing)
        return _fail(f"These products are no longer in the catalogue: {names}. Remove them before sending the list.")
    return None


def submit_request(conn, actor, request_id: int, expected_version) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if not _can(actor, "restock.manage"):
        return _fail("You cannot send this restock list.", 403)
    if row["status"] != "draft":
        return _fail("Only a draft can be sent for purchase.")
    conflict = _check_version(row, expected_version)
    if conflict:
        return conflict
    invalid = _validate_for_submit(conn, row)
    if invalid:
        return invalid
    now = _now()
    revision_no = int(row["current_revision"] or 0) + 1
    conn.execute(
        "INSERT INTO restock_revisions (request_id,revision_no,name,instructions,priority,desired_date,"
        "buyer_user_id,buyer_name,external_buyer,supplier_id,submitted_by,submitted_name,submitted_at,change_summary) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (row["id"], revision_no, row["name"], row["instructions"] or "", row["priority"], row["desired_date"] or "",
         row["buyer_user_id"], row["buyer_name"] or "", row["external_buyer"] or "", row["supplier_id"],
         _uid(actor), _name(actor), now, f"Revision {revision_no}"),
    )
    revision_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for line in _lines(conn, row["id"]):
        conn.execute(
            "INSERT INTO restock_revision_lines (revision_id,line_id,product_id,product_name,sku,barcode,"
            "quantity,unit,notes,position) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (revision_id, line["id"], line["product_id"], line["product_name"], line["sku"] or "",
             line["barcode"] or "", line["quantity"], line["unit"] or "", line["notes"] or "", line["position"]),
        )
    status = "assigned" if (row["buyer_user_id"] or (row["external_buyer"] or "").strip()) else "ready"
    conn.execute(
        "UPDATE restock_requests SET status=?, current_revision=?, submitted_at=?, submitted_by=?, "
        "submitted_name=?, updated_at=?, updated_by=?, updated_name=?, version=version+1 WHERE id=?",
        (status, revision_no, now, _uid(actor), _name(actor), now, _uid(actor), _name(actor), row["id"]),
    )
    _event(conn, row["id"], "submitted", actor, f"Revision {revision_no}")
    fresh = _load(conn, request_id, actor)
    if fresh["buyer_user_id"]:
        _notify_assignment(conn, fresh, actor, revision_no)
    return {"success": True, "request": _detail(conn, fresh, actor)}


def return_to_draft(conn, actor, request_id: int, expected_version) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if not _can(actor, "restock.manage"):
        return _fail("You cannot change this restock list.", 403)
    if row["status"] not in ("ready", "assigned"):
        return _fail("Only a list that has not been purchased can return to a draft.")
    conflict = _check_version(row, expected_version)
    if conflict:
        return conflict
    revision = _current_revision(conn, row)
    if revision:
        bought = conn.execute(
            "SELECT COALESCE(SUM(purchased_qty),0) FROM restock_purchases WHERE revision_id=?",
            (revision["id"],),
        ).fetchone()[0]
        if float(bought or 0) > 0:
            return _fail("Purchases are already recorded. The sent list stays as the buyer received it.")
    linked = conn.execute(
        "SELECT COUNT(*) FROM restock_receipt_links WHERE request_id=?", (row["id"],)
    ).fetchone()[0]
    if int(linked or 0) > 0:
        return _fail("Goods have already been linked to this list.")
    conn.execute(
        "UPDATE restock_requests SET status='draft', updated_at=?, updated_by=?, updated_name=?, version=version+1 WHERE id=?",
        (_now(), _uid(actor), _name(actor), row["id"]),
    )
    _event(conn, row["id"], "returned_to_draft", actor, f"Revision {row['current_revision']} kept")
    fresh = _load(conn, request_id, actor)
    return {"success": True, "request": _detail(conn, fresh, actor)}


def assign_request(conn, actor, request_id: int, payload: dict) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if not _can(actor, "restock.manage"):
        return _fail("You cannot assign a restock list.", 403)
    if row["status"] in ("draft", "cancelled", "archived"):
        return _fail("Send the list before assigning a buyer.")
    conflict = _check_version(row, (payload or {}).get("version"))
    if conflict:
        return conflict
    buyer_id = payload.get("buyer_user_id")
    external = str(payload.get("external_buyer") or "").strip()[:120]
    buyer_name = ""
    if buyer_id not in (None, "", 0, "0"):
        try:
            buyer_id = int(buyer_id)
        except (TypeError, ValueError):
            return _fail("Choose a buyer from the staff list.")
        user = conn.execute(
            "SELECT id, full_name, username, is_active FROM users WHERE id=?", (buyer_id,)
        ).fetchone()
        if not user or int(user["is_active"] or 0) != 1:
            return _fail("That buyer account is not active.")
        buyer_name = user["full_name"] or user["username"] or ""
    else:
        buyer_id = None
    if not buyer_id and not external:
        return _fail("Choose a staff buyer or write the external buyer's name.")
    before = row["buyer_name"] or row["external_buyer"] or ""
    after = buyer_name or external
    conn.execute(
        "UPDATE restock_requests SET buyer_user_id=?, buyer_name=?, external_buyer=?, "
        "updated_at=?, updated_by=?, updated_name=?, version=version+1 WHERE id=?",
        (buyer_id, buyer_name, external, _now(), _uid(actor), _name(actor), row["id"]),
    )
    _event(conn, row["id"], "assigned", actor, "", before, after)
    fresh = _load(conn, request_id, actor)
    _recompute(conn, fresh)
    fresh = _load(conn, request_id, actor)
    if buyer_id:
        _notify_assignment(conn, fresh, actor, int(fresh["current_revision"] or 0))
    return {"success": True, "request": _detail(conn, fresh, actor)}


def record_purchase(conn, actor, request_id: int, payload: dict) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if not _can(actor, "restock.purchase"):
        return _fail("You cannot record purchasing progress.", 403)
    if row["status"] in ("draft", "cancelled", "archived"):
        return _fail("Send the list before recording what was purchased.")
    conflict = _check_version(row, (payload or {}).get("version"))
    if conflict:
        return conflict
    revision = _current_revision(conn, row)
    if not revision:
        return _fail("This list has no sent version yet.")
    see_cost = _can(actor, "inventory.view_cost")
    lines = {int(item["id"]): item for item in _revision_lines(conn, revision["id"])}
    updates = payload.get("lines") or []
    if not isinstance(updates, list) or not updates:
        return _fail("Record a quantity for at least one product.")
    now = _now()
    for item in updates:
        try:
            line_id = int(item.get("id") or item.get("revision_line_id"))
        except (TypeError, ValueError):
            return _fail("Choose a product on the sent list.")
        line = lines.get(line_id)
        if not line:
            return _fail("That product is not on the sent list.")
        try:
            purchased = parse_quantity(item.get("purchased_qty", 0), line["unit"], allow_zero=True)
        except QuantityError as exc:
            return _fail(f"{line['product_name']}: {exc}")
        unavailable_raw = item.get("unavailable_qty", 0)
        try:
            unavailable = parse_quantity(unavailable_raw or 0, line["unit"], allow_zero=True)
        except QuantityError as exc:
            return _fail(f"{line['product_name']}: {exc}")
        requested = float(line["quantity"] or 0)
        override = bool(item.get("override"))
        if purchased - requested > 0.00001:
            if not override or not _can(actor, "restock.manage"):
                return _fail(
                    f"{line['product_name']} was requested as {format_quantity(requested)} {line['unit'] or ''}. "
                    "Buying more needs a manager to confirm the extra quantity.".strip()
                )
        outstanding = max(0.0, requested - purchased)
        if unavailable - outstanding > 0.00001 and purchased <= requested:
            return _fail(f"Unavailable quantity for {line['product_name']} cannot exceed what is still outstanding.")
        price = None
        if see_cost and item.get("unit_price") not in (None, ""):
            try:
                price = round(float(item.get("unit_price")), 4)
            except (TypeError, ValueError):
                return _fail(f"Enter a valid purchase price for {line['product_name']}.")
            if price < 0:
                return _fail("Purchase price cannot be negative.")
        elif not see_cost and item.get("unit_price") not in (None, ""):
            return _fail("You cannot record buying prices.", 403)
        supplier_id = item.get("supplier_id")
        supplier_id = None if supplier_id in (None, "", 0, "0") else int(supplier_id)
        notes = str(item.get("notes") or "").strip()[:500]
        purchase_date = str(item.get("purchase_date") or "").strip()[:10]
        invoice_ref = str(item.get("invoice_ref") or "").strip()[:80]
        previous = conn.execute(
            "SELECT * FROM restock_purchases WHERE revision_line_id=?", (line_id,)
        ).fetchone()
        if previous:
            conn.execute(
                "INSERT INTO restock_purchase_history (request_id,revision_line_id,purchased_qty,unavailable_qty,"
                "unit_price,notes,actor_id,actor_name,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (row["id"], line_id, previous["purchased_qty"], previous["unavailable_qty"], previous["unit_price"],
                 previous["notes"] or "", _uid(actor), _name(actor), now),
            )
            conn.execute(
                "UPDATE restock_purchases SET purchased_qty=?, unavailable_qty=?, purchase_date=?, unit_price=?, "
                "supplier_id=?, invoice_ref=?, notes=?, override=?, updated_by=?, updated_name=?, updated_at=? "
                "WHERE id=?",
                (purchased, unavailable, purchase_date, price, supplier_id, invoice_ref, notes,
                 1 if override else 0, _uid(actor), _name(actor), now, previous["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO restock_purchases (request_id,revision_id,revision_line_id,purchased_qty,unavailable_qty,"
                "purchase_date,unit_price,supplier_id,invoice_ref,notes,override,updated_by,updated_name,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["id"], revision["id"], line_id, purchased, unavailable, purchase_date, price, supplier_id,
                 invoice_ref, notes, 1 if override else 0, _uid(actor), _name(actor), now),
            )
        _event(
            conn, row["id"], "purchase_recorded", actor, line["product_name"],
            format_quantity(previous["purchased_qty"]) if previous else "0",
            format_quantity(purchased),
        )
    conn.execute(
        "UPDATE restock_requests SET updated_at=?, updated_by=?, updated_name=?, version=version+1 WHERE id=?",
        (now, _uid(actor), _name(actor), row["id"]),
    )
    fresh = _load(conn, request_id, actor)
    _recompute(conn, fresh)
    fresh = _load(conn, request_id, actor)
    return {"success": True, "request": _detail(conn, fresh, actor)}


def link_receipt(conn, actor, request_id: int, payload: dict) -> dict:
    """Attach an existing supplier delivery. This does not post stock again."""
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if not (_can(actor, "restock.manage") and _can(actor, "inventory.receive")):
        return _fail("You cannot link a delivery to this restock list.", 403)
    if row["status"] in ("draft", "cancelled", "archived"):
        return _fail("Send the list before linking a delivery.")
    try:
        line_id = int(payload.get("line_id"))
        receipt_id = int(payload.get("receipt_id"))
    except (TypeError, ValueError):
        return _fail("Choose the restock line and the delivery.")
    line = conn.execute(
        "SELECT * FROM restock_lines WHERE id=? AND request_id=?",
        (line_id, row["id"]),
    ).fetchone()
    if not line:
        return _fail("That product is not on this list.")
    try:
        accepted = parse_quantity(payload.get("qty_accepted"), line["unit"], allow_zero=True)
        rejected = parse_quantity(payload.get("qty_rejected") or 0, line["unit"], allow_zero=True)
    except QuantityError as exc:
        return _fail(str(exc))
    receipt = conn.execute("SELECT * FROM stock_receipts WHERE id=?", (receipt_id,)).fetchone()
    if not receipt:
        return _fail("That delivery was not found.")
    matched = conn.execute(
        "SELECT COALESCE(SUM(quantity),0) AS qty FROM stock_receipt_lines WHERE receipt_id=? AND product_id=?",
        (receipt_id, line["product_id"]),
    ).fetchone()
    if float(matched["qty"] or 0) + 0.00001 < accepted:
        return _fail("The accepted quantity is higher than that delivery recorded for this product.")
    existing = conn.execute(
        "SELECT id FROM restock_receipt_links WHERE line_id=? AND receipt_id=?",
        (line_id, receipt_id),
    ).fetchone()
    if existing:
        fresh = _load(conn, request_id, actor)
        return {"success": True, "duplicate": True, "request": _detail(conn, fresh, actor)}
    now = _now()
    revision = _current_revision(conn, row)
    conn.execute(
        "INSERT INTO restock_receipt_links (request_id,revision_id,line_id,receipt_id,receipt_number,"
        "supplier_id,product_id,qty_received,qty_accepted,qty_rejected,linked_by,linked_name,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (row["id"], revision["id"] if revision else None, line_id, receipt_id,
         receipt["receipt_number"] or "", receipt["supplier_id"], line["product_id"],
         accepted + rejected, accepted, rejected, _uid(actor), _name(actor), now),
    )
    _event(conn, row["id"], "receipt_linked", actor,
           f"{line['product_name']} {receipt['receipt_number'] or receipt_id} accepted {format_quantity(accepted)}")
    conn.execute(
        "UPDATE restock_requests SET updated_at=?, updated_by=?, updated_name=?, version=version+1 WHERE id=?",
        (now, _uid(actor), _name(actor), row["id"]),
    )
    fresh = _load(conn, request_id, actor)
    _recompute(conn, fresh)
    fresh = _load(conn, request_id, actor)
    return {"success": True, "request": _detail(conn, fresh, actor)}


def cancel_request(conn, actor, request_id: int, payload: dict) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if not _can(actor, "restock.manage"):
        return _fail("You cannot cancel this restock list.", 403)
    if row["status"] in ("cancelled", "archived", "received"):
        return _fail("This list can no longer be cancelled.")
    reason = str((payload or {}).get("reason") or "").strip()
    if len(reason) < 3:
        return _fail("Write a reason for cancelling this list.")
    conflict = _check_version(row, (payload or {}).get("version"))
    if conflict:
        return conflict
    conn.execute(
        "UPDATE restock_requests SET status='cancelled', previous_status=?, cancel_reason=?, "
        "updated_at=?, updated_by=?, updated_name=?, version=version+1 WHERE id=?",
        (row["status"], reason[:500], _now(), _uid(actor), _name(actor), row["id"]),
    )
    _event(conn, row["id"], "cancelled", actor, reason)
    fresh = _load(conn, request_id, actor)
    return {"success": True, "request": _detail(conn, fresh, actor)}


def archive_request(conn, actor, request_id: int, expected_version) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if not _can(actor, "restock.manage") and not (_can(actor, "restock.create") and _owns(row, actor) and row["status"] == "draft"):
        return _fail("You cannot archive this restock list.", 403)
    if row["status"] == "archived":
        return _fail("This list is already archived.")
    conflict = _check_version(row, expected_version)
    if conflict:
        return conflict
    now = _now()
    conn.execute(
        "UPDATE restock_requests SET previous_status=?, status='archived', archived_at=?, archived_by=?, "
        "updated_at=?, updated_by=?, updated_name=?, version=version+1 WHERE id=?",
        (row["status"], now, _uid(actor), now, _uid(actor), _name(actor), row["id"]),
    )
    _event(conn, row["id"], "archived", actor, row["status"])
    fresh = _load(conn, request_id, actor)
    return {"success": True, "request": _detail(conn, fresh, actor)}


def reopen_request(conn, actor, request_id: int, expected_version) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if row["status"] != "archived":
        return _fail("Only an archived list can be reopened.")
    previous = row["previous_status"] or "draft"
    superadmin = str((actor or {}).get("role") or "") == "superadmin"
    own_draft = previous == "draft" and _can(actor, "restock.create") and _owns(row, actor)
    if not (superadmin or (_can(actor, "restock.manage") and previous == "draft") or own_draft):
        return _fail("This archived list stays as history.", 403)
    conflict = _check_version(row, expected_version)
    if conflict:
        return conflict
    restored = previous if previous in STATUSES and previous != "archived" else "draft"
    conn.execute(
        "UPDATE restock_requests SET status=?, archived_at=NULL, updated_at=?, updated_by=?, updated_name=?, "
        "version=version+1 WHERE id=?",
        (restored, _now(), _uid(actor), _name(actor), row["id"]),
    )
    _event(conn, row["id"], "reopened", actor, restored)
    fresh = _load(conn, request_id, actor)
    return {"success": True, "request": _detail(conn, fresh, actor)}


def duplicate_request(conn, actor, request_id: int) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if not (_can(actor, "restock.create") or _can(actor, "restock.manage")):
        return _fail("You cannot copy this restock list.", 403)
    created = create_request(conn, actor, {
        "name": f"{row['name']} copy"[:120],
        "description": row["description"] or "",
        "priority": row["priority"],
        "instructions": row["instructions"] or "",
        "desired_date": row["desired_date"] or "",
    })
    if created.get("error"):
        return created
    new_id = created["request"]["id"]
    new_row = _load(conn, new_id, actor)
    now = _now()
    for line in _lines(conn, row["id"]):
        product = _product(conn, line["product_id"])
        if not product or int(product["is_active"] or 0) != 1:
            continue
        conn.execute(
            "INSERT INTO restock_lines (request_id,product_id,product_name,sku,barcode,quantity,unit,notes,"
            "position,added_by,added_at,updated_by,updated_at,removed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (new_id, product["id"], product["name"], product["sku"] or "", product["barcode"] or "",
             line["quantity"], product["unit"] or "", line["notes"] or "", line["position"],
             _uid(actor), now, _uid(actor), now),
        )
    _event(conn, new_id, "duplicated", actor, row["reference"])
    fresh = _load(conn, new_id, actor)
    return {"success": True, "request": _detail(conn, fresh, actor)}


def complete_request(conn, actor, request_id: int, payload: dict) -> dict:
    ensure_schema(conn)
    row = _load(conn, request_id, actor)
    if not row:
        return _fail("That restock list was not found.", 404)
    if not _can(actor, "restock.manage"):
        return _fail("You cannot complete this restock list.", 403)
    if row["status"] in ("draft", "cancelled", "archived"):
        return _fail("Send the list before completing it.")
    reason = str((payload or {}).get("reason") or "").strip()
    if len(reason) < 3:
        return _fail("Write why this list is complete while some items are still outstanding.")
    conflict = _check_version(row, (payload or {}).get("version"))
    if conflict:
        return conflict
    conn.execute(
        "UPDATE restock_requests SET status='received', explicit_complete=1, complete_reason=?, "
        "updated_at=?, updated_by=?, updated_name=?, version=version+1 WHERE id=?",
        (reason[:500], _now(), _uid(actor), _name(actor), row["id"]),
    )
    _event(conn, row["id"], "completed", actor, reason)
    fresh = _load(conn, request_id, actor)
    return {"success": True, "request": _detail(conn, fresh, actor)}


def suggestions(conn, actor) -> dict:
    if not (_can(actor, "restock.view") or _can(actor, "restock.manage") or _can(actor, "restock.create")):
        return _fail("You cannot view restock suggestions.", 403)
    ensure_schema(conn)
    cols = {item[1] for item in conn.execute("PRAGMA table_info(products)").fetchall()}
    if "min_stock" not in cols or "stock" not in cols:
        return {"success": True, "suggestions": [], "note": "This catalogue has no reorder level."}
    rows = conn.execute(
        "SELECT id, name, sku, barcode, unit, stock, min_stock FROM products "
        "WHERE COALESCE(is_active,1)=1 AND min_stock IS NOT NULL AND stock <= min_stock "
        "ORDER BY stock ASC, name ASC LIMIT 200"
    ).fetchall()
    suggestions_out = []
    for row in rows:
        stock = float(row["stock"] or 0)
        minimum = float(row["min_stock"] or 0)
        gap = max(0.0, minimum - stock)
        suggestions_out.append({
            "product_id": int(row["id"]),
            "product_name": row["name"],
            "sku": row["sku"] or "",
            "barcode": row["barcode"] or "",
            "unit": row["unit"] or "",
            "stock": stock,
            "min_stock": minimum,
            "suggested_qty": gap if gap > 0 else 1,
            "out_of_stock": stock <= 0,
        })
    return {"success": True, "suggestions": suggestions_out}


def buyers(conn, actor) -> dict:
    if not _can(actor, "restock.manage"):
        return _fail("You cannot assign buyers.", 403)
    rows = conn.execute(
        "SELECT id, full_name, username, role FROM users WHERE COALESCE(is_active,1)=1 ORDER BY full_name, username"
    ).fetchall()
    return {"success": True, "buyers": [
        {"id": int(row["id"]), "name": row["full_name"] or row["username"], "role": row["role"]}
        for row in rows
    ]}


def _setting(conn, key: str) -> str:
    try:
        row = conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
    except sqlite3.Error:
        return ""
    return str(row[0]).strip() if row and row[0] else ""


def document_html(conn, actor, request_id: int) -> dict:
    found = get_request(conn, actor, request_id)
    if found.get("error"):
        return found
    request_body = found["request"]
    shop = _setting(conn, "shop_name") or "Shop"
    address = _setting(conn, "shop_address")
    phone = _setting(conn, "shop_phone")
    see_cost = _can(actor, "inventory.view_cost")
    rows = []
    for index, line in enumerate(request_body.get("lines") or [], start=1):
        price = ""
        if see_cost and line.get("unit_price") is not None:
            price = f"<td>{html.escape(format_quantity(line['unit_price']))}</td>"
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{html.escape(str(line.get('product_name') or ''))}</td>"
            f"<td>{html.escape(str(line.get('sku') or ''))}</td>"
            f"<td class='num'>{html.escape(str(line.get('quantity_text') or ''))}</td>"
            f"<td>{html.escape(str(line.get('unit') or ''))}</td>"
            f"<td>{html.escape(str(line.get('notes') or ''))}</td>"
            f"{price}"
            "</tr>"
        )
    price_head = "<th>Unit price</th>" if see_cost and any(
        (line.get("unit_price") is not None) for line in (request_body.get("lines") or [])
    ) else ""
    buyer = request_body.get("buyer_name") or request_body.get("external_buyer") or "Not assigned"
    body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{html.escape(request_body['reference'])}</title>
<style>
body {{ font-family: Georgia, serif; color: #1c1915; margin: 24px; }}
h1 {{ font-size: 22px; letter-spacing: 0.04em; margin-bottom: 0; }}
.banner {{ border: 1px solid #8a5a12; background: #fff7e8; padding: 10px 12px; margin: 16px 0; font-family: sans-serif; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
th, td {{ border-bottom: 1px solid #ddd; text-align: left; padding: 8px 6px; vertical-align: top; }}
th {{ font-size: 12px; letter-spacing: 0.04em; }}
.num {{ text-align: right; white-space: nowrap; }}
.sign {{ margin-top: 28px; display: flex; gap: 24px; }}
.sign div {{ flex: 1; border-top: 1px solid #333; padding-top: 8px; min-height: 72px; }}
@media print {{ body {{ margin: 12mm; }} }}
</style></head><body>
<h1>RESTOCKING REQUEST</h1>
<p><strong>{html.escape(shop)}</strong><br>{html.escape(address)}<br>{html.escape(phone)}</p>
<p><strong>{html.escape(request_body['reference'])}</strong> · {html.escape(request_body['name'])}<br>
Status: {html.escape(request_body['status_label'])} · Priority: {html.escape(request_body['priority'])}<br>
Prepared: {html.escape(request_body['created_at'] or '')} by {html.escape(request_body['created_name'] or '')}<br>
Sent: {html.escape(request_body['submitted_at'] or 'Not sent')}<br>
Assigned to: {html.escape(buyer)}</p>
<div class="banner">THIS IS A RESTOCKING REQUEST. IT IS NOT A SUPPLIER INVOICE OR GOODS RECEIVED NOTE.
Goods are not purchased or received until a buyer and the shop record that separately.</div>
<p>{html.escape(request_body.get('instructions') or '')}</p>
<table><thead><tr><th>No.</th><th>Product</th><th>SKU</th><th>Quantity</th><th>Unit</th><th>Notes</th>{price_head}</tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="6">No products yet.</td></tr>'}</tbody></table>
<div class="sign"><div>Prepared by</div><div>Buyer confirmation</div></div>
</body></html>"""
    _event(conn, request_id, "printed", actor, request_body["reference"])
    conn.commit()
    return {"success": True, "html": body, "reference": request_body["reference"]}


def _document_body(conn, actor, request_id: int) -> dict:
    found = get_request(conn, actor, request_id)
    if found.get("error"):
        return found
    body = dict(found["request"])
    body["shop_name"] = _setting(conn, "shop_name") or "Shop"
    body["shop_address"] = _setting(conn, "shop_address")
    body["shop_phone"] = _setting(conn, "shop_phone")
    body["printed_at"] = _now()
    return {"success": True, "request": body}


def document_text(conn, actor, request_id: int, paper: str = "80") -> dict:
    """Receipt-printer text. This does not change stock or sales."""
    found = _document_body(conn, actor, request_id)
    if found.get("error"):
        return found
    from printing.sheet import columns_for, restock_lines
    width = columns_for(paper)
    lines = restock_lines(found["request"], width)
    _event(conn, request_id, "printed", actor, f"{found['request']['reference']} thermal {paper}")
    return {
        "success": True,
        "text": "\n".join(lines),
        "lines": lines,
        "paper": "58" if str(paper).startswith("58") else "80",
        "reference": found["request"]["reference"],
    }


def document_pdf(conn, actor, request_id: int, layout: str = "a4", paper: str = "80") -> dict:
    """PDF bytes. layout=a4 is the office copy. layout=thermal matches the receipt width."""
    if str(layout or "a4").lower() == "thermal":
        found = document_text(conn, actor, request_id, paper)
        if found.get("error"):
            return found
        from printing.sale_documents import lines_to_pdf
        blob = lines_to_pdf(found["lines"], found["paper"])
        return {"success": True, "pdf": blob, "reference": found["reference"], "layout": "thermal", "paper": found["paper"]}
    found = _document_body(conn, actor, request_id)
    if found.get("error"):
        return found
    from printing.sheet import restock_lines
    from printing.sale_documents import office_pdf
    lines = restock_lines(found["request"], 90)
    blob = office_pdf(lines, found["request"]["reference"], "RESTOCKING REQUEST")
    _event(conn, request_id, "printed", actor, f"{found['request']['reference']} pdf")
    return {"success": True, "pdf": blob, "reference": found["request"]["reference"], "layout": "a4"}


def search_products(conn, actor, query: str) -> dict:
    if not (_can(actor, "inventory.view") or _can(actor, "restock.create") or _can(actor, "restock.manage")):
        return _fail("You cannot search products.", 403)
    text = f"%{str(query or '').strip()}%"
    rows = conn.execute(
        "SELECT id, name, sku, barcode, category, unit, stock, min_stock, is_active FROM products "
        "WHERE COALESCE(is_active,1)=1 AND (name LIKE ? OR sku LIKE ? OR barcode LIKE ? OR category LIKE ?) "
        "ORDER BY name LIMIT 30",
        (text, text, text, text),
    ).fetchall()
    return {"success": True, "products": [dict(row) for row in rows]}
