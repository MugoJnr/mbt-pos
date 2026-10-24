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


def _day(expr: str, start: str, end: str) -> tuple[str, list]:
    if start and end:
        return f"date({expr}) BETWEEN ? AND ?", [start, end]
    if start:
        return f"date({expr}) >= ?", [start]
    if end:
        return f"date({expr}) <= ?", [end]
    return "1=1", []


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
        if status and (item.get("status") or "").lower() != status:
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
        found = db.execute(
            f"""SELECT s.id, s.receipt_number, s.created_at, s.cashier_name,
                       s.total, s.status, s.payment_method,
                       GROUP_CONCAT(si.product_name, ', ') AS products
                FROM sales s
                LEFT JOIN sale_items si ON si.sale_id = s.id
                WHERE {clause}
                GROUP BY s.id
                ORDER BY s.id DESC LIMIT 1000""",
            params,
        ).fetchall()
        for row in found:
            rows.append({
                "kind": "sale",
                "id": row["id"],
                "reference": row["receipt_number"],
                "at": row["created_at"],
                "user": row["cashier_name"] or "",
                "amount": row["total"],
                "status": row["status"] or "completed",
                "payment": row["payment_method"] or "",
                "summary": row["products"] or "",
            })

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
                "payment": "",
                "summary": row["reason"] or "",
            })

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
                    linked.append(dict(approval))
        return {
            "kind": "sale",
            "reference": sale["receipt_number"],
            "header": body,
            "lines": [dict(item) for item in items],
            "approvals": linked,
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
