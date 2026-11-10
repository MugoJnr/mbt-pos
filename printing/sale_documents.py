"""Receipts and invoices for a sale that is already saved.

One shop setting chooses the document. The till and the web portal both read
system_settings. Printing never creates a sale, a payment, or a second number.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

PRINTER_UNAVAILABLE = (
    "Sale saved successfully. Printer unavailable. "
    "You can view, download or print the document later."
)

POLICY_CHOICES = (
    ("A", "Always receipt",
     "Every sale is a receipt. A receipt is evidence of payment received."),
    ("B", "Always invoice",
     "Every sale is an invoice, including a sale that is fully paid."),
    ("C", "Automatic by payment status",
     "A fully paid sale is a receipt. A partially paid sale is an invoice. An unpaid credit sale is an invoice."),
    ("D", "Invoice for credit sales",
     "Credit and part-paid sales are invoices showing the original amount, amount paid, payment breakdown, outstanding balance, customer, and due date when one is set. Other sales follow the automatic rule."),
    ("E", "Cashier chooses",
     "The cashier chooses a receipt or an invoice on each sale."),
    ("F", "Automatic, with override",
     "The till chooses automatically. An authorised cashier can change that choice."),
)

DOCUMENT_DEFAULTS = {
    "document_policy": "C",
    "printer_name": "",
    "printer_connection": "USB",
    "printer_host": "",
    "paper_size": "80",
    "print_customer_copy": "1",
    "print_duplicate_copy": "0",
    "show_document_preview": "0",
    "allow_cashier_doc_override": "0",
    "allow_reprint": "1",
}


def policy_text(code: str) -> str:
    wanted = (code or "C").strip().upper()[:1]
    for key, _label, text in POLICY_CHOICES:
        if key == wanted:
            return text
    return POLICY_CHOICES[2][2]


def payment_standing(total, amount_paid) -> str:
    gross = round(float(total or 0), 2)
    paid = round(float(amount_paid or 0), 2)
    if paid + 0.009 >= gross:
        return "paid"
    if paid > 0.009:
        return "partial"
    return "unpaid"


def resolve_document_kind(policy: str, standing: str, choice: str = "") -> str:
    """Pick receipt or invoice. A non-empty choice is already authorised."""
    picked = (choice or "").strip().lower()
    if picked in ("receipt", "invoice"):
        return picked
    code = (policy or "C").strip().upper()[:1]
    credit = standing in ("partial", "unpaid")
    if code == "A":
        return "receipt"
    if code == "B":
        return "invoice"
    if code == "D":
        return "invoice" if credit else "receipt"
    return "invoice" if credit else "receipt"


def honor_choice(cfg: dict, choice: str, *, can_edit_settings: bool, can_sell: bool) -> str:
    picked = (choice or "").strip().lower()
    if picked not in ("receipt", "invoice"):
        return ""
    if can_edit_settings:
        return picked
    if not can_sell:
        return ""
    policy = str((cfg or {}).get("document_policy") or "C").strip().upper()[:1]
    allow = str((cfg or {}).get("allow_cashier_doc_override") or "0") == "1"
    if policy in ("E", "F") or allow:
        return picked
    return ""


def override_allowed(cfg: dict, *, can_edit_settings: bool, can_sell: bool) -> bool:
    if can_edit_settings:
        return True
    if not can_sell:
        return False
    policy = str((cfg or {}).get("document_policy") or "C").strip().upper()[:1]
    allow = str((cfg or {}).get("allow_cashier_doc_override") or "0") == "1"
    return policy in ("E", "F") or allow


def load_settings(db) -> dict:
    cfg = dict(DOCUMENT_DEFAULTS)
    try:
        rows = db.execute("SELECT key, value FROM system_settings").fetchall()
    except Exception:
        rows = []
    for row in rows:
        if hasattr(row, "keys"):
            cfg[row["key"]] = row["value"]
        else:
            cfg[row[0]] = row[1]
    cfg["allow_reprint"] = "1"
    size = str(cfg.get("paper_size") or "80")
    cfg["paper_size"] = "58" if size.strip() in ("58", "58mm") else "80"
    connection = str(cfg.get("printer_connection") or "USB").strip()
    if connection.upper() == "WINDOWS":
        cfg["printer_connection"] = "Windows"
    elif connection.upper() == "LAN":
        cfg["printer_connection"] = "LAN"
    else:
        cfg["printer_connection"] = "USB"
    policy = str(cfg.get("document_policy") or "C").strip().upper()[:1]
    cfg["document_policy"] = policy if policy in "ABCDEF" else "C"
    return cfg


def paper_columns(cfg: dict) -> int:
    return 32 if str((cfg or {}).get("paper_size") or "80") == "58" else 48


def ensure_document_columns(db) -> None:
    cols = {row[1] for row in db.execute("PRAGMA table_info(sales)").fetchall()}
    if "issued_document_kind" not in cols:
        db.execute("ALTER TABLE sales ADD COLUMN issued_document_kind TEXT")
    if "issued_document_number" not in cols:
        db.execute("ALTER TABLE sales ADD COLUMN issued_document_number TEXT")


def _row(db, sql, params=()):
    found = db.execute(sql, params).fetchone()
    if not found:
        return {}
    return dict(found) if hasattr(found, "keys") else {}


def _rows(db, sql, params=()):
    return [dict(row) if hasattr(row, "keys") else {} for row in db.execute(sql, params).fetchall()]


def stamp_sale_document(db, sale_id: int, choice: str = "", *,
                        can_edit_settings: bool = False, can_sell: bool = True,
                        commit: bool = True) -> dict:
    """Freeze the document type once. Later setting changes do not rewrite it."""
    ensure_document_columns(db)
    sale = _row(db, "SELECT * FROM sales WHERE id=?", (int(sale_id),))
    if not sale:
        return {"error": "Sale not found"}
    existing = (sale.get("issued_document_kind") or "").strip().lower()
    number = (sale.get("issued_document_number") or sale.get("receipt_number") or "").strip()
    if existing in ("receipt", "invoice"):
        return {
            "success": True,
            "frozen": True,
            "kind": existing,
            "number": number or sale.get("receipt_number") or "",
            "receipt_number": sale.get("receipt_number") or "",
        }
    cfg = load_settings(db)
    debt = _debt_for_sale(db, sale["id"])
    paid = float(debt.get("amount_paid") if debt else sale.get("amount_paid") or 0)
    total = float(debt.get("total_amount") if debt else sale.get("total") or 0)
    standing = payment_standing(total, paid)
    honored = honor_choice(
        cfg, choice, can_edit_settings=can_edit_settings, can_sell=can_sell,
    )
    kind = resolve_document_kind(cfg.get("document_policy") or "C", standing, honored)
    number = sale.get("receipt_number") or ""
    if kind == "invoice" and debt.get("invoice_number"):
        number = debt["invoice_number"]
    db.execute(
        "UPDATE sales SET issued_document_kind=?, issued_document_number=? "
        "WHERE id=? AND (issued_document_kind IS NULL OR issued_document_kind='')",
        (kind, number, int(sale_id)),
    )
    if commit:
        db.commit()
    return {
        "success": True,
        "frozen": False,
        "kind": kind,
        "number": number,
        "receipt_number": sale.get("receipt_number") or "",
    }


def _debt_for_sale(db, sale_id: int) -> dict:
    return _row(
        db,
        "SELECT * FROM debt_invoices WHERE sale_id=? AND status!='cancelled' "
        "ORDER BY id DESC LIMIT 1",
        (int(sale_id),),
    )


def _customer(db, sale: dict, debt: dict) -> dict:
    name = (sale.get("customer_name") or debt.get("customer_name") or "").strip()
    phone = (sale.get("customer_phone") or debt.get("customer_phone") or "").strip()
    if sale.get("customer_id") and (not name or not phone):
        cust = _row(db, "SELECT name, phone, email FROM customers WHERE id=?", (sale["customer_id"],))
        name = name or (cust.get("name") or "")
        phone = phone or (cust.get("phone") or "")
    return {"name": name, "phone": phone}


def _money(value) -> float:
    return round(float(value or 0), 2)


def _breakdown(db, sale: dict, debt: dict) -> list:
    raw = sale.get("payment_tenders")
    tenders = raw
    if isinstance(raw, str) and raw.strip():
        import json
        try:
            tenders = json.loads(raw)
        except Exception:
            tenders = []
    lines = []
    if isinstance(tenders, list):
        for row in tenders:
            if not isinstance(row, dict):
                continue
            amount = _money(row.get("amount"))
            if amount <= 0:
                continue
            status = str(row.get("status") or "confirmed")
            if status == "outstanding":
                continue
            lines.append({
                "method": str(row.get("method") or "Payment"),
                "amount": amount,
                "status": status,
                "reference": "",
            })
    if not lines:
        electronic = _money(sale.get("electronic_paid"))
        cash = _money(sale.get("cash_paid"))
        if electronic > 0.009:
            lines.append({
                "method": str(sale.get("electronic_method") or "Electronic"),
                "amount": electronic,
                "status": "confirmed",
                "reference": str(sale.get("mpesa_ref") or ""),
            })
        if cash > 0.009:
            lines.append({
                "method": "Cash",
                "amount": cash,
                "status": "confirmed",
                "reference": "",
            })
        if not lines and _money(sale.get("amount_paid")) > 0.009:
            lines.append({
                "method": str(sale.get("payment_method") or "Cash"),
                "amount": _money(sale.get("amount_paid")),
                "status": "confirmed",
                "reference": str(sale.get("mpesa_ref") or ""),
            })
    if debt.get("id"):
        payments = _rows(
            db,
            "SELECT payment_receipt, amount, payment_method, notes, created_at "
            "FROM debt_payments WHERE invoice_id=? ORDER BY id",
            (debt["id"],),
        )
        for pay in payments:
            notes = str(pay.get("notes") or "")
            if notes.startswith("Initial payment"):
                continue
            lines.append({
                "method": str(pay.get("payment_method") or "Cash"),
                "amount": _money(pay.get("amount")),
                "status": "confirmed",
                "reference": str(pay.get("payment_receipt") or ""),
                "later_payment": True,
            })
    outstanding = _outstanding(sale, debt)
    if outstanding > 0.009 and not any(row.get("status") == "outstanding" for row in lines):
        lines.append({
            "method": "Credit",
            "amount": outstanding,
            "status": "outstanding",
            "reference": "",
        })
    return lines


def _outstanding(sale: dict, debt: dict) -> float:
    if debt:
        return max(0.0, _money(debt.get("balance")))
    return max(0.0, round(_money(sale.get("total")) - _money(sale.get("amount_paid")), 2))


def _paid_amount(sale: dict, debt: dict) -> float:
    if debt:
        return _money(debt.get("amount_paid"))
    return _money(sale.get("amount_paid"))


def _status_label(standing: str) -> str:
    if standing == "paid":
        return "Paid"
    if standing == "partial":
        return "Partially paid"
    return "Unpaid"


def _fit(left: str, right: str, width: int) -> str:
    left = str(left or "")
    right = str(right or "")
    gap = width - len(left) - len(right)
    if gap < 1:
        return (left + " " + right)[:width]
    return left + (" " * gap) + right


def _render_lines(doc: dict, width: int) -> list:
    lines = []
    if doc.get("voided"):
        lines.append(center("VOIDED", width))
    if doc.get("reprint"):
        lines.append(center("REPRINT", width))
    if doc.get("duplicate"):
        lines.append(center("DUPLICATE", width))
    lines.append("=" * width)
    lines.append(center(doc["business"].get("name") or "Shop", width))
    for bit in (doc["business"].get("address"), doc["business"].get("phone"), doc["business"].get("email")):
        if bit:
            lines.append(center(str(bit), width))
    if doc.get("logo"):
        lines.append(center("[logo]", width))
    lines.append(center(doc["title"], width))
    lines.append("=" * width)
    lines.append(_fit("Number:", doc.get("number") or "", width))
    if doc.get("receipt_number") and doc.get("receipt_number") != doc.get("number"):
        lines.append(_fit("Sale:", doc["receipt_number"], width))
    if doc.get("invoice_number") and doc.get("invoice_number") not in (doc.get("number"), doc.get("receipt_number")):
        lines.append(_fit("Invoice:", doc["invoice_number"], width))
    lines.append(_fit("Date:", str(doc.get("when") or "")[:19], width))
    if doc.get("cashier"):
        lines.append(_fit("Cashier:", doc["cashier"], width))
    customer = doc.get("customer") or {}
    if customer.get("name"):
        lines.append(_fit("Customer:", customer["name"], width))
    if customer.get("phone"):
        lines.append(_fit("Contact:", customer["phone"], width))
    if doc.get("due_date"):
        lines.append(_fit("Due:", str(doc["due_date"]), width))
    lines.append("-" * width)
    if doc.get("items"):
        for item in doc["items"]:
            name = str(item.get("product_name") or "")
            qty = item.get("quantity")
            qty_text = f"{qty:g}" if isinstance(qty, float) and qty != int(qty) else str(qty)
            amount = f"{_money(item.get('total')):,.2f}"
            lines.append(_fit(f"{qty_text} {name}"[:width - len(amount) - 1], amount, width))
            price = _money(item.get("unit_price"))
            if price:
                lines.append(f"  @ {price:,.2f}")
            if _money(item.get("discount")) > 0:
                lines.append(f"  Discount -{_money(item.get('discount')):,.2f}")
        lines.append("-" * width)
    if _money(doc.get("discount")) > 0:
        lines.append(_fit("Discount:", f"-{_money(doc.get('discount')):,.2f}", width))
    if doc.get("show_tax"):
        lines.append(_fit("Tax:", f"{_money(doc.get('tax')):,.2f}", width))
    lines.append(_fit("Total:", f"{_money(doc.get('total')):,.2f}", width))
    lines.append(_fit("Amount paid:", f"{_money(doc.get('amount_paid')):,.2f}", width))
    for row in doc.get("breakdown") or []:
        label = str(row.get("method") or "Payment")
        if row.get("reference"):
            label = f"{label} {row['reference']}"
        if row.get("status") == "outstanding":
            label = f"{label} outstanding"
        lines.append(_fit(label[:18], f"{_money(row.get('amount')):,.2f}", width))
    if _money(doc.get("change")) > 0:
        lines.append(_fit("Change:", f"{_money(doc.get('change')):,.2f}", width))
    lines.append(_fit("Status:", doc.get("payment_status") or "", width))
    if _money(doc.get("outstanding")) > 0.009:
        lines.append("-" * width)
        lines.append(center("BALANCE DUE", width))
        lines.append(center(f"{_money(doc.get('outstanding')):,.2f}", width))
    elif doc.get("kind") == "invoice":
        lines.append(center("PAID", width))
    if doc.get("reference"):
        lines.append(_fit("Reference:", str(doc["reference"]), width))
    lines.append("-" * width)
    lines.append(center(doc.get("footer") or "Thank you!", width))
    return lines


def center(text: str, width: int) -> str:
    text = str(text or "")
    if len(text) >= width:
        return text[:width]
    pad = (width - len(text)) // 2
    return (" " * pad) + text


def _html_doc(doc: dict) -> str:
    width = "58mm" if doc.get("paper_size") == "58" else "80mm"
    rows = []
    for item in doc.get("items") or []:
        rows.append(
            "<tr><td>{}</td><td style='text-align:right'>{}</td>"
            "<td style='text-align:right'>{}</td><td style='text-align:right'>{}</td></tr>".format(
                html.escape(str(item.get("product_name") or "")),
                html.escape(str(item.get("quantity") or "")),
                f"{_money(item.get('unit_price')):,.2f}",
                f"{_money(item.get('total')):,.2f}",
            )
        )
    pays = []
    for row in doc.get("breakdown") or []:
        note = " outstanding" if row.get("status") == "outstanding" else ""
        ref = f" {row['reference']}" if row.get("reference") else ""
        pays.append(
            f"<p>{html.escape(str(row.get('method') or ''))}{html.escape(ref)}{note} "
            f"{_money(row.get('amount')):,.2f}</p>"
        )
    banners = []
    if doc.get("voided"):
        banners.append("<h1>VOIDED</h1>")
    if doc.get("reprint"):
        banners.append("<p><strong>REPRINT</strong> · original number kept</p>")
    logo = "<img src='/api/documents/logo' alt='Logo' style='max-width:42mm;max-height:16mm' onerror='this.remove()'>" if doc.get("logo") else ""
    balance = ""
    if _money(doc.get("outstanding")) > 0.009:
        balance = (
            "<p class='balance'>Balance due "
            f"{_money(doc.get('outstanding')):,.2f}</p>"
        )
    elif doc.get("kind") == "invoice":
        balance = "<p class='paid'>PAID</p>"
    customer = doc.get("customer") or {}
    contact = " · ".join(bit for bit in (customer.get("name"), customer.get("phone")) if bit)
    business = doc.get("business") or {}
    shop = "<br>".join(
        html.escape(str(bit)) for bit in (
            business.get("address"), business.get("phone"), business.get("email"),
        ) if bit
    )
    tax = ""
    if doc.get("show_tax"):
        tax = f"<p>Tax {_money(doc.get('tax')):,.2f}</p>"
    discount = ""
    if _money(doc.get("discount")) > 0:
        discount = f"<p>Discount -{_money(doc.get('discount')):,.2f}</p>"
    change = ""
    if _money(doc.get("change")) > 0:
        change = f"<p>Change {_money(doc.get('change')):,.2f}</p>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(doc.get('number') or doc['title'])}</title>
<style>
body{{font-family:ui-sans-serif,sans-serif;width:{width};margin:12px;color:#111}}
h1{{font-size:16px;margin:0}} h2{{font-size:14px;margin:4px 0}}
table{{width:100%;border-collapse:collapse;font-size:12px}} td{{padding:2px 0;vertical-align:top}}
.balance{{font-size:18px;font-weight:800}} .paid{{font-weight:800}}
</style></head><body>
{''.join(banners)}{logo}
<h2>{html.escape(business.get('name') or 'Shop')}</h2>
<p>{shop}</p>
<h1>{html.escape(doc['title'])}</h1>
<p>{html.escape(doc.get('number') or '')}<br>{html.escape(str(doc.get('when') or '')[:19])}</p>
<p>{html.escape(contact)}</p>
<table>{''.join(rows)}</table>
{discount}{tax}
<p><strong>Total {_money(doc.get('total')):,.2f}</strong></p>
<p>Paid {_money(doc.get('amount_paid')):,.2f}</p>
{''.join(pays)}{change}
<p>Status: {html.escape(doc.get('payment_status') or '')}</p>
{balance}
<p>{html.escape(doc.get('footer') or '')}</p>
</body></html>"""


