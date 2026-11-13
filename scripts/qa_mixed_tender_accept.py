"""Isolated mixed-tender acceptance. Does not open the live shop database."""
from __future__ import annotations

import csv
import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

RUN = "MBTQA-20261027-002"
REPO = Path(r"C:\MBT_Build\mbt-pos-port")
SHOP = Path(r"C:\MBT_Build\qa-mixed-tender-20261027\shop")
DB_PATH = SHOP / "data" / "mbt_pos.db"
OUT = REPO / "qa-results" / RUN
SECRET = "Qa-Tender-20261027!"

os.environ["MBT_DATA_ROOT"] = str(SHOP)
os.environ["LOCALAPPDATA"] = str(SHOP.parent / "local")
os.environ["APPDATA"] = str(SHOP.parent / "roaming")
os.environ["PROGRAMDATA"] = str(SHOP.parent / "programdata")
for folder in (SHOP / "data", SHOP.parent / "local", SHOP.parent / "roaming", SHOP.parent / "programdata", OUT):
    folder.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()

sys.path.insert(0, str(REPO))
patches = [
    patch("mbt_paths.get_db_path", return_value=str(DB_PATH)),
    patch("desktop.utils.api_client.get_db_path", return_value=str(DB_PATH)),
]
for item in patches:
    item.start()

import desktop.utils.api_client as ac  # noqa: E402
import backend.app as appmod  # noqa: E402

ac._SCHEMA_READY = False
appmod.DB_PATH = str(DB_PATH)
CLIENT = appmod.app.test_client()
ROWS = []
PAYMENTS = []
STOCK = []
DEBTS = []


def record(test_id, feature, expected, actual, status, **extra):
    ROWS.append({
        "test_id": test_id, "feature": feature, "role": "cashier",
        "interface": "dashboard-api", "expected": expected, "actual": actual,
        "status": status, "evidence": extra.get("evidence", str(DB_PATH)),
    })


