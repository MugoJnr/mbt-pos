"""One list of the receipt-producing records the shop already stores."""
from __future__ import annotations

import json
import sqlite3


def _tables(db) -> set[str]:
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] if not isinstance(row, sqlite3.Row) else row[0] for row in rows}


def _has(tables: set[str], name: str) -> bool:
    return name in tables


def _like(value: str) -> str:
    return f"%{(value or '').strip()}%"


def _paid_with(method: str, raw_tenders) -> str:
    names = []
    parsed = []
    if raw_tenders:
        try:
            loaded = json.loads(raw_tenders) if isinstance(raw_tenders, str) else raw_tenders
            if isinstance(loaded, list):
                parsed = loaded
        except (json.JSONDecodeError, TypeError):
            parsed = []
    for tender in parsed:
        if not isinstance(tender, dict):
            continue
        name = str(tender.get("method") or "").strip()
        status = str(tender.get("status") or "confirmed").lower()
        if not name or status != "confirmed" or name.lower() in ("credit", "account"):
            continue
        if name not in names:
            names.append(name)
    if names:
        return " + ".join(names)
    return method or ""


def _day(expr: str, start: str, end: str) -> tuple[str, list]:
    if start and end:
        return f"date({expr}) BETWEEN ? AND ?", [start, end]
    if start:
        return f"date({expr}) >= ?", [start]
    if end:
        return f"date({expr}) <= ?", [end]
    return "1=1", []


def _sale_history(db, tables: set[str], sale_id: int) -> list:
    if not _has(tables, "sale_edits"):
        return []
    columns = {row[1] for row in db.execute("PRAGMA table_info(sale_edits)").fetchall()}
    stamp = "created_at" if "created_at" in columns else "id"
    return [
        dict(row) for row in db.execute(
            f"""SELECT edit_type, field_name, old_value, new_value, reason,
                       edited_by_name, {stamp} AS at
                FROM sale_edits WHERE sale_id=? ORDER BY id""",
            (int(sale_id),),
        ).fetchall()
    ]


def _receipt_audit(db, tables: set[str], reference: str) -> list:
    if not reference or not _has(tables, "audit_log"):
        return []
    return [
        dict(row) for row in db.execute(
            """SELECT created_at, username, action, details
               FROM audit_log
               WHERE details LIKE ?
                 AND action IN ('VOID_SALE','UNVOID_SALE','VOID_CONSUMPTION','UNVOID_CONSUMPTION')
               ORDER BY id""",
            (f"%{reference}%",),
        ).fetchall()
    ]