def _logo_configured() -> bool:
    try:
        from backend.report_export_service import find_logo_path
        return bool(find_logo_path())
    except Exception:
        return False


def build_sale_document(db, sale_id: int, kind: str = "", *, reprint: bool = False,
                        duplicate: bool = False, stamp_if_missing: bool = True) -> dict:
    ensure_document_columns(db)
    sale = _row(db, "SELECT * FROM sales WHERE id=?", (int(sale_id),))
    if not sale:
        return {"error": "Sale not found"}
    items = _rows(db, "SELECT * FROM sale_items WHERE sale_id=? ORDER BY id", (int(sale_id),))
    if stamp_if_missing and not (sale.get("issued_document_kind") or "").strip():
        stamp_sale_document(db, sale_id, commit=True)
        sale = _row(db, "SELECT * FROM sales WHERE id=?", (int(sale_id),))
    cfg = load_settings(db)
    debt = _debt_for_sale(db, sale_id)
    stored = (sale.get("issued_document_kind") or "").strip().lower()
    requested = (kind or "").strip().lower()
    use = requested if requested in ("receipt", "invoice") else (stored or "receipt")
    total = _money(debt.get("total_amount") if debt else sale.get("total"))
    paid = _paid_amount(sale, debt)
    outstanding = _outstanding(sale, debt)
    standing = payment_standing(total, paid)
    show_tax = _money(sale.get("tax")) > 0 and str(cfg.get("receipt_tax_enabled") or "1") != "0"
    number = (sale.get("issued_document_number") or sale.get("receipt_number") or "")
    if use == "invoice" and debt.get("invoice_number"):
        number = debt["invoice_number"]
    elif use == "receipt":
        number = sale.get("receipt_number") or number
    title = "INVOICE" if use == "invoice" else "RECEIPT"
    doc = {
        "success": True,
        "kind": use,
        "stored_kind": stored or use,
        "title": title,
        "number": number,
        "receipt_number": sale.get("receipt_number") or "",
        "invoice_number": debt.get("invoice_number") or "",
        "sale_id": int(sale_id),
        "voided": (sale.get("status") or "") == "voided",
        "reprint": bool(reprint),
        "duplicate": bool(duplicate),
        "business": {
            "name": cfg.get("shop_name") or "My Shop",
            "address": cfg.get("shop_address") or "",
            "phone": cfg.get("shop_phone") or "",
            "email": cfg.get("shop_email") or "",
        },
        "logo": _logo_configured(),
        "when": sale.get("created_at") or sale.get("sale_date") or "",
        "cashier": sale.get("cashier_name") or "",
        "customer": _customer(db, sale, debt),
        "due_date": debt.get("due_date") or "",
        "items": [{
            "product_name": item.get("product_name") or "",
            "quantity": item.get("quantity") or 0,
            "unit_price": _money(item.get("unit_price")),
            "discount": _money(item.get("discount")),
            "total": _money(item.get("total")),
        } for item in items],
        "discount": _money(sale.get("discount")),
        "tax": _money(sale.get("tax")) if show_tax else 0,
        "show_tax": show_tax,
        "total": total,
        "amount_paid": paid,
        "outstanding": outstanding,
        "change": _money(sale.get("change_amount")),
        "payment_status": _status_label(standing),
        "payment_method": sale.get("payment_method") or "",
        "breakdown": _breakdown(db, sale, debt),
        "reference": sale.get("mpesa_ref") or "",
        "footer": cfg.get("receipt_footer") or "Thank you for shopping with us!",
        "paper_size": cfg.get("paper_size") or "80",
        "policy": cfg.get("document_policy") or "C",
    }
    doc["lines"] = _render_lines(doc, paper_columns(cfg))
    doc["text"] = "\n".join(doc["lines"])
    doc["html"] = _html_doc(doc)
    return doc


