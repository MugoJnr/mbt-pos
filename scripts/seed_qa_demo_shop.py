#!/usr/bin/env python3
"""
Seed an isolated QA demo shop for screenshot / Claude system gates.

Does NOT touch production AppData (`%LOCALAPPDATA%\\MugoByte\\MBT POS`).
Writes to `%LOCALAPPDATA%\\MugoByte\\MBT POS QA` (or MBT_QA_DATA_ROOT).

Usage:
  python scripts/seed_qa_demo_shop.py              # copy+enrich if needed
  python scripts/seed_qa_demo_shop.py --reset      # wipe QA, re-copy, enrich
  python scripts/seed_qa_demo_shop.py --enrich-only

Then capture with:
  set MBT_DATA_ROOT=%LOCALAPPDATA%\\MugoByte\\MBT POS QA
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SEED_VERSION = "qa-demo-v3"
DEMO_TAG = "[QA Demo]"

PROD_ROOT = Path(os.environ.get("LOCALAPPDATA", "")) / "MugoByte" / "MBT POS"
QA_ROOT = Path(
    os.environ.get("MBT_QA_DATA_ROOT")
    or (Path(os.environ.get("LOCALAPPDATA", "")) / "MugoByte" / "MBT POS QA")
)


def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def _copy_prod_to_qa(reset: bool) -> Path:
    qa = QA_ROOT
    if reset and qa.exists():
        shutil.rmtree(qa, ignore_errors=True)
    qa.mkdir(parents=True, exist_ok=True)
    for sub in ("data", "config", "exports", "backups", "logs"):
        (qa / sub).mkdir(parents=True, exist_ok=True)

    src_db = PROD_ROOT / "data" / "mbt_pos.db"
    dst_db = qa / "data" / "mbt_pos.db"
    if not dst_db.exists() or reset:
        if not src_db.exists():
            raise SystemExit(f"Production DB missing: {src_db}")
        # Prefer clean copy without WAL siblings if possible
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(src_db) + suffix) if suffix else src_db
            if p.exists():
                shutil.copy2(p, Path(str(dst_db) + suffix) if suffix else dst_db)
        print(f"COPIED db -> {dst_db}", flush=True)
    else:
        print(f"KEEP existing QA db {dst_db}", flush=True)

    # Copy non-secret-looking config that helps the app boot (skip secrets if absent)
    src_cfg = PROD_ROOT / "config"
    dst_cfg = qa / "config"
    if src_cfg.is_dir():
        for name in (
            "web_config.json",
            "category_visual_prefs.json",
            "audio_settings.json",
            "ai_copilot_prefs.json",
        ):
            s = src_cfg / name
            d = dst_cfg / name
            if s.is_file() and (reset or not d.exists()):
                shutil.copy2(s, d)
    return qa


def _conn(db_path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
    except sqlite3.OperationalError:
        pass
    return c


def _set_setting(c: sqlite3.Connection, key: str, value: str) -> None:
    c.execute(
        "INSERT INTO system_settings (key, value, updated_at) VALUES (?,?,?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, datetime.now().isoformat()),
    )


def _already_seeded(c: sqlite3.Connection) -> bool:
    row = c.execute(
        "SELECT value FROM system_settings WHERE key='qa_demo_seed_version'"
    ).fetchone()
    return bool(row and row[0] == SEED_VERSION)


def _seed_shop_identity(c: sqlite3.Connection) -> None:
    _set_setting(c, "shop_name", "Green Valley Agro")
    _set_setting(c, "shop_address", "Nakuru–Eldoret Rd, Nakuru")
    _set_setting(c, "shop_phone", "+254 712 555 210")
    _set_setting(c, "shop_email", "greenvalley@qa.mugobyte.local")
    _set_setting(c, "currency_symbol", "KES")
    _set_setting(c, "currency_code", "KES")
    _set_setting(c, "receipt_footer", "Asante · Green Valley Agro · QA Demo Shop")
    _set_setting(c, "mpesa_business_name", "Green Valley Agro")
    _set_setting(c, "mpesa_till_number", "584721")


def _seed_notes(c: sqlite3.Connection) -> int:
    # Remove empty Untitled placeholders
    c.execute(
        "DELETE FROM notes WHERE (title IS NULL OR trim(title)='' OR title='Untitled')"
        " AND (content IS NULL OR trim(content)='')"
    )
    existing = {
        (r[0] or "").strip().lower()
        for r in c.execute("SELECT title FROM notes").fetchall()
    }
    notes = [
        (
            "Opening checklist — Thu",
            "Float counted KES 5,000.\nTills unlocked · scale zeroed.\nDelivery bay clear for Yara truck 10:30.",
            1,
        ),
        (
            "Supplier follow-up — Yara",
            "Chase 50kg DAP short-delivery from Tuesday.\nContact: Wanjiku 0722… · PO-GV-441.",
            1,
        ),
        (
            "Handoff — James → Grace",
            "Register 1: M-Pesa float OK.\nPending credit collect: Kamau Feeds KES 4,800.\nDo not sell expired ACTELLIC lot A-19.",
            0,
        ),
        (
            "Closing — stock variances",
            "Urea 50kg: −2 bags (shrink).\n24D Max: count matches.\nTomorrow: receive foliar spray 20L.",
            0,
        ),
        (
            "Credit policy reminder",
            "New credit > KES 10,000 needs manager PIN.\nOverdue > 14 days: no further credit until collect.",
            0,
        ),
        (
            "Promo board — weekend",
            "DAP 50kg: KES 50 off cash.\nBundle: CAN + foliar 1L.\nAnnounce on Live Dashboard banner.",
            0,
        ),
        (
            "Staff rota",
            "Fri: Grace + Amina\nSat: James + Peter\nSun: closed (inventory count).",
            0,
        ),
        (
            "Repair log — scale",
            "Counter scale drifts +40g. Calibrate Friday AM before open.\nTemp workaround: use floor scale for >5kg.",
            0,
        ),
    ]
    n = 0
    uid = c.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    uid = uid[0] if uid else 1
    base = datetime.now()
    for i, (title, content, pinned) in enumerate(notes):
        if title.lower() in existing:
            continue
        ts = (base - timedelta(hours=3 * i)).isoformat(timespec="seconds")
        c.execute(
            "INSERT INTO notes (user_id, title, content, pinned, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            (uid, title, content, pinned, ts, ts),
        )
        n += 1
    return n


def _seed_users(c: sqlite3.Connection) -> int:
    from roles import default_tab_permissions

    staff = [
        ("grace", "Grace Wanjiru", "manager", "Grace@qa1"),
        ("james", "James Otieno", "cashier", "James@qa1"),
        ("amina", "Amina Hassan", "cashier", "Amina@qa1"),
        ("peter", "Peter Mwangi", "cashier", "Peter@qa1"),
        ("lucy", "Lucy Njeri", "admin", "Lucy@qa1"),
    ]
    added = 0
    for username, full_name, role, pw in staff:
        exists = c.execute(
            "SELECT id FROM users WHERE lower(username)=lower(?)", (username,)
        ).fetchone()
        if exists:
            continue
        perms = json.dumps(default_tab_permissions(role))
        c.execute(
            "INSERT INTO users (username, password_hash, role, full_name, email,"
            " tab_permissions, is_active)"
            " VALUES (?,?,?,?,?,?,1)",
            (username, _hash_pw(pw), role, full_name, f"{username}@qa.local", perms),
        )
        added += 1
    return added


def _seed_customers_debt(c: sqlite3.Connection) -> dict:
    """Rename QA stubs + ensure a professional debt book."""
    renames = {
        "Credit Smoke": "Kamau Feeds Ltd",
        "QA Cust 28030": "Njeri Dairy Farm",
        "QA Credit Cust 13234": "Otieno Horticulture",
        "QA Cust 31973": "Kipchoge Grain Co-op",
        "Smoke NameOnly 1784331699": "Baraka Hardware",
        "Smoke NamePhone 1784331718": "Soko Fresh Produce",
        "Smoke2 NameOnly 1784331788": "Lake Basin Feeds",
        "Smoke2 NamePhone 1784331801": "Highlands Vet Supply",
    }
    for old, new in renames.items():
        c.execute(
            "UPDATE customers SET name=?, notes=? WHERE name=?",
            (new, f"{DEMO_TAG} renamed from {old}", old),
        )
        c.execute(
            "UPDATE debt_invoices SET customer_name=? WHERE customer_name=?",
            (new, old),
        )
        c.execute(
            "UPDATE debt_payments SET cashier_name=cashier_name WHERE customer_id IN "
            "(SELECT id FROM customers WHERE name=?)",
            (new,),
        )

    roster = [
        ("Wanjiku Agro Traders", "0712345601", 25000),
        ("Rift Valley Poultry", "0723456702", 18000),
        ("Mugo Hardware Credit", "0734567803", 12000),
        ("Chebet Vegetables", "0745678904", 6500),
        ("Kiprop Maize Mill", "0756789005", 9200),
        ("Achieng Fish Farm", "0767890106", 4800),
    ]
    created = 0
    for name, phone, limit in roster:
        row = c.execute(
            "SELECT id FROM customers WHERE lower(name)=lower(?)", (name,)
        ).fetchone()
        if row:
            continue
        cols = {r[1] for r in c.execute("PRAGMA table_info(customers)").fetchall()}
        if "customer_type" in cols and "national_id" in cols:
            c.execute(
                "INSERT INTO customers (name,phone,credit_limit,notes,customer_type,national_id)"
                " VALUES (?,?,?,?,?,?)",
                (name, phone, limit, DEMO_TAG, "Wholesale", ""),
            )
        else:
            c.execute(
                "INSERT INTO customers (name,phone,credit_limit,notes) VALUES (?,?,?,?)",
                (name, phone, limit, DEMO_TAG),
            )
        created += 1

    # Ensure open invoices with realistic balances (idempotent via invoice_number prefix)
    products = c.execute(
        "SELECT id, name, sku, price, stock FROM products"
        " WHERE is_active=1 AND price>0 ORDER BY stock DESC LIMIT 40"
    ).fetchall()
    if not products:
        return {"customers_added": created, "invoices": 0}

    custs = c.execute(
        "SELECT id, name, phone FROM customers WHERE is_active=1 ORDER BY id"
    ).fetchall()
    inv_n = 0
    rng = random.Random(42)
    today = date.today()
    for i, cust in enumerate(custs[:8]):
        inv_no = f"INV-QA-{today.strftime('%Y%m%d')}-{i+1:03d}"
        exists = c.execute(
            "SELECT id FROM debt_invoices WHERE invoice_number=?", (inv_no,)
        ).fetchone()
        if exists:
            continue
        # Create a linked completed sale first
        prod = products[i % len(products)]
        qty = rng.choice([1, 2, 3, 5])
        unit = float(prod["price"] or 0)
        total = round(unit * qty, 2)
        if total < 500:
            total = round(total + 2500, 2)
        paid = round(total * rng.choice([0.0, 0.2, 0.35]), 2)
        balance = round(total - paid, 2)
        rn = f"RCP-QA-{today.strftime('%Y%m%d')}-{i+1:04d}"
        sale_ts = (datetime.now() - timedelta(days=rng.randint(1, 12))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        c.execute(
            "INSERT INTO sales (receipt_number,cashier_id,cashier_name,subtotal,discount,tax,"
            "total,payment_method,amount_paid,change_amount,notes,status,created_at)"
            " VALUES (?,?,?,?,0,0,?,?,?,?,?,?,?)",
            (
                rn,
                1,
                "grace",
                total,
                total,
                "credit",
                paid,
                0,
                DEMO_TAG,
                "completed",
                sale_ts,
            ),
        )
        sale_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute(
            "INSERT INTO sale_items (sale_id,product_id,product_name,sku,quantity,"
            "unit_price,discount,total) VALUES (?,?,?,?,?,?,0,?)",
            (sale_id, prod["id"], prod["name"], prod["sku"] or "", qty, unit, total),
        )
        due = (today + timedelta(days=rng.choice([7, 14, 21]))).isoformat()
        status = "partial" if paid > 0 else "pending"
        c.execute(
            "INSERT INTO debt_invoices (invoice_number,sale_id,receipt_number,customer_id,"
            "customer_name,customer_phone,total_amount,amount_paid,balance,status,due_date,"
            "cashier_id,cashier_name,notes,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                inv_no,
                sale_id,
                rn,
                cust["id"],
                cust["name"],
                cust["phone"] or "",
                total,
                paid,
                balance,
                status,
                due,
                1,
                "grace",
                DEMO_TAG,
                sale_ts,
                sale_ts,
            ),
        )
        inv_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        if paid > 0:
            pay_no = f"PAY-QA-{today.strftime('%Y%m%d')}-{i+1:04d}"
            c.execute(
                "INSERT INTO debt_payments (payment_receipt,invoice_id,customer_id,amount,"
                "payment_method,balance_before,balance_after,cashier_id,cashier_name,notes,"
                "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    pay_no,
                    inv_id,
                    cust["id"],
                    paid,
                    rng.choice(["cash", "mpesa"]),
                    total,
                    balance,
                    1,
                    "james",
                    DEMO_TAG,
                    (datetime.now() - timedelta(days=rng.randint(0, 3))).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                ),
            )
        inv_n += 1
    return {"customers_added": created, "invoices": inv_n}


def _seed_week_sales(c: sqlite3.Connection) -> int:
    """Dense last-7-days sales for dashboard/reports charts (no stock mutation)."""
    products = c.execute(
        "SELECT id, name, sku, price FROM products"
        " WHERE is_active=1 AND COALESCE(price,0)>10 ORDER BY RANDOM() LIMIT 80"
    ).fetchall()
    if not products:
        return 0
    methods = [
        ("cash", 0.28),
        ("mpesa", 0.32),
        ("card", 0.12),
        ("bank", 0.08),
        ("airtel", 0.10),
        ("mixed", 0.10),
    ]
    rng = random.Random(7)
    cashiers = ["admin", "grace", "james", "amina", "peter"]
    inserted = 0
    today = date.today()
    for day_offset in range(6, -1, -1):
        d = today - timedelta(days=day_offset)
        # Skip if this day already has dense QA sales
        existing = c.execute(
            "SELECT COUNT(*) FROM sales WHERE date(created_at)=? AND notes LIKE ?",
            (d.isoformat(), f"%{DEMO_TAG}%"),
        ).fetchone()[0]
        if existing >= 8:
            continue
        n_sales = 10 + (day_offset % 5)  # 10–14 per day
        for s_i in range(n_sales):
            rn = f"RCP-WK-{d.strftime('%Y%m%d')}-{s_i+1:03d}"
            if c.execute(
                "SELECT 1 FROM sales WHERE receipt_number=?", (rn,)
            ).fetchone():
                continue
            n_items = rng.randint(1, 3)
            items = [rng.choice(products) for _ in range(n_items)]
            lines = []
            subtotal = 0.0
            for prod in items:
                qty = rng.choice([1, 1, 2, 3])
                unit = float(prod["price"])
                # mild weekend uplift
                if d.weekday() >= 5:
                    unit *= 1.05
                line = round(unit * qty, 2)
                subtotal += line
                lines.append((prod, qty, unit, line))
            disc = round(subtotal * rng.choice([0.0, 0.0, 0.0, 0.05]), 2)
            total = round(subtotal - disc, 2)
            method = rng.choices(
                [m[0] for m in methods], weights=[m[1] for m in methods], k=1
            )[0]
            hour = rng.randint(8, 18)
            minute = rng.randint(0, 59)
            ts = f"{d.isoformat()} {hour:02d}:{minute:02d}:{rng.randint(0,59):02d}"
            cashier = rng.choice(cashiers)
            c.execute(
                "INSERT INTO sales (receipt_number,cashier_id,cashier_name,subtotal,"
                "discount,tax,total,payment_method,amount_paid,change_amount,notes,"
                "status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rn,
                    1,
                    cashier,
                    subtotal,
                    disc,
                    0,
                    total,
                    method,
                    total,
                    0,
                    DEMO_TAG,
                    "completed",
                    ts,
                ),
            )
            sale_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            for prod, qty, unit, line in lines:
                c.execute(
                    "INSERT INTO sale_items (sale_id,product_id,product_name,sku,"
                    "quantity,unit_price,discount,total) VALUES (?,?,?,?,?,?,0,?)",
                    (
                        sale_id,
                        prod["id"],
                        prod["name"],
                        prod["sku"] or "",
                        qty,
                        unit,
                        line,
                    ),
                )
            inserted += 1
    return inserted


def _seed_expenses(c: sqlite3.Connection) -> int:
    from desktop.utils.accounting_engine import (
        ensure_accounting_schema,
        seed_chart_of_accounts,
        create_expense,
    )

    ensure_accounting_schema(c)
    seed_chart_of_accounts(c)
    expenses = [
        (0, 3500, "6000", "Shop electricity — July"),
        (1, 1200, "6400", "Boda delivery — foliar stock"),
        (2, 800, "6000", "Cleaning supplies"),
        (3, 4500, "6400", "Lorry hire — fertilizer drop"),
        (4, 600, "6900", "Mobile airtime float"),
        (5, 2200, "6000", "Security guard week"),
        (6, 1500, "6600", "Misc packaging bags"),
    ]
    n = 0
    today = date.today()
    for days_ago, amount, code, desc in expenses:
        ed = (today - timedelta(days=days_ago)).isoformat()
        full_desc = f"{DEMO_TAG} {desc}"
        exists = c.execute(
            "SELECT id FROM expense_entries WHERE description=? AND expense_date=?",
            (full_desc, ed),
        ).fetchone()
        if exists:
            continue
        r = create_expense(
            c,
            {
                "amount": amount,
                "account_code": code,
                "pay_from_code": "1000",
                "expense_date": ed,
                "description": full_desc,
                "vendor_name": "QA Vendor",
            },
            user_id=1,
            username="admin",
        )
        if r.get("success"):
            n += 1
    return n


def enrich(db_path: Path, force: bool = False) -> dict:
    c = _conn(db_path)
    try:
        if _already_seeded(c) and not force:
            print(f"ALREADY seeded {SEED_VERSION}", flush=True)
            return {"skipped": True, "version": SEED_VERSION}
        _seed_shop_identity(c)
        stats = {
            "notes": _seed_notes(c),
            "users": _seed_users(c),
            "debt": _seed_customers_debt(c),
            "sales": _seed_week_sales(c),
            "expenses": _seed_expenses(c),
        }
        _set_setting(c, "qa_demo_seed_version", SEED_VERSION)
        _set_setting(c, "qa_demo_seed_at", datetime.now().isoformat())
        c.commit()
        marker = QA_ROOT / "data" / "QA_DEMO_SEED.json"
        marker.write_text(
            json.dumps(
                {
                    "version": SEED_VERSION,
                    "tag": DEMO_TAG,
                    "stats": stats,
                    "db": str(db_path),
                    "note": "Isolated QA profile — production AppData untouched.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(json.dumps({"ok": True, **stats}, indent=2), flush=True)
        return stats
    finally:
        c.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--enrich-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="Re-run enrich even if version matches")
    args = ap.parse_args()

    if not args.enrich_only:
        _copy_prod_to_qa(reset=args.reset)
    db = QA_ROOT / "data" / "mbt_pos.db"
    if not db.exists():
        raise SystemExit(f"QA DB missing: {db}")
    enrich(db, force=args.force or args.reset)
    print(f"QA_ROOT={QA_ROOT}", flush=True)
    print("Set MBT_DATA_ROOT to this path before capture/gate.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