def list_receipts(
    db,
    *,
    can_sales: bool = False,
    can_consumption: bool = False,
    can_inventory: bool = False,
    can_adjustments: bool = False,
    can_debt: bool = False,
    can_finance: bool = False,
    can_approvals: bool = False,
    username: str = "",
    kind: str = "",
    status: str = "",
    query: str = "",
    start: str = "",
    end: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return a page of receipts the caller is allowed to see."""
    tables = _tables(db)
    kind = (kind or "").strip().lower()
    status = (status or "").strip().lower()
    query = (query or "").strip()
    rows: list[dict] = []

    def keep(item: dict) -> bool:
        if kind and item["kind"] != kind:
            return False
        if status:
            shown = (item.get("display_status") or item.get("status") or "").lower()
            raw = (item.get("status") or "").lower()
            if status not in (shown, raw):
                return False
        if query:
            blob = " ".join(
                str(item.get(key) or "")
                for key in ("reference", "user", "summary", "payment", "kind")
            ).lower()
            if query.lower() not in blob:
                return False
        return True

    if can_sales and _has(tables, "sales"):
        clause, params = _day("COALESCE(s.sale_date, s.created_at)", start, end)
        sale_cols = {item[1] for item in db.execute("PRAGMA table_info(sales)").fetchall()}
        tender_sql = "s.payment_tenders" if "payment_tenders" in sale_cols else "NULL AS payment_tenders"
        found = db.execute(
            f"""SELECT s.id, s.receipt_number, s.created_at, s.cashier_name,
                       s.total, s.status, s.payment_method, {tender_sql},
                       GROUP_CONCAT(si.product_name, ', ') AS products
                FROM sales s
                LEFT JOIN sale_items si ON si.sale_id = s.id
                WHERE {clause}
                GROUP BY s.id
                ORDER BY s.id DESC LIMIT 1000""",
            params,
        ).fetchall()
        for row in found:
            raw_status = (row["status"] or "completed").lower()
            rows.append({
                "kind": "sale",
                "id": row["id"],
                "reference": row["receipt_number"],
                "at": row["created_at"],
                "user": row["cashier_name"] or "",
                "amount": row["total"],
                "status": raw_status,
                "display_status": "voided" if raw_status == "voided" else (
                    "pending" if raw_status in ("pending", "held") else "active"
                ),
                "payment": _paid_with(row["payment_method"] or "", row["payment_tenders"]),
                "summary": row["products"] or "",
            })
        if _has(tables, "sale_edits"):
            restored = {
                int(item[0]) for item in db.execute(
                    "SELECT DISTINCT sale_id FROM sale_edits WHERE edit_type='UNVOID'"
                ).fetchall()
            }
            for item in rows:
                if item.get("kind") == "sale" and item["id"] in restored and item["status"] != "voided":
                    item["display_status"] = "restored"

    if can_consumption and _has(tables, "stock_consumptions"):
        clause, params = _day("COALESCE(c.date, c.created_at)", start, end)
        found = db.execute(
            f"""SELECT c.id, c.reference_no, c.created_at, c.created_by_name,
                       c.total_cost, c.voided, c.reason
                FROM stock_consumptions c
                WHERE {clause}
                ORDER BY c.id DESC LIMIT 1000""",
            params,
        ).fetchall()
        for row in found:
            rows.append({
                "kind": "consumption",
                "id": row["id"],
                "reference": row["reference_no"],
                "at": row["created_at"],
                "user": row["created_by_name"] or "",
                "amount": row["total_cost"],
                "status": "voided" if int(row["voided"] or 0) else "recorded",
                "display_status": "voided" if int(row["voided"] or 0) else "active",
                "payment": "",
                "summary": row["reason"] or "",
            })
        if _has(tables, "stock_movements"):
            restored_refs = {
                item[0] for item in db.execute(
                    "SELECT reference FROM stock_movements WHERE movement_type='INTERNAL_USE_UNVOID'"
                ).fetchall()
            }
            for item in rows:
                if (
                    item.get("kind") == "consumption"
                    and item.get("reference") in restored_refs
                    and item.get("status") != "voided"
                ):
                    item["display_status"] = "restored"

    if can_inventory and _has(tables, "stock_receipts"):
        clause, params = _day("r.created_at", start, end)
        found = db.execute(
            f"""SELECT r.id, r.receipt_number, r.created_at, r.username,
                       r.grand_total, r.reference_note,
                       GROUP_CONCAT(l.product_name, ', ') AS products
                FROM stock_receipts r
                LEFT JOIN stock_receipt_lines l ON l.receipt_id = r.id
                WHERE {clause}
                GROUP BY r.id
                ORDER BY r.id DESC LIMIT 1000""",
            params,
        ).fetchall()
        for row in found:
            rows.append({
                "kind": "supplier",
                "id": row["id"],
                "reference": row["receipt_number"],
                "at": row["created_at"],
                "user": row["username"] or "",
                "amount": row["grand_total"],
                "status": "received",
                "payment": "",
                "summary": row["products"] or row["reference_note"] or "",
            })

    if can_debt and _has(tables, "debt_payments"):
        clause, params = _day("p.created_at", start, end)
        found = db.execute(
            f"""SELECT p.id, p.payment_receipt, p.created_at, p.cashier_name,
                       p.amount, p.payment_method
                FROM debt_payments p
                WHERE {clause}
                ORDER BY p.id DESC LIMIT 1000""",
            params,
        ).fetchall()
        for row in found:
            rows.append({
                "kind": "debt_payment",
                "id": row["id"],
                "reference": row["payment_receipt"],
                "at": row["created_at"],
                "user": row["cashier_name"] or "",
                "amount": row["amount"],
                "status": "recorded",
                "payment": row["payment_method"] or "",
                "summary": "Customer repayment",
            })

    if can_finance and _has(tables, "expense_entries"):
        clause, params = _day("e.expense_date", start, end)
        found = db.execute(
            f"""SELECT e.id, e.expense_number, e.created_at, e.created_by_name,
                       e.amount, e.status, e.description, e.vendor_name
                FROM expense_entries e
                WHERE e.deleted_at IS NULL AND {clause}
                ORDER BY e.id DESC LIMIT 1000""",
            params,
        ).fetchall()
        for row in found:
            rows.append({
                "kind": "expense",
                "id": row["id"],
                "reference": row["expense_number"],
                "at": row["created_at"],
                "user": row["created_by_name"] or "",
                "amount": row["amount"],
                "status": row["status"] or "approved",
                "payment": "",
                "summary": row["description"] or row["vendor_name"] or "",
            })

    if (can_inventory or can_adjustments) and _has(tables, "stock_adjustment_requests"):
        clause, params = _day("a.created_at", start, end)
        found = db.execute(
            f"""SELECT a.id, a.request_number, a.created_at, a.username,
                       a.product_name, a.current_stock, a.requested_qty,
                       a.status, a.reason
                FROM stock_adjustment_requests a
                WHERE {clause}
                ORDER BY a.id DESC LIMIT 1000""",
            params,
        ).fetchall()
        for row in found:
            rows.append({
                "kind": "stock_adjustment",
                "id": row["id"],
                "reference": row["request_number"],
                "at": row["created_at"],
                "user": row["username"] or "",
                "amount": None,
                "status": row["status"] or "pending",
                "payment": "",
                "summary": (
                    f"{row['product_name']}: {row['current_stock']} → "
                    f"{row['requested_qty']}. {row['reason'] or ''}"
                ).strip(),
            })

    if can_approvals and _has(tables, "cc_approvals"):
        clause, params = _day("a.created_at", start, end)
        sql = (
            f"""SELECT a.id, a.type, a.title, a.created_at, a.requested_by,
                       a.amount, a.status, a.details
                FROM cc_approvals a
                WHERE {clause}"""
        )
        if not can_inventory and username:
            sql += " AND a.requested_by=?"
            params.append(username)
        sql += " ORDER BY a.id DESC LIMIT 1000"
        found = db.execute(sql, params).fetchall()
        for row in found:
            rows.append({
                "kind": "approval",
                "id": row["id"],
                "reference": f"{row['type']} #{row['id']}",
                "at": row["created_at"],
                "user": row["requested_by"] or "",
                "amount": row["amount"],
                "status": row["status"] or "pending",
                "payment": "",
                "summary": row["title"] or row["details"] or "",
            })

    kept = [item for item in rows if keep(item)]
    kept.sort(key=lambda item: (item.get("at") or "", item.get("id") or 0), reverse=True)
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    return {"total": len(kept), "receipts": kept[offset:offset + limit]}


def receipt_detail(db, kind: str, record_id: int, *, show_cost: bool = False) -> dict | None:
    """Open one receipt. Cost fields stay out unless the caller may see them."""
    tables = _tables(db)
    kind = (kind or "").strip().lower()
    record_id = int(record_id)

    if kind == "sale" and _has(tables, "sales"):
        sale = db.execute("SELECT * FROM sales WHERE id=?", (record_id,)).fetchone()
        if not sale:
            return None
        items = db.execute(
            """SELECT product_name, sku, quantity, unit_price, discount, total
               FROM sale_items WHERE sale_id=? ORDER BY id""",
            (record_id,),
        ).fetchall()
        body = dict(sale)
        if not show_cost:
            body.pop("cost", None)
        customer = None
        if sale["customer_id"] if "customer_id" in sale.keys() else None:
            found = db.execute(
                "SELECT id, name, phone FROM customers WHERE id=?",
                (sale["customer_id"],),
            ).fetchone()
            customer = dict(found) if found else None
        tenders = []
        raw_tenders = sale["payment_tenders"] if "payment_tenders" in sale.keys() else None
        if raw_tenders:
            try:
                parsed = json.loads(raw_tenders)
                if isinstance(parsed, list):
                    tenders = parsed
            except (json.JSONDecodeError, TypeError):
                tenders = []
        debt = None
        if _has(tables, "debt_invoices"):
            invoice = db.execute(
                "SELECT id, invoice_number, total_amount, amount_paid, balance, status "
                "FROM debt_invoices WHERE sale_id=? AND COALESCE(status,'') != 'cancelled' "
                "ORDER BY id DESC LIMIT 1",
                (record_id,),
            ).fetchone()
            debt = dict(invoice) if invoice else None
        linked = []
        if _has(tables, "cc_approvals"):
            for approval in db.execute(
                "SELECT id, type, status, title, details, review_note FROM cc_approvals"
            ).fetchall():
                meta = {}
                try:
                    raw = db.execute(
                        "SELECT meta_json FROM cc_approvals WHERE id=?", (approval["id"],)
                    ).fetchone()
                    meta = json.loads((raw["meta_json"] if raw else "") or "{}")
                except (json.JSONDecodeError, TypeError, KeyError):
                    meta = {}
                if int(meta.get("sale_id") or 0) == record_id:
                    item = dict(approval)
                    item["current_reason"] = meta.get("current_reason") or approval["details"] or ""
                    linked.append(item)
        return {
            "kind": "sale",
            "reference": sale["receipt_number"],
            "header": body,
            "lines": [dict(item) for item in items],
            "approvals": linked,
            "customer": customer,
            "tenders": tenders,
            "debt": debt,
            "history": _sale_history(db, tables, record_id) + _receipt_audit(
                db, tables, sale["receipt_number"] or ""
            ),
        }

    if kind == "consumption" and _has(tables, "stock_consumptions"):
        row = db.execute("SELECT * FROM stock_consumptions WHERE id=?", (record_id,)).fetchone()
        if not row:
            return None
        lines = db.execute(
            "SELECT * FROM stock_consumption_items WHERE consumption_id=? ORDER BY id",
            (record_id,),
        ).fetchall() if _has(tables, "stock_consumption_items") else []
        header = dict(row)
        cleaned = []
        for line in lines:
            item = dict(line)
            if not show_cost:
                for key in ("unit_cost", "line_cost", "selling_price", "retail_opportunity", "foregone_profit"):
                    item.pop(key, None)
            cleaned.append(item)
        if not show_cost:
            header.pop("total_cost", None)
        return {
            "kind": "consumption",
            "reference": row["reference_no"],
            "header": header,
            "lines": cleaned,
            "history": _receipt_audit(db, tables, row["reference_no"] or ""),
        }

    if kind == "supplier" and _has(tables, "stock_receipts"):
        row = db.execute("SELECT * FROM stock_receipts WHERE id=?", (record_id,)).fetchone()
        if not row:
            return None
        lines = db.execute(
            "SELECT * FROM stock_receipt_lines WHERE receipt_id=? ORDER BY id",
            (record_id,),
        ).fetchall()
        header = dict(row)
        cleaned = []
        for line in lines:
            item = dict(line)
            if not show_cost:
                item.pop("unit_cost", None)
                item.pop("line_total", None)
            cleaned.append(item)
        if not show_cost:
            header.pop("grand_total", None)
        return {
            "kind": "supplier",
            "reference": row["receipt_number"],
            "header": header,
            "lines": cleaned,
        }

    if kind == "stock_adjustment" and _has(tables, "stock_adjustment_requests"):
        row = db.execute(
            "SELECT * FROM stock_adjustment_requests WHERE id=?", (record_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "kind": "stock_adjustment",
            "reference": row["request_number"],
            "header": dict(row),
            "lines": [],
        }

    if kind == "debt_payment" and _has(tables, "debt_payments"):
        row = db.execute("SELECT * FROM debt_payments WHERE id=?", (record_id,)).fetchone()
        if not row:
            return None
        return {
            "kind": "debt_payment",
            "reference": row["payment_receipt"],
            "header": dict(row),
            "lines": [],
        }

    if kind == "expense" and _has(tables, "expense_entries"):
        row = db.execute("SELECT * FROM expense_entries WHERE id=?", (record_id,)).fetchone()
        if not row:
            return None
        return {
            "kind": "expense",
            "reference": row["expense_number"],
            "header": dict(row),
            "lines": [],
        }

    if kind == "approval" and _has(tables, "cc_approvals"):
        row = db.execute("SELECT * FROM cc_approvals WHERE id=?", (record_id,)).fetchone()
        if not row:
            return None
        header = dict(row)
        return {
            "kind": "approval",
            "reference": f"{row['type']} #{row['id']}",
            "header": header,
            "lines": [],
        }
    return None