def build_payment_document(db, payment_receipt: str, *, reprint: bool = False) -> dict:
    receipt = (payment_receipt or "").strip()
    if not receipt:
        return {"error": "Payment receipt is required"}
    pay = _row(db, "SELECT * FROM debt_payments WHERE payment_receipt=?", (receipt,))
    if not pay:
        return {"error": "Payment receipt not found"}
    debt = _row(db, "SELECT * FROM debt_invoices WHERE id=?", (pay["invoice_id"],))
    sale = _row(db, "SELECT * FROM sales WHERE id=?", (debt.get("sale_id") or 0,)) if debt else {}
    cfg = load_settings(db)
    customer = _customer(db, sale or {}, debt or {})
    if not customer.get("name"):
        customer["name"] = debt.get("customer_name") or ""
    doc = {
        "success": True,
        "kind": "payment_receipt",
        "title": "PAYMENT RECEIPT",
        "number": receipt,
        "receipt_number": debt.get("receipt_number") or sale.get("receipt_number") or "",
        "invoice_number": debt.get("invoice_number") or "",
        "sale_id": sale.get("id"),
        "voided": bool(pay.get("reversed")) or (sale.get("status") == "voided"),
        "reprint": bool(reprint),
        "duplicate": False,
        "not_a_sale": True,
        "business": {
            "name": cfg.get("shop_name") or "My Shop",
            "address": cfg.get("shop_address") or "",
            "phone": cfg.get("shop_phone") or "",
            "email": cfg.get("shop_email") or "",
        },
        "logo": _logo_configured(),
        "when": pay.get("created_at") or "",
        "cashier": pay.get("cashier_name") or "",
        "customer": customer,
        "due_date": "",
        "items": [],
        "discount": 0,
        "tax": 0,
        "show_tax": False,
        "total": _money(debt.get("total_amount")),
        "amount_paid": _money(pay.get("amount")),
        "previous_outstanding": _money(pay.get("balance_before")),
        "outstanding": _money(pay.get("balance_after")),
        "change": 0,
        "payment_status": "Paid" if _money(pay.get("balance_after")) <= 0.009 else "Partially paid",
        "payment_method": pay.get("payment_method") or "",
        "breakdown": [{
            "method": str(pay.get("payment_method") or "Cash"),
            "amount": _money(pay.get("amount")),
            "status": "confirmed",
            "reference": receipt,
        }],
        "reference": receipt,
        "footer": "This payment is on an existing sale. It is not a new sale.",
        "paper_size": cfg.get("paper_size") or "80",
        "policy": cfg.get("document_policy") or "C",
    }
    width = paper_columns(cfg)
    lines = []
    if doc["voided"]:
        lines.append(center("VOIDED", width))
    if reprint:
        lines.append(center("REPRINT", width))
    lines.extend([
        "=" * width,
        center(doc["business"]["name"], width),
        center("PAYMENT RECEIPT", width),
        "=" * width,
        _fit("Number:", receipt, width),
        _fit("Date:", str(doc["when"])[:19], width),
        _fit("Customer:", customer.get("name") or "", width),
        _fit("Sale:", doc["receipt_number"], width),
        _fit("Invoice:", doc["invoice_number"], width),
        _fit("Previous due:", f"{doc['previous_outstanding']:,.2f}", width),
        _fit("Received now:", f"{doc['amount_paid']:,.2f}", width),
        _fit("Method:", str(doc["payment_method"] or ""), width),
        _fit("Remaining:", f"{doc['outstanding']:,.2f}", width),
        center("Not a new sale", width),
        "-" * width,
        center(doc["footer"], width),
    ])
    doc["lines"] = lines
    doc["text"] = "\n".join(lines)
    doc["html"] = _html_doc({
        **doc,
        "items": [],
        "total": doc["previous_outstanding"],
        "amount_paid": doc["amount_paid"],
        "outstanding": doc["outstanding"],
        "payment_status": (
            f"Previous {doc['previous_outstanding']:,.2f} · "
            f"received {doc['amount_paid']:,.2f} · remaining {doc['outstanding']:,.2f}"
        ),
    })
    return doc


