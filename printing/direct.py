"""Print a saved document. Printing does not create a sale or change stock."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

_RECENT = {}
_LOCK = threading.Lock()
_ALLOWED = {"viewer", "cashier", "manager", "admin", "superadmin"}


def _actor_role(actor: dict) -> str:
    return str((actor or {}).get("role") or "").strip().lower()


def _counts(db) -> dict:
    found = {}
    for table in ("sales", "sale_items", "stock_movements", "stock_consumptions", "debt_payments"):
        try:
            found[table] = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            found[table] = None
    return found


def _record(db, label: str, status: str, reason: str) -> None:
    if db is None:
        return
    try:
        db.execute(
            """CREATE TABLE IF NOT EXISTS print_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT,
                status TEXT,
                reason TEXT,
                created_at TEXT
            )"""
        )
        db.execute(
            "INSERT INTO print_jobs (label, status, reason, created_at) VALUES (?,?,?,?)",
            (str(label or "")[:80], status, str(reason or "")[:180], datetime.now().isoformat(timespec="seconds")),
        )
        db.commit()
    except Exception:
        logger.info("Print job was not recorded")


def render_text(db, kind: str, record_id, actor: dict) -> dict:
    """The text the printer will receive. Totals come from the saved document."""
    role = _actor_role(actor)
    if role not in _ALLOWED:
        return {"error": "You cannot print receipts.", "status": 403}
    kind = str(kind or "").strip().lower()
    from printing.sale_documents import load_settings, paper_columns
    from printing.sheet import centre_lines, columns_for, consumption_lines

    cfg = load_settings(db)
    width = paper_columns(cfg) if cfg else columns_for("80")
    show_cost = False
    try:
        from desktop.utils.security import sees_product_cost
        show_cost = bool(sees_product_cost(actor or {}))
    except Exception:
        show_cost = role in ("admin", "superadmin", "manager")

    if kind == "sale":
        from printing.sale_documents import build_sale_document
        doc = build_sale_document(db, int(record_id), reprint=True)
        if doc.get("error"):
            return doc
        return {"success": True, "kind": kind, "reference": doc.get("number") or "", "text": doc.get("text") or "", "paper": cfg.get("paper_size")}

    if kind in ("debt_payment", "payment"):
        if str(record_id).isdigit():
            row = db.execute("SELECT payment_receipt FROM debt_payments WHERE id=?", (int(record_id),)).fetchone()
            receipt = row[0] if row else ""
        else:
            receipt = str(record_id or "").strip()
        if not receipt:
            return {"error": "That payment receipt was not found."}
        from printing.sale_documents import build_payment_document
        doc = build_payment_document(db, receipt, reprint=True)
        if doc.get("error"):
            return doc
        return {"success": True, "kind": "debt_payment", "reference": doc.get("number") or "", "text": doc.get("text") or "", "paper": cfg.get("paper_size")}

    if kind == "consumption":
        detail = _consumption(db, int(record_id), show_cost)
        if not detail:
            return {"error": "That consumption receipt was not found."}
        text = "\n".join(consumption_lines(detail, width, show_cost=show_cost))
        return {"success": True, "kind": kind, "reference": detail.get("reference") or "", "text": text, "paper": cfg.get("paper_size")}

    from backend.receipts_centre import receipt_detail
    detail = receipt_detail(db, kind, int(record_id), show_cost=show_cost)
    if not detail:
        return {"error": "That receipt could not be opened."}
    text = "\n".join(centre_lines(detail, width))
    return {"success": True, "kind": kind, "reference": detail.get("reference") or "", "text": text, "paper": cfg.get("paper_size")}


def _consumption(db, record_id: int, show_cost: bool) -> dict | None:
    row = db.execute(
        """SELECT sc.*, d.name AS department_name
           FROM stock_consumptions sc
           LEFT JOIN departments d ON d.id = sc.department_id
           WHERE sc.id=?""",
        (int(record_id),),
    ).fetchone()
    if not row:
        return None
    header = dict(row)
    items = []
    query = (
        "SELECT sci.product_name, sci.quantity, sci.unit_cost, sci.total_cost, "
        "COALESCE(NULLIF(sci.unit, ''), p.unit, 'pcs') AS unit "
        "FROM stock_consumption_items sci "
        "LEFT JOIN products p ON p.id = sci.product_id "
        "WHERE sci.consumption_id=? ORDER BY sci.id"
    )
    for item in db.execute(query, (int(record_id),)).fetchall():
        line = dict(item)
        if not show_cost:
            line.pop("unit_cost", None)
            line.pop("total_cost", None)
        items.append(line)
    if not show_cost:
        header.pop("total_cost", None)
    shop = db.execute("SELECT value FROM system_settings WHERE key='shop_name'").fetchone()
    return {
        "kind": "consumption",
        "reference": header.get("reference_no") or "",
        "shop_name": str(shop[0]).strip() if shop and shop[0] else "",
        "header": header,
        "lines": items,
    }


def submit(db, kind: str, record_id, actor: dict, *, reprint: bool = False) -> dict:
    """Hand one saved receipt to the configured printer."""
    before = _counts(db)
    rendered = render_text(db, kind, record_id, actor)
    if rendered.get("error"):
        return rendered
    reference = str(rendered.get("reference") or kind)
    with _LOCK:
        previous = _RECENT.get(reference)
    if previous and time.time() - previous[0] < 1.5 and not reprint:
        outcome = dict(previous[1])
        outcome["duplicate"] = True
        outcome["message"] = "This receipt was just sent. Wait a moment before printing it again."
        return outcome
    from printing.printer_engine import print_document_bytes
    from printing.sale_documents import load_settings
    cfg = load_settings(db)
    outcome = print_document_bytes(
        cfg,
        _bytes(rendered.get("text") or "", reference),
        label=reference,
        text=rendered.get("text") or "",
        unavailable="The receipt is saved. The printer is not available. Turn it on and print again.",
    )
    after = _counts(db)
    outcome["unchanged"] = before == after
    outcome["reference"] = reference
    outcome["kind"] = rendered.get("kind")
    if not outcome.get("unchanged"):
        logger.error("Printing changed saved records for %s", reference)
        outcome["error"] = "Printing was stopped because it would have changed the saved receipt."
    _record(db, reference, outcome.get("status") or ("submitted" if outcome.get("printed") else "failed"), outcome.get("reason") or outcome.get("message") or "")
    if outcome.get("printed"):
        with _LOCK:
            _RECENT[reference] = (time.time(), dict(outcome))
    return outcome


def _bytes(text: str, reference: str) -> bytes:
    from printing.printer_engine import text_to_escpos
    return text_to_escpos(text, reference=reference)