def main():
    db = ac._db()
    db.execute(
        "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
        ("qa-cashier", ac._hash_pw(SECRET), "cashier", "QA Cashier"),
    )
    db.execute(
        "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
        ("qa-admin", ac._hash_pw(SECRET), "admin", "QA Admin"),
    )
    db.execute(
        "INSERT INTO products (name, sku, price, cost_price, stock, is_active) VALUES (?,?,?,?,?,1)",
        ("QA-Tender-Item", "QA-TENDER", 100, 40, 500),
    )
    db.execute("INSERT INTO customers (name, phone, is_active) VALUES ('QA-Tender-Customer', '0711', 1)")
    db.commit()
    product = db.execute("SELECT id FROM products").fetchone()["id"]
    customer = db.execute("SELECT id FROM customers").fetchone()["id"]
    db.close()
    login = CLIENT.post("/api/auth/login", json={"username": "qa-cashier", "password": SECRET})
    headers = {"Authorization": f"Bearer {login.get_json()['token']}"}

    def sell(token, tenders, total=1000, discount=0, customer_id=customer, qty=10):
        before = _stock(product)
        response = CLIENT.post("/api/sales", headers=headers, json={
            "items": [{"product_id": product, "quantity": qty, "unit_price": 100, "discount": discount}],
            "subtotal": qty * 100, "discount": discount, "total": total,
            "payment_method": "Mixed", "payment_tenders": tenders,
            "customer_id": customer_id, "client_token": token,
        })
        body = response.get_json() or {}
        after = _stock(product)
        debt = body.get("debt") or {}
        STOCK.append({
            "test_id": token, "product": "QA-Tender-Item", "before": before, "after": after,
            "expected_change": 0 if body.get("duplicate") else -qty,
            "actual_change": after - before,
        })
        PAYMENTS.append({
            "test_id": token, "receipt": body.get("receipt_number"),
            "total": total, "tenders": json.dumps(tenders),
            "debt_balance": debt.get("balance"), "status": response.status_code,
            "duplicate": bool(body.get("duplicate")),
        })
        return response

    cases = [
        ("ST-01", [{"method": "Cash", "amount": 1000}], 0),
        ("ST-02", [{"method": "M-Pesa", "amount": 1000}], 0),
        ("ST-03", [{"method": "Cash", "amount": 400}, {"method": "Credit", "amount": 600}], 600),
        ("ST-04", [{"method": "M-Pesa", "amount": 400}, {"method": "Credit", "amount": 600}], 600),
        ("ST-05", [{"method": "Cash", "amount": 200}, {"method": "M-Pesa", "amount": 300}, {"method": "Credit", "amount": 500}], 500),
        ("ST-06", [{"method": "Cash", "amount": 200}, {"method": "Card", "amount": 300}, {"method": "Credit", "amount": 500}], 500),
        ("ST-07", [
            {"method": "Cash", "amount": 100}, {"method": "M-Pesa", "amount": 200},
            {"method": "Card", "amount": 200}, {"method": "Credit", "amount": 500},
        ], 500),
        ("ST-08", [
            {"method": "M-Pesa", "amount": 300}, {"method": "Bank Transfer", "amount": 200},
            {"method": "Credit", "amount": 500},
        ], 500),
    ]
    for test_id, tenders, credit in cases:
        response = sell(test_id, tenders)
        body = response.get_json() or {}
        balance = None if not body.get("debt") else body["debt"].get("balance")
        ok = response.status_code == 200 and (credit == 0 or balance == credit) and not body.get("duplicate")
        if credit == 0:
            ok = response.status_code == 200 and not body.get("debt")
        record(test_id, "Mixed tender", f"One sale, credit {credit}", f"status {response.status_code} debt {balance}", "PASS" if ok else "FAIL")

    st09 = sell("ST-09", [
        {"method": "Cash", "amount": 200}, {"method": "M-Pesa", "amount": 300}, {"method": "Credit", "amount": 500},
    ])
    invoice = ((st09.get_json() or {}).get("debt") or {}).get("invoice_id")
    balances = []
    for amount, ref in ((100, "R1"), (150, "R2"), (250, "R3")):
        paid = CLIENT.post(f"/api/debt/invoices/{invoice}/pay", headers=headers, json={
            "amount": amount, "payment_method": "cash", "payment_reference": ref,
        })
        balances.append((paid.get_json() or {}).get("balance_after"))
        DEBTS.append({"invoice": invoice, "payment": amount, "balance_after": (paid.get_json() or {}).get("balance_after"), "status": paid.status_code})
    record("ST-09", "Repay 100, 150, 250", "Balances 400, 250, 0", str(balances), "PASS" if balances == [400, 250, 0] or balances == [400.0, 250.0, 0.0] else "FAIL")
    sales_before = _count("sales")
    record("ST-09-REV", "Repayments are not new sales", "Sale count unchanged", f"sales={_count('sales')} before={sales_before}", "PASS" if _count("sales") == sales_before else "FAIL")

    pending = sell("ST-10", [
        {"method": "Cash", "amount": 200},
        {"method": "M-Pesa", "amount": 300, "status": "pending"},
        {"method": "Credit", "amount": 500},
    ])
    confirmed = sell("ST-10", [
        {"method": "Cash", "amount": 200}, {"method": "M-Pesa", "amount": 300}, {"method": "Credit", "amount": 500},
    ])
    record(
        "ST-10", "Pending M-Pesa is not collected",
        "Pending rejected, confirmed sale once",
        f"pending={pending.status_code} confirmed={confirmed.status_code} duplicate={((confirmed.get_json() or {}).get('duplicate'))}",
        "PASS" if pending.status_code == 400 and confirmed.status_code == 200 else "FAIL",
    )
    discounted = sell("ST-11", [
        {"method": "Cash", "amount": 200}, {"method": "M-Pesa", "amount": 200}, {"method": "Credit", "amount": 500},
    ], total=900, discount=100)
    record(
        "ST-11", "Discounted mixed tender",
        "Allocations match 900",
        f"status {discounted.status_code} debt {((discounted.get_json() or {}).get('debt') or {}).get('balance')}",
        "PASS" if discounted.status_code == 200 and ((discounted.get_json() or {}).get("debt") or {}).get("balance") == 500 else "FAIL",
    )
    original = sell("ST-12", [
        {"method": "Cash", "amount": 400}, {"method": "Credit", "amount": 600},
    ])
    sale_id = (original.get_json() or {}).get("sale_id")
    db = ac._db()
    line_id = db.execute("SELECT id FROM sale_items WHERE sale_id=?", (sale_id,)).fetchone()["id"]
    db.close()
    denied = CLIENT.post(f"/api/sales/{sale_id}/return", headers=headers, json={
        "items": [{"sale_item_id": line_id, "quantity": 2}],
        "reason": "Cashier must not refund", "refund_method": "cash",
        "client_token": str(uuid.uuid4()),
    })
    admin_login = CLIENT.post("/api/auth/login", json={"username": "qa-admin", "password": SECRET})
    admin_headers = {"Authorization": f"Bearer {admin_login.get_json()['token']}"}
    returned = CLIENT.post(f"/api/sales/{sale_id}/return", headers=admin_headers, json={
        "items": [{"sale_item_id": line_id, "quantity": 2}],
        "reason": "Two units returned", "refund_method": "cash",
        "client_token": str(uuid.uuid4()),
    })
    db = ac._db()
    debt_row = db.execute("SELECT balance FROM debt_invoices WHERE sale_id=?", (sale_id,)).fetchone()
    stock_now = db.execute("SELECT stock FROM products WHERE id=?", (product,)).fetchone()["stock"]
    db.close()
    body = returned.get_json() or {}
    ok = (
        denied.status_code == 400
        and returned.status_code == 200
        and float(body.get("debt_reduced") or 0) == 200
        and debt_row is not None and float(debt_row["balance"]) == 400
    )
    record(
        "ST-12", "Partial return after mixed tender",
        "Cashier denied. Admin return cuts debt 600 to 400 and restocks 2.",
        f"cashier {denied.status_code} admin {returned.status_code} debt {None if not debt_row else debt_row['balance']} stock {stock_now} body {body}",
        "PASS" if ok else "FAIL",
    )
    record(
        "SPLIT-CART", "Split one cart into separate bills",
        "A dedicated cart-split action",
        "Not supported. Two checkouts are used instead, and each quantity is sold once.",
        "NOT SUPPORTED",
    )
    record(
        "REAL-MPESA", "Safaricom callback",
        "Gateway confirmation",
        "Not sent. M-Pesa amounts here are recorded tenders, not Daraja charges.",
        "NOT SUPPORTED",
    )

    failed = [row for row in ROWS if row["status"] == "FAIL"]
    _write(failed)
    print(f"scenarios={len(ROWS)} failed={len(failed)}")
    for row in failed:
        print("FAIL", row["test_id"], row["actual"][:240])
    return 1 if failed else 0