def change_document_kind(db, sale_id: int, kind: str, *, allowed: bool) -> dict:
    if not allowed:
        return {"error": "You cannot change the document type.", "status": 403}
    picked = (kind or "").strip().lower()
    if picked not in ("receipt", "invoice"):
        return {"error": "Choose a receipt or an invoice."}
    ensure_document_columns(db)
    before = _row(
        db,
        "SELECT id, receipt_number, total, amount_paid, status, issued_document_kind, "
        "issued_document_number FROM sales WHERE id=?",
        (int(sale_id),),
    )
    if not before:
        return {"error": "Sale not found"}
    if not (before.get("issued_document_kind") or "").strip():
        stamp_sale_document(db, sale_id, commit=True)
        before = _row(
            db,
            "SELECT id, receipt_number, total, amount_paid, status, issued_document_kind, "
            "issued_document_number FROM sales WHERE id=?",
            (int(sale_id),),
        )
    old = (before.get("issued_document_kind") or "").strip().lower()
    if old == picked:
        return {
            "success": True,
            "unchanged": True,
            "kind": picked,
            "number": before.get("issued_document_number") or before.get("receipt_number") or "",
        }
    db.execute(
        "UPDATE sales SET issued_document_kind=? WHERE id=?",
        (picked, int(sale_id)),
    )
    db.commit()
    after = _row(
        db,
        "SELECT total, amount_paid, status, issued_document_number FROM sales WHERE id=?",
        (int(sale_id),),
    )
    if (
        _money(after.get("total")) != _money(before.get("total"))
        or _money(after.get("amount_paid")) != _money(before.get("amount_paid"))
        or (after.get("status") or "") != (before.get("status") or "")
    ):
        logger.error("document kind change touched money on sale %s", sale_id)
    return {
        "success": True,
        "changed": True,
        "old_kind": old,
        "kind": picked,
        "number": before.get("issued_document_number") or before.get("receipt_number") or "",
        "sale_id": int(sale_id),
        "receipt_number": before.get("receipt_number") or "",
    }


