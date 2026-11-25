"""Product and selling-price changes that wait for an administrator.

Admin and Super Admin publish immediately. A manager's product, price, unit,
or quantity-precision change stays in the existing approval list until an
admin approves it. Approval writes the product card only. Sales, receipts,
batch costs, FIFO quantities, and stock are left as they were.
"""
from __future__ import annotations

import json
from datetime import datetime

PUBLISH = "product_publish"
CHANGE = "product_change"
_OPEN = ("pending", "rejected", "returned")
_TEXT_FIELDS = ("name", "sku", "category", "unit", "barcode")
_NUMBER_FIELDS = ("price", "cost_price", "min_stock", "is_active", "allow_decimal_qty")


def _role(actor: dict) -> str:
    return str((actor or {}).get("role") or "").strip().lower()


def publishes_now(actor: dict) -> bool:
    return _role(actor) in ("admin", "superadmin")


def _actor(api) -> dict:
    from desktop.utils.security import client_actor
    return client_actor(api)


def _direct_price(api) -> bool:
    from desktop.utils.security import has_permission
    actor = _actor(api)
    return publishes_now(actor) or has_permission(actor, "inventory.direct_price")


def _name_key(value) -> str:
    return str(value or "").strip().casefold()


def _meta(raw) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _number(value):
    if value is None or value == "":
        return None
    return round(float(value), 4)


def _changed(old, data: dict) -> dict:
    changed = {}
    keys = old.keys() if hasattr(old, "keys") else ()
    for field in _TEXT_FIELDS:
        if field not in data:
            continue
        before = old[field] if field in keys else ""
        after = data.get(field)
        if str(before or "").strip() != str(after or "").strip():
            changed[field] = after
    for field in _NUMBER_FIELDS:
        if field not in data:
            continue
        before = old[field] if field in keys else None
        after = data.get(field)
        try:
            left = None if before is None else _number(before)
            right = None if after is None else _number(after)
        except (TypeError, ValueError):
            left, right = before, after
        if left != right:
            changed[field] = after
    changed.pop("stock", None)
    return changed


def _open_rows(db, user_id, kind: str):
    return db.execute(
        "SELECT id, status, meta_json FROM cc_approvals "
        "WHERE type=? AND requested_by_id=? AND status IN ('pending','rejected','returned') "
        "ORDER BY id DESC",
        (kind, int(user_id)),
    ).fetchall()


def _find_create(db, user_id, name: str):
    wanted = _name_key(name)
    if not wanted:
        return None
    for row in _open_rows(db, user_id, PUBLISH):
        if _name_key(_meta(row["meta_json"]).get("name")) == wanted:
            return row
    return None


def _find_change(db, user_id, product_id: int):
    for row in _open_rows(db, user_id, CHANGE):
        try:
            found = int(_meta(row["meta_json"]).get("product_id") or 0)
        except (TypeError, ValueError):
            found = 0
        if found == int(product_id):
            return row
    return None


def _save_request(db, api, kind: str, title: str, details: str, amount, meta: dict, existing=None) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    payload = json.dumps(meta)
    if existing is not None:
        db.execute(
            "UPDATE cc_approvals SET title=?, details=?, amount=?, status='pending', "
            "meta_json=?, review_note='', updated_at=? WHERE id=? "
            "AND status IN ('pending','rejected','returned')",
            (title, details, amount, payload, now, int(existing["id"])),
        )
        return int(existing["id"])
    db.execute(
        "INSERT INTO cc_approvals "
        "(type, title, details, amount, status, requested_by, requested_by_id, meta_json, updated_at) "
        "VALUES (?,?,?,?, 'pending',?,?,?,?)",
        (
            kind, title, details, amount,
            api._username or "", api._user_id, payload, now,
        ),
    )
    return int(db.execute("SELECT last_insert_rowid()").fetchone()[0])