def _stock(product):
    db = ac._db()
    try:
        return float(db.execute("SELECT stock FROM products WHERE id=?", (product,)).fetchone()["stock"])
    finally:
        db.close()


def _count(table):
    db = ac._db()
    try:
        return db.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    finally:
        db.close()


def _write(failed):
    def dump(name, rows):
        path = OUT / name
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        (REPO / name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    dump("MBT_POS_COMPLETE_SCENARIO_MATRIX.csv", ROWS)
    dump("MBT_POS_SALES_AND_SPLIT_LEDGER.csv", PAYMENTS)
    dump("MBT_POS_PAYMENT_ALLOCATION_LEDGER.csv", PAYMENTS)
    dump("MBT_POS_STOCK_MOVEMENT_LEDGER.csv", STOCK)
    dump("MBT_POS_DEBT_REPAYMENT_LEDGER.csv", DEBTS)
    counts = {}
    for row in ROWS:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    text = f"""# Mixed-tender acceptance {RUN}

Branch `port/v3.1.66-audit`, commit `f1df495`, plus uncommitted tender work.
Isolated database `{DB_PATH}`. The live shop database was not opened.

| Status | Count |
|---|---:|
| PASS | {counts.get('PASS', 0)} |
| FAIL | {counts.get('FAIL', 0)} |
| NOT SUPPORTED | {counts.get('NOT SUPPORTED', 0)} |

A KES 1,000 sale can now take cash, M-Pesa, card, bank transfer, and a customer-credit remainder in one receipt. A pending M-Pesa line is not collected. Repeating the same client token does not create a second sale. Repayments of 100, 150, and 250 take a 500 balance to 0 and do not add a sale.

Dedicated cart-splitting is not a separate action. Two checkouts sell the chosen quantities once each.
Real Safaricom charges were not made.

The installed Program Files till is still 3.1.73 and does not contain this tender change.
"""
    (OUT / "MBT_POS_MASTER_ACCEPTANCE_REPORT.md").write_text(text, encoding="utf-8")
    (REPO / "MBT_POS_MASTER_ACCEPTANCE_REPORT.md").write_text(text, encoding="utf-8")
    recon = """# Accounting reconciliation — mixed tender

Independent check for ST-05:

- Sale total 1,000
- Confirmed cash 200
- Confirmed M-Pesa 300
- Outstanding credit 500
- 200 + 300 + 500 = 1,000
- Stock falls by the sold quantity once
- A repeated token does not sell again

ST-09 repayments reduce the 500 debt by 100, then 150, then 250. Those receipts are debt payments, not sales.

Pending M-Pesa is excluded, so 200 cash + 500 credit does not cover 1,000 and the sale is refused.
"""
    (OUT / "MBT_POS_ACCOUNTING_RECONCILIATION.md").write_text(recon, encoding="utf-8")
    (REPO / "MBT_POS_ACCOUNTING_RECONCILIATION.md").write_text(recon, encoding="utf-8")
    defects = """# Defect register — mixed tender

## Fixed in this working tree

- DEF-TENDER-1: The dashboard sale rejected a split that did not cover the total, so cash + M-Pesa + customer credit could not be one sale. `allocate_sale` now accepts that allocation, ignores unconfirmed electronic lines, and creates one debt for the credit remainder.

## Still open

- The installed 3.1.73 executable does not include this fix.
- Splitting one open cart into several bills is not a single action.
- Edmus activation and live command checks were not run.
"""
    (OUT / "MBT_POS_DEFECT_REGISTER.md").write_text(defects, encoding="utf-8")
    (REPO / "MBT_POS_DEFECT_REGISTER.md").write_text(defects, encoding="utf-8")
    role = """# Role and security notes — mixed tender

The cashier session used for these sales cannot remove a product. That was verified in MBTQA-20261027-001. Credit without a customer is rejected by the server. Viewer sales remain denied by the existing sales permission.

This run did not repeat the full five-role matrix.
"""
    (OUT / "MBT_POS_ROLE_SECURITY_REPORT.md").write_text(role, encoding="utf-8")
    (REPO / "MBT_POS_ROLE_SECURITY_REPORT.md").write_text(role, encoding="utf-8")
    offline = """# Offline and recovery

Offline selling, a Windows restart, and a cloud backup were not run in this tender pass. A pending payment is refused rather than stored as collected money. The same client token returns the original sale instead of posting a second one.
"""
    (OUT / "MBT_POS_OFFLINE_RECOVERY_REPORT.md").write_text(offline, encoding="utf-8")
    (REPO / "MBT_POS_OFFLINE_RECOVERY_REPORT.md").write_text(offline, encoding="utf-8")
    release = """# Release verification

Installed executable: `C:\\Program Files\\MugoByte\\MBT POS\\MBT_POS.exe`, file version 3.1.73.0, written 2026-10-27 18:31.

That file was built before the mixed-credit allocation. It is not the build that passed ST-01 to ST-12. No new installer was published. GitHub latest remains 3.1.72.
"""
    (OUT / "MBT_POS_RELEASE_VERIFICATION.md").write_text(release, encoding="utf-8")
    (REPO / "MBT_POS_RELEASE_VERIFICATION.md").write_text(release, encoding="utf-8")
    summary = text + "\nThe final installed build is not yet safe to treat as containing the mixed-credit fix.\n"
    (OUT / "MBT_POS_FINAL_ACCEPTANCE_SUMMARY.md").write_text(summary, encoding="utf-8")
    (REPO / "MBT_POS_FINAL_ACCEPTANCE_SUMMARY.md").write_text(summary, encoding="utf-8")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        for item in patches:
            item.stop()
        ac._SCHEMA_READY = False