def print_existing_sale(db, sale_id: int, *, automatic: bool = False, reprint: bool = False) -> dict:
    """Print the saved document. This never inserts a sale or a payment."""
    cfg = load_settings(db)
    if automatic and str(cfg.get("auto_print") or "1") != "1":
        return {"printed": False, "skipped": True, "sale_saved": True, "message": ""}
    customer_copy = str(cfg.get("print_customer_copy") or "1") == "1"
    duplicate = str(cfg.get("print_duplicate_copy") or "0") == "1"
    if not customer_copy and not duplicate:
        return {
            "printed": False,
            "skipped": True,
            "sale_saved": True,
            "message": "Printing is turned off. The sale is saved. You can view or download the document.",
        }
    doc = build_sale_document(db, sale_id, reprint=reprint)
    if doc.get("error"):
        return doc
    from printing.printer_engine import print_document_bytes, text_to_escpos
    blobs = []
    if customer_copy:
        blobs.append(text_to_escpos(doc["text"]))
    if duplicate:
        dup = build_sale_document(db, sale_id, reprint=reprint, duplicate=True, stamp_if_missing=False)
        blobs.append(text_to_escpos(dup.get("text") or doc["text"]))
    outcome = print_document_bytes(cfg, b"".join(blobs), label=str(doc.get("number") or sale_id))
    outcome["sale_saved"] = True
    outcome["sale_id"] = int(sale_id)
    outcome["kind"] = doc.get("kind")
    outcome["number"] = doc.get("number")
    outcome["document"] = {key: doc[key] for key in (
        "kind", "number", "receipt_number", "title", "payment_status", "total",
        "amount_paid", "outstanding",
    ) if key in doc}
    return outcome


def lines_to_pdf(lines: list, paper_size: str = "80") -> bytes:
    """A small text PDF. No external PDF library."""
    width = 164 if str(paper_size) == "58" else 226
    leading = 11
    margin = 14
    safe = [str(line).encode("latin-1", "replace").decode("latin-1") for line in (lines or [""])]
    height = max(280, margin * 2 + leading * (len(safe) + 2))
    commands = ["BT", "/F1 9 Tf"]
    y = height - margin
    first = True
    for line in safe:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if first:
            commands.append(f"1 0 0 1 {margin} {y:.2f} Tm ({escaped}) Tj")
            first = False
        else:
            commands.append(f"0 -{leading} Td ({escaped}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", "replace")
    objects = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    add(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    add(
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
        f"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>".encode()
    )
    add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n".encode())
        out.extend(body)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return bytes(out)


def document_pdf(doc: dict) -> bytes:
    return lines_to_pdf(doc.get("lines") or [], doc.get("paper_size") or "80")