def hold_create(api, product: dict, db=None):
    """Queue a manager's new product. None means the caller publishes it now."""
    actor = _actor(api)
    if publishes_now(actor):
        return None
    if _role(actor) != "manager":
        return {"error": "You cannot add a product.", "status": 403}
    own_connection = db is None
    if own_connection:
        from desktop.utils.api_client import _db
        db = _db()
    name = str(product.get("name") or "").strip()
    try:
        api._ensure_approval_table(db)
        existing = _find_create(db, api._user_id, name)
        price = _number(product.get("price")) or 0
        meta = {
            "name": name,
            "product": product,
        }
        request_id = _save_request(
            db, api, PUBLISH,
            f"New product: {name}",
            "Waiting for an administrator. The product is not on the selling list yet.",
            price, meta, existing,
        )
        db.commit()
    finally:
        if own_connection:
            db.close()
    return {
        "success": True,
        "pending_approval": True,
        "published": False,
        "id": None,
        "request_id": request_id,
        "replaced_request": existing is not None,
        "message": "Waiting for an administrator. The product was not published.",
    }


def hold_update(api, db, old, data: dict):
    """Queue a manager's product edit. None means the caller writes it now.

    A direct-price grant writes only products.price. Every other change,
    including unit and decimal precision, stays pending.
    """
    actor = _actor(api)
    if publishes_now(actor):
        return None
    if _role(actor) != "manager":
        return {"error": "You cannot change this product.", "status": 403}
    changed = _changed(old, data)
    if not changed:
        return {"success": True, "pending_approval": False, "unchanged": True}
    price_applied = False
    if "price" in changed and _direct_price(api):
        db.execute(
            "UPDATE products SET price=?, updated_at=? WHERE id=?",
            (_number(changed.pop("price")), datetime.now().isoformat(timespec="seconds"), int(old["id"])),
        )
        price_applied = True
    api._ensure_approval_table(db)
    if not changed:
        existing = _find_change(db, api._user_id, int(old["id"]))
        if existing is not None:
            db.execute(
                "UPDATE cc_approvals SET status='withdrawn', review_note=?, updated_at=? "
                "WHERE id=? AND status IN ('pending','rejected','returned')",
                (
                    "The selling price was saved directly.",
                    datetime.now().isoformat(timespec="seconds"),
                    int(existing["id"]),
                ),
            )
        db.commit()
        return {
            "success": True,
            "pending_approval": False,
            "price_applied": True,
            "message": "Selling price saved. Older sales, receipts, and stock were not changed.",
        }
    product_name = str(old["name"] if "name" in old.keys() else "") or "Product"
    price = changed.get("price", old["price"] if "price" in old.keys() else 0)
    meta = {
        "product_id": int(old["id"]),
        "name": product_name,
        "changes": changed,
    }
    existing = _find_change(db, api._user_id, int(old["id"]))
    request_id = _save_request(
        db, api, CHANGE,
        f"Product change: {product_name}",
        "Waiting for an administrator. The live product and price stay as they are.",
        _number(price) or 0,
        meta,
        existing,
    )
    db.commit()
    message = "Waiting for an administrator. The live product was not changed."
    if price_applied:
        message = "Selling price saved. The other changes wait for an administrator."
    return {
        "success": True,
        "pending_approval": True,
        "published": False,
        "price_applied": price_applied,
        "request_id": request_id,
        "replaced_request": existing is not None,
        "message": message,
    }


def apply_approved(api, approval_id: int, kind: str, meta: dict) -> dict:
    """Publish one approved request. A second call does not create another product."""
    if not isinstance(meta, dict):
        meta = {}
    if meta.get("applied") or meta.get("applied_product_id"):
        return {
            "success": True,
            "duplicate": True,
            "id": meta.get("applied_product_id"),
        }
    if kind == PUBLISH:
        result = api.create_product(dict(meta.get("product") or {}))
        applied_id = result.get("id")
    elif kind == CHANGE:
        try:
            product_id = int(meta.get("product_id") or 0)
        except (TypeError, ValueError):
            product_id = 0
        changes = dict(meta.get("changes") or {})
        changes.pop("stock", None)
        result = api.update_product(product_id, changes)
        applied_id = product_id if result.get("success") else None
    else:
        return {"error": "That request cannot be published.", "status": 400}
    if not result.get("success"):
        return result
    from desktop.utils.api_client import _db
    db = _db()
    try:
        row = db.execute(
            "SELECT meta_json FROM cc_approvals WHERE id=?", (int(approval_id),)
        ).fetchone()
        current = _meta(row["meta_json"] if row else "{}")
        current["applied"] = True
        current["applied_product_id"] = applied_id
        db.execute(
            "UPDATE cc_approvals SET meta_json=? WHERE id=?",
            (json.dumps(current), int(approval_id)),
        )
        db.commit()
    finally:
        db.close()
    result["applied_product_id"] = applied_id
    return result
