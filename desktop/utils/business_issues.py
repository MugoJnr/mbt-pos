"""Business Health & Issues Centre.

One registry shared by the till and the web dashboard. A scan records
conditions that the shop can already store. It does not block a sale, invent
a buying price, or add a business module the till does not have.

Rules that are easy to get wrong stay in shadow mode: they are stored for
review and are not shown as confirmed problems.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta

SEVERITY_RANK = {"info": 0, "attention": 1, "important": 2, "critical": 3}

# needs: which existing permission may see the issue.
# cost issues stay off the cashier screen. Cashiers do not see buying prices.
RULES = (
    {
        "code": "INV-NO-BUYING-PRICE",
        "category": "inventory",
        "severity": "attention",
        "needs": "cost",
        "mode": "active",
        "description": "An active product has no buying price above zero.",
        "disableable": True,
    },
    {
        "code": "INV-NEGATIVE-COST",
        "category": "inventory",
        "severity": "important",
        "needs": "cost",
        "mode": "active",
        "description": "A product card stores a negative buying price.",
        "disableable": True,
    },
    {
        "code": "INV-SELL-BELOW-COST",
        "category": "inventory",
        "severity": "attention",
        "needs": "cost",
        "mode": "active",
        "description": "The shelf price is below the known buying price.",
        "disableable": True,
    },
    {
        "code": "INV-LOW-MARGIN",
        "category": "inventory",
        "severity": "info",
        "needs": "cost",
        "mode": "shadow",
        "description": "The shelf margin is under five percent. Many real prices are tight, so this stays in shadow.",
        "disableable": True,
    },
    {
        "code": "INV-NEGATIVE-STOCK",
        "category": "inventory",
        "severity": "important",
        "needs": "stock",
        "mode": "active",
        "description": "Recorded stock is below zero.",
        "disableable": True,
    },
    {
        "code": "INV-LAYER-GAP",
        "category": "inventory",
        "severity": "attention",
        "needs": "cost",
        "mode": "shadow",
        "description": "On-hand quantity and remaining cost layers differ. A stocktake can cause this, so it is not shown as confirmed.",
        "disableable": True,
    },
    {
        "code": "SALE-UNCOSTED",
        "category": "sales",
        "severity": "attention",
        "needs": "cost",
        "mode": "active",
        "description": "A completed sale still has units with no recorded cost.",
        "disableable": True,
    },
    {
        "code": "SALE-PAY-SHORT",
        "category": "sales",
        "severity": "important",
        "needs": "sales",
        "mode": "active",
        "description": "A completed cash sale was saved below its total and has no debt invoice.",
        "disableable": True,
    },
    {
        "code": "SALE-MPESA-DUP",
        "category": "sales",
        "severity": "attention",
        "needs": "sales",
        "mode": "active",
        "description": "The same typed M-Pesa code is on more than one receipt. A typed code is not a Safaricom confirmation.",
        "disableable": True,
    },
    {
        "code": "DEBT-BALANCE",
        "category": "debt",
        "severity": "important",
        "needs": "debt",
        "mode": "active",
        "description": "A debt invoice balance does not equal the total minus the amount paid.",
        "disableable": True,
    },
    {
        "code": "ACCT-UNBALANCED",
        "category": "accounting",
        "severity": "critical",
        "needs": "accounting",
        "mode": "active",
        "description": "A posted journal does not balance.",
        "disableable": False,
    },
    {
        "code": "CONSUME-BAD-QTY",
        "category": "consumption",
        "severity": "important",
        "needs": "stock",
        "mode": "active",
        "description": "A consumption line was saved with a quantity that is not above zero.",
        "disableable": True,
    },
    {
        "code": "STOCKTAKE-LEFT-OPEN",
        "category": "inventory",
        "severity": "attention",
        "needs": "stock",
        "mode": "active",
        "description": "A stock count has stayed open for more than two days.",
        "disableable": True,
    },
    {
        "code": "DELIVERY-BAD-QTY",
        "category": "purchasing",
        "severity": "important",
        "needs": "stock",
        "mode": "active",
        "description": "A supplier delivery line has a quantity that is not above zero.",
        "disableable": True,
    },
    {
        "code": "DELIVERY-DUP-REF",
        "category": "purchasing",
        "severity": "attention",
        "needs": "stock",
        "mode": "active",
        "description": "The same supplier reference is on more than one delivery.",
        "disableable": True,
    },
    {
        "code": "SYNC-WAITING",
        "category": "sync",
        "severity": "attention",
        "needs": "admin",
        "mode": "active",
        "description": "Items have been waiting to sync for more than a day. An offline shop is not treated as a critical failure.",
        "disableable": True,
    },
)

_BY_CODE = {rule["code"]: rule for rule in RULES}


def registry() -> list:
    return [dict(rule) for rule in RULES]


def ensure_issue_tables(db) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS business_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT NOT NULL UNIQUE,
            rule_code TEXT NOT NULL,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            explanation TEXT NOT NULL,
            entity_type TEXT,
            entity_id TEXT,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            evidence_hash TEXT NOT NULL DEFAULT '',
            destination_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'open',
            mode TEXT NOT NULL DEFAULT 'active',
            first_detected TEXT NOT NULL,
            last_detected TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT,
            resolution TEXT,
            snooze_until TEXT,
            dismiss_reason TEXT,
            updated_at TEXT NOT NULL
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_business_issues_status ON business_issues(status, severity)"
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS business_issue_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            actor TEXT,
            note TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS business_issue_rules (
            code TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            updated_by TEXT,
            updated_at TEXT NOT NULL
        )"""
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _tables(db) -> set:
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(db, table: str) -> set:
    try:
        return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def rule_mode(db, code: str) -> str:
    row = db.execute(
        "SELECT mode FROM business_issue_rules WHERE code=?", (code,)
    ).fetchone()
    if row and row[0] in ("active", "shadow", "disabled"):
        return row[0]
    return _BY_CODE[code]["mode"]


def set_rule_mode(db, code: str, mode: str, actor: str) -> dict:
    if code not in _BY_CODE:
        return {"error": "That issue rule does not exist.", "status": 404}
    if mode not in ("active", "shadow", "disabled"):
        return {"error": "Choose active, shadow, or disabled.", "status": 400}
    if mode == "disabled" and not _BY_CODE[code]["disableable"]:
        return {"error": "This integrity check cannot be switched off.", "status": 403}
    ensure_issue_tables(db)
    db.execute(
        """INSERT INTO business_issue_rules (code, mode, updated_by, updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT(code) DO UPDATE SET mode=excluded.mode,
             updated_by=excluded.updated_by, updated_at=excluded.updated_at""",
        (code, mode, actor, _now()),
    )
    db.commit()
    return {"success": True, "code": code, "mode": mode}


def _hash(evidence: dict) -> str:
    raw = json.dumps(evidence, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _detect(db) -> tuple[list, set]:
    """Return detections and the rule codes that actually ran."""
    tables = _tables(db)
    found = []
    ran = set()

    def accept(code, *, title, explanation, entity_type, entity_id, evidence, destination):
        if rule_mode(db, code) == "disabled":
            return
        rule = _BY_CODE[code]
        found.append({
            "rule_code": code,
            "category": rule["category"],
            "severity": rule["severity"],
            "mode": rule_mode(db, code),
            "title": title,
            "explanation": explanation,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "evidence": evidence,
            "destination": destination,
        })
        ran.add(code)

    if "products" in tables:
        rows = db.execute(
            """SELECT id, name, sku, price, cost_price, stock, unit
               FROM products WHERE COALESCE(is_active,1)=1"""
        ).fetchall()
        for row in rows:
            name = row["name"] if isinstance(row, sqlite3.Row) else row[1]
            pid = row["id"] if isinstance(row, sqlite3.Row) else row[0]
            sku = row["sku"] if isinstance(row, sqlite3.Row) else row[2]
            price = float((row["price"] if isinstance(row, sqlite3.Row) else row[3]) or 0)
            cost_raw = row["cost_price"] if isinstance(row, sqlite3.Row) else row[4]
            stock = float((row["stock"] if isinstance(row, sqlite3.Row) else row[5]) or 0)
            unit = (row["unit"] if isinstance(row, sqlite3.Row) else row[6]) or ""
            dest = {"web": "/inventory", "desktop": "inventory", "product_id": int(pid)}
            evidence_base = {"product_id": int(pid), "name": name, "sku": sku or ""}
            if cost_raw is None or float(cost_raw) <= 0:
                if cost_raw is not None and float(cost_raw) < 0:
                    accept(
                        "INV-NEGATIVE-COST",
                        title=f"{name} has a negative buying price",
                        explanation="The product card stores a buying price below zero. That cannot be a cost.",
                        entity_type="product", entity_id=pid,
                        evidence={**evidence_base, "cost_price": float(cost_raw)},
                        destination=dest,
                    )
                else:
                    accept(
                        "INV-NO-BUYING-PRICE",
                        title=f"{name} has no buying price",
                        explanation="This product can still be sold. Profit for those units stays incomplete until a real buying price is saved. Zero is not treated as a cost.",
                        entity_type="product", entity_id=pid,
                        evidence=evidence_base,
                        destination=dest,
                    )
            else:
                cost = float(cost_raw)
                if price > 0 and price < cost:
                    accept(
                        "INV-SELL-BELOW-COST",
                        title=f"{name} is priced below its buying price",
                        explanation="The shelf price is lower than the buying price on the product card. A till discount on one sale is separate from this. Review the card if this price is not intentional.",
                        entity_type="product", entity_id=pid,
                        evidence={**evidence_base, "price": price, "cost_price": cost},
                        destination=dest,
                    )
                elif price > cost and price > 0 and (price - cost) / price < 0.05:
                    accept(
                        "INV-LOW-MARGIN",
                        title=f"{name} has a very small margin",
                        explanation="The card margin is under five percent. This is recorded for review and is not shown as a confirmed problem.",
                        entity_type="product", entity_id=pid,
                        evidence={**evidence_base, "price": price, "cost_price": cost},
                        destination=dest,
                    )
            if stock < -0.0001:
                accept(
                    "INV-NEGATIVE-STOCK",
                    title=f"{name} has negative stock",
                    explanation=f"Stock is {stock:g} {unit}. Selling is not blocked by this warning. A super admin corrects stock with Adjust Stock.",
                    entity_type="product", entity_id=pid,
                    evidence={**evidence_base, "stock": stock, "unit": unit},
                    destination=dest,
                )
        for code in ("INV-NO-BUYING-PRICE", "INV-NEGATIVE-COST", "INV-SELL-BELOW-COST", "INV-LOW-MARGIN", "INV-NEGATIVE-STOCK"):
            if rule_mode(db, code) != "disabled":
                ran.add(code)

    if "products" in tables and "cost_layers" in tables:
        rows = db.execute(
            """SELECT p.id, p.name, p.stock, COALESCE(SUM(l.remaining_qty),0) AS layered
               FROM products p
               JOIN cost_layers l ON l.product_id=p.id
               WHERE COALESCE(p.is_active,1)=1
               GROUP BY p.id
               HAVING ABS(p.stock - layered) > 0.05"""
        ).fetchall()
        for row in rows:
            pid = row["id"] if isinstance(row, sqlite3.Row) else row[0]
            name = row["name"] if isinstance(row, sqlite3.Row) else row[1]
            stock = float(row["stock"] if isinstance(row, sqlite3.Row) else row[2])
            layered = float(row["layered"] if isinstance(row, sqlite3.Row) else row[3])
            accept(
                "INV-LAYER-GAP",
                title=f"{name} stock and cost layers differ",
                explanation="The quantity on hand and the remaining cost layers are not the same. This is kept in shadow because a stock count can change quantity without rewriting layers.",
                entity_type="product", entity_id=pid,
                evidence={"product_id": int(pid), "name": name, "stock": stock, "layered": layered},
                destination={"web": "/inventory", "desktop": "inventory", "product_id": int(pid)},
            )
        if rule_mode(db, "INV-LAYER-GAP") != "disabled":
            ran.add("INV-LAYER-GAP")

    if {"sales", "sale_items", "cost_layer_uses"} <= tables:
        rows = db.execute(
            """SELECT s.id, s.receipt_number, si.product_id, si.product_name, si.quantity,
                      COALESCE((
                        SELECT SUM(u.quantity) FROM cost_layer_uses u
                        WHERE u.sale_id=si.sale_id AND u.product_id=si.product_id
                          AND COALESCE(u.reversed,0)=0
                      ), 0) AS covered
               FROM sale_items si
               JOIN sales s ON s.id=si.sale_id
               WHERE s.status='completed' AND si.quantity > 0
                 AND date(COALESCE(NULLIF(s.sale_date,''), s.created_at)) >= date('now','-90 days')"""
        ).fetchall()
        grouped = {}
        for row in rows:
            qty = float(row["quantity"] if isinstance(row, sqlite3.Row) else row[4])
            covered = float(row["covered"] if isinstance(row, sqlite3.Row) else row[5])
            if covered + 0.001 >= qty:
                continue
            sid = int(row["id"] if isinstance(row, sqlite3.Row) else row[0])
            bucket = grouped.setdefault(sid, {
                "receipt": row["receipt_number"] if isinstance(row, sqlite3.Row) else row[1],
                "lines": 0,
                "uncovered": 0.0,
            })
            bucket["lines"] += 1
            bucket["uncovered"] = round(bucket["uncovered"] + (qty - covered), 4)
        for sid, bucket in grouped.items():
            accept(
                "SALE-UNCOSTED",
                title=f"Receipt {bucket['receipt']} has uncosted units",
                explanation="The sale is complete. Units without a buying cost are left out of profit. They are not treated as free.",
                entity_type="sale", entity_id=sid,
                evidence=bucket,
                destination={"web": "/receipts", "desktop": "sales", "sale_id": sid},
            )
        if rule_mode(db, "SALE-UNCOSTED") != "disabled":
            ran.add("SALE-UNCOSTED")

    if "sales" in tables:
        debt_ids = set()
        if "debt_invoices" in tables:
            debt_ids = {
                int(row[0]) for row in db.execute(
                    "SELECT sale_id FROM debt_invoices WHERE sale_id IS NOT NULL"
                ) if row[0] is not None
            }
        rows = db.execute(
            """SELECT id, receipt_number, total, amount_paid, payment_method
               FROM sales WHERE status='completed'
                 AND date(COALESCE(NULLIF(sale_date,''), created_at)) >= date('now','-90 days')"""
        ).fetchall()
        for row in rows:
            sid = int(row["id"] if isinstance(row, sqlite3.Row) else row[0])
            if sid in debt_ids:
                continue
            method = str((row["payment_method"] if isinstance(row, sqlite3.Row) else row[4]) or "").lower()
            if method in ("credit", "debt", "on account"):
                continue
            total = float((row["total"] if isinstance(row, sqlite3.Row) else row[2]) or 0)
            paid = float((row["amount_paid"] if isinstance(row, sqlite3.Row) else row[3]) or 0)
            if paid + 0.05 < total:
                receipt = row["receipt_number"] if isinstance(row, sqlite3.Row) else row[1]
                accept(
                    "SALE-PAY-SHORT",
                    title=f"Receipt {receipt} is short of its total",
                    explanation="The amount paid is below the receipt total and there is no debt invoice for this sale.",
                    entity_type="sale", entity_id=sid,
                    evidence={"receipt": receipt, "total": total, "amount_paid": paid, "payment_method": method},
                    destination={"web": "/receipts", "desktop": "sales", "sale_id": sid},
                )
        cols = _columns(db, "sales")
        if "mpesa_ref" in cols:
            refs = db.execute(
                """SELECT lower(trim(mpesa_ref)) AS ref, COUNT(*) AS n,
                          GROUP_CONCAT(receipt_number) AS receipts
                   FROM sales
                   WHERE status='completed' AND trim(COALESCE(mpesa_ref,'')) != ''
                   GROUP BY lower(trim(mpesa_ref))
                   HAVING n > 1
                   LIMIT 50"""
            ).fetchall()
            for row in refs:
                ref = row["ref"] if isinstance(row, sqlite3.Row) else row[0]
                receipts = row["receipts"] if isinstance(row, sqlite3.Row) else row[2]
                accept(
                    "SALE-MPESA-DUP",
                    title="The same M-Pesa code is on more than one receipt",
                    explanation="The code was typed on the till. This does not mean Safaricom has confirmed or rejected it.",
                    entity_type="mpesa_ref", entity_id=ref,
                    evidence={"mpesa_ref": ref, "receipts": receipts},
                    destination={"web": "/receipts", "desktop": "sales"},
                )
        if rule_mode(db, "SALE-PAY-SHORT") != "disabled":
            ran.add("SALE-PAY-SHORT")
        if rule_mode(db, "SALE-MPESA-DUP") != "disabled":
            ran.add("SALE-MPESA-DUP")

    if "debt_invoices" in tables:
        rows = db.execute(
            """SELECT id, invoice_number, customer_name, total_amount, amount_paid, balance, status
               FROM debt_invoices
               WHERE lower(COALESCE(status,'')) NOT IN ('cancelled','void','voided')"""
        ).fetchall()
        for row in rows:
            total = float((row["total_amount"] if isinstance(row, sqlite3.Row) else row[3]) or 0)
            paid = float((row["amount_paid"] if isinstance(row, sqlite3.Row) else row[4]) or 0)
            balance = float((row["balance"] if isinstance(row, sqlite3.Row) else row[5]) or 0)
            if abs(balance - (total - paid)) > 0.02:
                iid = int(row["id"] if isinstance(row, sqlite3.Row) else row[0])
                number = row["invoice_number"] if isinstance(row, sqlite3.Row) else row[1]
                accept(
                    "DEBT-BALANCE",
                    title=f"Debt {number} does not reconcile",
                    explanation="The balance on the invoice is not the total minus the amount paid.",
                    entity_type="debt_invoice", entity_id=iid,
                    evidence={
                        "invoice": number,
                        "customer": row["customer_name"] if isinstance(row, sqlite3.Row) else row[2],
                        "total": total, "paid": paid, "balance": balance,
                    },
                    destination={"web": "/debt", "desktop": "debt", "invoice_id": iid},
                )
        if rule_mode(db, "DEBT-BALANCE") != "disabled":
            ran.add("DEBT-BALANCE")

    if {"journal_entries", "journal_lines"} <= tables:
        rows = db.execute(
            """SELECT e.id, e.entry_number,
                      COALESCE(SUM(l.debit),0) AS total_debit,
                      COALESCE(SUM(l.credit),0) AS total_credit
               FROM journal_entries e
               LEFT JOIN journal_lines l ON l.journal_id=e.id
               WHERE e.status='posted' AND e.deleted_at IS NULL
               GROUP BY e.id
               HAVING ABS(COALESCE(SUM(l.debit),0) - COALESCE(SUM(l.credit),0)) > 0.02
               LIMIT 100"""
        ).fetchall()
        for row in rows:
            eid = int(row["id"] if isinstance(row, sqlite3.Row) else row[0])
            number = row["entry_number"] if isinstance(row, sqlite3.Row) else row[1]
            debit = float(row["total_debit"] if isinstance(row, sqlite3.Row) else row[2])
            credit = float(row["total_credit"] if isinstance(row, sqlite3.Row) else row[3])
            accept(
                "ACCT-UNBALANCED",
                title=f"Journal {number} does not balance",
                explanation="Posted debits and credits differ. Correct this with the existing journal reversal or adjustment. Do not edit the posted rows by hand.",
                entity_type="journal", entity_id=eid,
                evidence={"entry": number, "debit": round(debit, 2), "credit": round(credit, 2)},
                destination={"web": "/finance", "desktop": "accounting", "journal_id": eid},
            )
        if rule_mode(db, "ACCT-UNBALANCED") != "disabled":
            ran.add("ACCT-UNBALANCED")

    if {"stock_consumptions", "stock_consumption_items"} <= tables:
        rows = db.execute(
            """SELECT i.id, h.reference_no, i.product_name, i.quantity
               FROM stock_consumption_items i
               JOIN stock_consumptions h ON h.id=i.consumption_id
               WHERE COALESCE(h.voided,0)=0 AND i.quantity <= 0"""
        ).fetchall()
        for row in rows:
            iid = int(row["id"] if isinstance(row, sqlite3.Row) else row[0])
            ref = row["reference_no"] if isinstance(row, sqlite3.Row) else row[1]
            name = row["product_name"] if isinstance(row, sqlite3.Row) else row[2]
            qty = row["quantity"] if isinstance(row, sqlite3.Row) else row[3]
            accept(
                "CONSUME-BAD-QTY",
                title=f"Consumption {ref} has a quantity that is not usable",
                explanation=f"{name} was saved with quantity {qty}. A real consumption is above zero.",
                entity_type="consumption_item", entity_id=iid,
                evidence={"reference": ref, "product": name, "quantity": qty},
                destination={"web": "/consumption", "desktop": "consumption"},
            )
        if rule_mode(db, "CONSUME-BAD-QTY") != "disabled":
            ran.add("CONSUME-BAD-QTY")

    if "stocktakes" in tables:
        cutoff = (datetime.now() - timedelta(days=2)).isoformat(timespec="seconds")
        rows = db.execute(
            """SELECT id, name, created_at FROM stocktakes
               WHERE status='open' AND created_at < ?""",
            (cutoff,),
        ).fetchall()
        for row in rows:
            sid = int(row["id"] if isinstance(row, sqlite3.Row) else row[0])
            name = row["name"] if isinstance(row, sqlite3.Row) else row[1]
            accept(
                "STOCKTAKE-LEFT-OPEN",
                title=f"Stock count {name or sid} is still open",
                explanation="The count was started more than two days ago and has not been applied. Opening this screen does not resolve it.",
                entity_type="stocktake", entity_id=sid,
                evidence={"name": name, "created_at": row["created_at"] if isinstance(row, sqlite3.Row) else row[2]},
                destination={"web": "/inventory", "desktop": "inventory"},
            )
        if rule_mode(db, "STOCKTAKE-LEFT-OPEN") != "disabled":
            ran.add("STOCKTAKE-LEFT-OPEN")

    if "stock_receipt_lines" in tables:
        rows = db.execute(
            """SELECT l.id, r.receipt_number, l.product_name, l.quantity
               FROM stock_receipt_lines l
               JOIN stock_receipts r ON r.id=l.receipt_id
               WHERE l.quantity <= 0"""
        ).fetchall()
        for row in rows:
            lid = int(row["id"] if isinstance(row, sqlite3.Row) else row[0])
            receipt = row["receipt_number"] if isinstance(row, sqlite3.Row) else row[1]
            accept(
                "DELIVERY-BAD-QTY",
                title=f"Delivery {receipt} has a line quantity that is not usable",
                explanation="A delivery line was saved at zero or below. Stock should increase by the quantity that arrived.",
                entity_type="delivery_line", entity_id=lid,
                evidence={"receipt": receipt, "product": row["product_name"] if isinstance(row, sqlite3.Row) else row[2],
                          "quantity": row["quantity"] if isinstance(row, sqlite3.Row) else row[3]},
                destination={"web": "/inventory", "desktop": "inventory"},
            )
        if rule_mode(db, "DELIVERY-BAD-QTY") != "disabled":
            ran.add("DELIVERY-BAD-QTY")
        if "reference_note" in _columns(db, "stock_receipts"):
            refs = db.execute(
                """SELECT lower(trim(reference_note)) AS ref, COUNT(*) AS n,
                          GROUP_CONCAT(receipt_number) AS receipts
                   FROM stock_receipts
                   WHERE trim(COALESCE(reference_note,'')) != ''
                   GROUP BY lower(trim(reference_note))
                   HAVING n > 1
                   LIMIT 50"""
            ).fetchall()
            for row in refs:
                ref = row["ref"] if isinstance(row, sqlite3.Row) else row[0]
                accept(
                    "DELIVERY-DUP-REF",
                    title="The same supplier reference is on more than one delivery",
                    explanation="Two deliveries share a reference. Check that the goods were not received twice.",
                    entity_type="delivery_ref", entity_id=ref,
                    evidence={"reference": ref, "receipts": row["receipts"] if isinstance(row, sqlite3.Row) else row[2]},
                    destination={"web": "/inventory", "desktop": "inventory"},
                )
            if rule_mode(db, "DELIVERY-DUP-REF") != "disabled":
                ran.add("DELIVERY-DUP-REF")

    if "sync_queue" in tables:
        row = db.execute(
            """SELECT COUNT(*), MIN(created_at) FROM sync_queue
               WHERE status='pending' AND created_at < datetime('now','-1 day')"""
        ).fetchone()
        waiting = int(row[0] or 0)
        if waiting:
            accept(
                "SYNC-WAITING",
                title=f"{waiting} item(s) have been waiting to sync",
                explanation="The till can keep selling offline. This is attention, not a critical fault, until the items have waited more than a day.",
                entity_type="sync", entity_id="queue",
                evidence={"waiting": waiting, "oldest": row[1]},
                destination={"web": "/health", "desktop": "settings"},
            )
        if rule_mode(db, "SYNC-WAITING") != "disabled":
            ran.add("SYNC-WAITING")

    return found, ran


def _event(db, issue_id: int, action: str, actor: str, note: str = "") -> None:
    db.execute(
        """INSERT INTO business_issue_events (issue_id, action, actor, note, created_at)
           VALUES (?,?,?,?,?)""",
        (issue_id, action, actor, note, _now()),
    )


def scan(db, actor: str = "system") -> dict:
    """Detect, deduplicate, and auto-resolve. Safe to run more than once."""
    ensure_issue_tables(db)
    found, ran = _detect(db)
    now = _now()
    seen = set()
    opened = 0
    updated = 0
    for item in found:
        evidence_hash = _hash(item["evidence"])
        fingerprint = f"{item['rule_code']}:{item['entity_type']}:{item['entity_id']}"
        seen.add(fingerprint)
        current = db.execute(
            "SELECT * FROM business_issues WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        payload = (
            item["rule_code"], item["category"], item["severity"], item["title"],
            item["explanation"], item["entity_type"], str(item["entity_id"]),
            json.dumps(item["evidence"], default=str), evidence_hash,
            json.dumps(item["destination"], default=str), item["mode"],
        )
        if current is None:
            cur = db.execute(
                """INSERT INTO business_issues (
                    fingerprint, rule_code, category, severity, title, explanation,
                    entity_type, entity_id, evidence_json, evidence_hash, destination_json,
                    status, mode, first_detected, last_detected, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,'open',?,?,?,?)""",
                (fingerprint, *payload, now, now, now),
            )
            _event(db, cur.lastrowid, "detected", actor, item["title"])
            opened += 1
            continue
        status = current["status"]
        issue_id = current["id"]
        same = current["evidence_hash"] == evidence_hash
        if status == "dismissed" and same:
            db.execute(
                "UPDATE business_issues SET last_detected=?, updated_at=?, mode=? WHERE id=?",
                (now, now, item["mode"], issue_id),
            )
        elif status == "snoozed" and (current["snooze_until"] or "") > now and same:
            db.execute(
                "UPDATE business_issues SET last_detected=?, updated_at=?, mode=? WHERE id=?",
                (now, now, item["mode"], issue_id),
            )
        elif status == "open" and same:
            db.execute(
                "UPDATE business_issues SET last_detected=?, updated_at=?, mode=? WHERE id=?",
                (now, now, item["mode"], issue_id),
            )
            updated += 1
        else:
            db.execute(
                """UPDATE business_issues
                   SET rule_code=?, category=?, severity=?, title=?, explanation=?,
                       entity_type=?, entity_id=?, evidence_json=?, evidence_hash=?,
                       destination_json=?, status='open', mode=?, last_detected=?,
                       resolved_at=NULL, resolved_by=NULL, resolution=NULL,
                       snooze_until=NULL, updated_at=?
                   WHERE id=?""",
                (*payload, now, now, issue_id),
            )
            _event(db, issue_id, "reopened" if status != "open" else "updated", actor, item["title"])
            if status != "open":
                opened += 1
            else:
                updated += 1
    resolved = 0
    if ran:
        placeholders = ",".join("?" for _ in ran)
        stale = db.execute(
            f"""SELECT id, title FROM business_issues
                WHERE status IN ('open','snoozed','dismissed') AND rule_code IN ({placeholders})""",
            tuple(ran),
        ).fetchall()
        for row in stale:
            fingerprint_row = db.execute(
                "SELECT fingerprint, snooze_until, status FROM business_issues WHERE id=?",
                (row["id"],),
            ).fetchone()
            if fingerprint_row["fingerprint"] in seen:
                continue
            if fingerprint_row["status"] == "snoozed" and (fingerprint_row["snooze_until"] or "") > now:
                continue
            db.execute(
                """UPDATE business_issues
                   SET status='resolved', resolved_at=?, resolved_by='system',
                       resolution='The condition is no longer present.', updated_at=?
                   WHERE id=?""",
                (now, now, row["id"]),
            )
            _event(db, row["id"], "auto_resolved", "system", row["title"])
            resolved += 1
    db.commit()
    return {"success": True, "opened": opened, "updated": updated, "resolved": resolved, "detected": len(found)}


def _user_role(user: dict) -> str:
    nested = user.get("user") if isinstance(user.get("user"), dict) else None
    return str((nested or user).get("role") or "cashier").lower()


def can_see(user: dict, needs: str) -> bool:
    from desktop.utils.security import has_permission, sees_product_cost
    role = _user_role(user)
    if needs == "cost":
        return sees_product_cost(user)
    if needs == "accounting":
        return has_permission(user, "accounting.view")
    if needs == "debt":
        return has_permission(user, "debt.view")
    if needs == "sales":
        return has_permission(user, "sales.view_all")
    if needs == "admin":
        return role in ("admin", "superadmin")
    return has_permission(user, "inventory.view")


def can_manage(user: dict, severity: str) -> bool:
    role = _user_role(user)
    if severity == "critical":
        return role == "superadmin"
    if severity == "important":
        return role in ("admin", "superadmin")
    if severity == "attention":
        return role in ("manager", "admin", "superadmin")
    return role in ("manager", "admin", "superadmin")


def _public(row) -> dict:
    return {
        "id": row["id"],
        "rule_code": row["rule_code"],
        "category": row["category"],
        "severity": row["severity"],
        "title": row["title"],
        "explanation": row["explanation"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "evidence": json.loads(row["evidence_json"] or "{}"),
        "destination": json.loads(row["destination_json"] or "{}"),
        "status": row["status"],
        "mode": row["mode"],
        "first_detected": row["first_detected"],
        "last_detected": row["last_detected"],
        "resolved_at": row["resolved_at"],
        "resolved_by": row["resolved_by"],
        "resolution": row["resolution"],
        "snooze_until": row["snooze_until"],
        "dismiss_reason": row["dismiss_reason"],
    }


def list_issues(db, user: dict, status: str = "open", include_shadow: bool = False) -> list:
    ensure_issue_tables(db)
    if status == "all":
        rows = db.execute(
            "SELECT * FROM business_issues ORDER BY last_detected DESC LIMIT 400"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM business_issues WHERE status=? ORDER BY last_detected DESC LIMIT 400",
            (status,),
        ).fetchall()
    visible = []
    for row in rows:
        rule = _BY_CODE.get(row["rule_code"])
        if rule is None or not can_see(user, rule["needs"]):
            continue
        live_mode = rule_mode(db, row["rule_code"])
        if live_mode == "disabled":
            continue
        if live_mode == "shadow" and not (include_shadow and _user_role(user) == "superadmin"):
            continue
        item = _public(row)
        item["mode"] = live_mode
        visible.append(item)
    visible.sort(key=lambda item: (-SEVERITY_RANK.get(item["severity"], 0), item["title"]))
    return visible


def summary(db, user: dict) -> dict:
    counts = {"info": 0, "attention": 0, "important": 0, "critical": 0, "open": 0}
    for item in list_issues(db, user, "open"):
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1
        counts["open"] += 1
    return counts


def issue_events(db, issue_id: int) -> list:
    rows = db.execute(
        """SELECT action, actor, note, created_at FROM business_issue_events
           WHERE issue_id=? ORDER BY id""",
        (issue_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _load_visible(db, user, issue_id: int):
    row = db.execute("SELECT * FROM business_issues WHERE id=?", (issue_id,)).fetchone()
    if row is None:
        return None, {"error": "That issue was not found.", "status": 404}
    rule = _BY_CODE.get(row["rule_code"])
    if rule is None or not can_see(user, rule["needs"]):
        return None, {"error": "You cannot view this issue.", "status": 403}
    return row, None


def dismiss_issue(db, user: dict, issue_id: int, reason: str) -> dict:
    reason = (reason or "").strip()
    if len(reason) < 3:
        return {"error": "Enter a reason before dismissing an issue.", "status": 400}
    row, error = _load_visible(db, user, issue_id)
    if error:
        return error
    if row["severity"] == "critical":
        return {"error": "A critical integrity issue cannot be dismissed.", "status": 403}
    if not can_manage(user, row["severity"]):
        return {"error": "You cannot dismiss this issue.", "status": 403}
    if row["status"] != "open":
        return {"error": "Only an open issue can be dismissed.", "status": 409}
    actor = _user_role(user)
    name = str(user.get("username") or user.get("full_name") or actor)
    now = _now()
    db.execute(
        """UPDATE business_issues
           SET status='dismissed', dismiss_reason=?, resolved_by=?, updated_at=?
           WHERE id=?""",
        (reason, name, now, issue_id),
    )
    _event(db, issue_id, "dismissed", name, reason)
    db.commit()
    return {"success": True, "status": "dismissed"}


def snooze_issue(db, user: dict, issue_id: int, days: int, reason: str) -> dict:
    reason = (reason or "").strip()
    if len(reason) < 3:
        return {"error": "Enter a reason before snoozing an issue.", "status": 400}
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 0
    if days < 1 or days > 7:
        return {"error": "Snooze for 1 to 7 days.", "status": 400}
    row, error = _load_visible(db, user, issue_id)
    if error:
        return error
    if row["severity"] == "critical":
        return {"error": "A critical integrity issue cannot be snoozed.", "status": 403}
    if not can_manage(user, row["severity"]):
        return {"error": "You cannot snooze this issue.", "status": 403}
    if row["status"] != "open":
        return {"error": "Only an open issue can be snoozed.", "status": 409}
    name = str(user.get("username") or user.get("full_name") or _user_role(user))
    until = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
    now = _now()
    db.execute(
        """UPDATE business_issues SET status='snoozed', snooze_until=?, updated_at=? WHERE id=?""",
        (until, now, issue_id),
    )
    _event(db, issue_id, "snoozed", name, f"{days} day(s). {reason}")
    db.commit()
    return {"success": True, "status": "snoozed", "snooze_until": until}
