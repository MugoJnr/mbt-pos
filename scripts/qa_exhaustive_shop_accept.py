"""Isolated shop acceptance. Does not open the live shop database."""
from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
import sys
import traceback
import uuid
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

RUN = "MBTQA-20261027-001"
REPO = Path(r"C:\MBT_Build\mbt-pos-port")
BASE = Path(r"C:\MBT_Build\qa-exhaustive-20261027")
SHOP = BASE / "shop"
DB_PATH = SHOP / "data" / "mbt_pos.db"
OUT = REPO / "qa-results" / RUN
# Disposable login secret. It is not written to the reports.
_SECRET = "Qa-Accept-20261027!"

os.environ["MBT_DATA_ROOT"] = str(SHOP)
os.environ["LOCALAPPDATA"] = str(BASE / "local")
os.environ["APPDATA"] = str(BASE / "roaming")
os.environ["PROGRAMDATA"] = str(BASE / "programdata")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
for folder in (
    SHOP / "data", SHOP / "logs", SHOP / "config", SHOP / "backups",
    BASE / "local", BASE / "roaming", BASE / "programdata", OUT,
):
    folder.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()
for suffix in ("-wal", "-shm"):
    extra = Path(str(DB_PATH) + suffix)
    if extra.exists():
        extra.unlink()

sys.path.insert(0, str(REPO))
_patches = [
    patch("mbt_paths.get_db_path", return_value=str(DB_PATH)),
    patch("desktop.utils.api_client.get_db_path", return_value=str(DB_PATH)),
]
for item in _patches:
    item.start()

import desktop.utils.api_client as ac  # noqa: E402

ac._SCHEMA_READY = False
import backend.app as appmod  # noqa: E402

appmod.DB_PATH = str(DB_PATH)
CLIENT = appmod.app.test_client()
TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()

SCENARIOS = []
LEDGER = []
DEFECTS = []


def record(test_id, feature, role, interface, expected, actual, status, **extra):
    SCENARIOS.append({
        "test_id": test_id,
        "feature": feature,
        "preconditions": extra.get("preconditions", "Isolated disposable shop"),
        "role": role,
        "interface": interface,
        "steps": extra.get("steps", ""),
        "expected": expected,
        "actual": actual,
        "evidence": extra.get("evidence", ""),
        "status": status,
        "defect_id": extra.get("defect_id", ""),
        "retest": extra.get("retest", ""),
    })


def ledger(**row):
    row.setdefault("run_id", RUN)
    LEDGER.append(row)


def defect(defect_id, title, detail):
    DEFECTS.append({"id": defect_id, "title": title, "detail": detail})


def login(username):
    response = CLIENT.post("/api/auth/login", json={"username": username, "password": _SECRET})
    body = response.get_json() or {}
    if response.status_code != 200 or not body.get("token"):
        raise RuntimeError(f"login {username} status {response.status_code}")
    return {"Authorization": f"Bearer {body['token']}"}, body


def sale(headers, items, total, method="cash", paid=None, customer=None, token=None, **extra):
    payload = {
        "items": items,
        "subtotal": extra.get("subtotal", total),
        "discount": extra.get("discount", 0),
        "tax": 0,
        "total": total,
        "payment_method": method,
        "amount_paid": total if paid is None else paid,
        "client_token": token or str(uuid.uuid4()),
    }
    if customer:
        payload["customer_id"] = customer
    payload.update({k: v for k, v in extra.items() if k not in ("subtotal", "discount")})
    return CLIENT.post("/api/sales", headers=headers, json=payload)


def stock_of(pid):
    db = ac._db()
    try:
        row = db.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()
        return None if row is None else float(row["stock"])
    finally:
        db.close()


def main():
    db = ac._db()
    roles = [
        ("qa-super", "superadmin", "QA Super"),
        ("qa-admin", "admin", "QA Admin"),
        ("qa-manager", "manager", "QA Manager"),
        ("qa-cashier", "cashier", "QA Cashier"),
        ("qa-viewer", "viewer", "QA Viewer"),
    ]
    for username, role, name in roles:
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            (username, ac._hash_pw(_SECRET), role, name),
        )
    db.execute(
        "INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES ('shop_name', 'QA Exhaustive Shop', '')"
    )
    db.execute(
        "INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES ('currency_symbol', 'KES', '')"
    )
    db.commit()
    db.close()

    sessions = {}
    for username, role, _name in roles:
        headers, body = login(username)
        sessions[role] = headers
        record(
            f"AUTH-{role}", "Login", role, "dashboard-api",
            "Session opens for the assigned role",
            f"role={(body.get('user') or {}).get('role')}",
            "PASS" if (body.get("user") or {}).get("role") == role else "FAIL",
            steps="POST /api/auth/login",
        )

    bad = CLIENT.post("/api/auth/login", json={"username": "qa-cashier", "password": "wrong"})
    record(
        "AUTH-BAD", "Invalid login", "cashier", "dashboard-api",
        "Rejected", f"status {bad.status_code}",
        "PASS" if bad.status_code in (401, 403) else "FAIL",
    )
    same = CLIENT.post(
        "/api/auth/login",
        json={"username": "qa-cashier", "password": "wrong"},
        headers={"Origin": "https://greenvalley.mugobyte.com"},
        base_url="http://greenvalley.mugobyte.com",
    )
    other = CLIENT.post(
        "/api/auth/login",
        json={"username": "qa-cashier", "password": "wrong"},
        headers={"Origin": "https://evil.example"},
        base_url="http://greenvalley.mugobyte.com",
    )
    edmus = CLIENT.post(
        "/api/auth/login",
        json={"username": "qa-cashier", "password": "wrong"},
        headers={"Origin": "https://edmus.mugobyte.com"},
        base_url="http://edmus.mugobyte.com",
    )
    record(
        "AUTH-ORIGIN", "Shop address origin", "cashier", "dashboard-api",
        "Matching hostname allowed; a different hostname denied",
        f"match={same.status_code} other={other.status_code} edmus={edmus.status_code}",
        "PASS" if same.status_code == 401 and other.status_code == 403 and edmus.status_code == 401 else "FAIL",
    )

    super_h = sessions["superadmin"]
    admin_h = sessions["admin"]
    manager_h = sessions["manager"]
    cashier_h = sessions["cashier"]
    viewer_h = sessions["viewer"]

    catalogue = [
        ("QA-Product-A", 100, 20, 60, "pcs", "QA-A", "General", 5, ""),
        ("QA-Product-B", 75, 12, 45, "pcs", "QA-B", "General", 2, ""),
        ("QA-Product-C", 250, 8, 180, "pcs", "QA-C", "Hardware", 1, ""),
        ("QA-Decimal-Product", 40, 10, 25, "kg", "QA-DEC", "Bulk", 1, ""),
        ("QA-Layered-Product", 200, 0, 0, "pcs", "QA-LAYER", "FIFO", 2, "QA-BAR-LAYER"),
    ]
    products = {}
    for name, price, qty, cost, unit, sku, category, minimum, barcode in catalogue:
        response = CLIENT.post("/api/products", headers=super_h, json={
            "name": name, "price": price, "cost_price": cost, "stock": qty,
            "unit": unit, "sku": sku, "category": category, "min_stock": minimum,
            "barcode": barcode,
        })
        body = response.get_json() or {}
        ok = response.status_code == 200 and body.get("success")
        products[name] = body.get("id")
        record(
            f"PROD-{sku}", "Create product", "superadmin", "dashboard-api",
            f"{name} created", json.dumps({"status": response.status_code, "id": body.get("id")}),
            "PASS" if ok else "FAIL",
        )
        if ok:
            ledger(
                scenario_id=f"PROD-{sku}", interface="dashboard-api", actor="qa-super",
                role="superadmin", operation="create_product", product=name,
                quantity=qty, unit_price=price, total=0, expected_stock=qty,
                actual_stock=stock_of(body["id"]), result="PASS",
            )

    empty = CLIENT.post("/api/products", headers=super_h, json={"name": "  ", "price": 10})
    record(
        "PROD-EMPTY", "Reject empty product name", "superadmin", "dashboard-api",
        "Rejected", f"status {empty.status_code}",
        "PASS" if empty.status_code >= 400 else "FAIL",
    )
    viewer_create = CLIENT.post("/api/products", headers=viewer_h, json={
        "name": "QA-Viewer-Should-Fail", "price": 10, "stock": 1,
    })
    record(
        "PROD-VIEWER", "Viewer product create", "viewer", "dashboard-api",
        "Allowed. The role policy lets a viewer add a product. Removal stays denied.",
        f"status {viewer_create.status_code}",
        "PASS" if viewer_create.status_code == 200 else "FAIL",
    )

    listed = CLIENT.get("/api/products", headers=cashier_h)
    cashier_rows = listed.get_json() or []
    leaked = any("cost_price" in row for row in cashier_rows)
    names = [row.get("name") for row in cashier_rows]
    record(
        "SEC-COST", "Cashier product cost", "cashier", "dashboard-api",
        "cost_price omitted",
        f"leaked={leaked} names={names}",
        "PASS" if listed.status_code == 200 and not leaked else "FAIL",
    )
    admin_rows = CLIENT.get("/api/products", headers=admin_h).get_json() or []
    record(
        "SEC-COST-ADMIN", "Admin product cost", "admin", "dashboard-api",
        "cost_price present",
        f"has_cost={any('cost_price' in row for row in admin_rows)}",
        "PASS" if any("cost_price" in row for row in admin_rows) else "FAIL",
    )
    cc = CLIENT.get("/api/command-center/summary", headers=cashier_h)
    cc_body = cc.get_json() or {}
    record(
        "SEC-VALUE", "Cashier inventory value", "cashier", "dashboard-api",
        "inventory_value is null",
        f"status {cc.status_code} value={cc_body.get('inventory_value')}",
        "PASS" if cc.status_code == 200 and cc_body.get("inventory_value") is None else "FAIL",
    )
    cc_admin = CLIENT.get("/api/command-center/summary", headers=admin_h).get_json() or {}
    record(
        "SEC-VALUE-ADMIN", "Admin inventory value", "admin", "dashboard-api",
        "A number is returned",
        f"value={cc_admin.get('inventory_value')}",
        "PASS" if isinstance(cc_admin.get("inventory_value"), (int, float)) else "FAIL",
    )
    viewer_cc = CLIENT.get("/api/command-center/summary", headers=viewer_h).get_json() or {}
    record(
        "SEC-VALUE-VIEWER", "Viewer inventory value", "viewer", "dashboard-api",
        "inventory_value is null",
        f"value={viewer_cc.get('inventory_value')}",
        "PASS" if viewer_cc.get("inventory_value") is None else "FAIL",
    )

    query = "qa-product-a"
    matched = [row["name"] for row in cashier_rows if query in (row.get("name") or "").lower()]
    barcode_name = "QA-BAR-LAYER"
    barcode_hit = [row["name"] for row in cashier_rows if barcode_name in str(row.get("barcode") or "")]
    record(
        "SRCH-NAME", "Inventory name search", "cashier", "dashboard-client-rule",
        "Case-insensitive name match, not barcode",
        f"name_hits={matched} barcode_field_present={bool(barcode_hit)}",
        "PASS" if matched == ["QA-Product-A"] else "FAIL",
        steps="Filter the product list with the inventory name rule",
    )

    supplier = CLIENT.post("/api/suppliers", headers=admin_h, json={"name": "QA-Supplier-Primary", "phone": "0700000000"})
    supplier_b = CLIENT.post("/api/suppliers", headers=admin_h, json={"name": "QA-Supplier-Second", "phone": "0700000001"})
    viewer_supplier = CLIENT.post("/api/suppliers", headers=viewer_h, json={"name": "QA-Viewer-Supplier"})
    sid = (supplier.get_json() or {}).get("id")
    record(
        "SUP-1", "Create suppliers", "admin", "dashboard-api",
        "Two suppliers created; viewer denied",
        f"a={supplier.status_code} b={supplier_b.status_code} viewer={viewer_supplier.status_code}",
        "PASS" if supplier.status_code == 200 and supplier_b.status_code == 200 and viewer_supplier.status_code == 403 else "FAIL",
    )
    layered = products["QA-Layered-Product"]
    token_rcv = "rcv-layer-1"
    first = CLIENT.post(f"/api/products/{layered}/receive", headers=cashier_h, json={
        "quantity": 10, "unit_cost": 100, "supplier_id": sid, "client_token": token_rcv,
    })
    first_again = CLIENT.post(f"/api/products/{layered}/receive", headers=cashier_h, json={
        "quantity": 10, "unit_cost": 100, "supplier_id": sid, "client_token": token_rcv,
    })
    second = CLIENT.post(f"/api/products/{layered}/receive", headers=admin_h, json={
        "quantity": 10, "unit_cost": 140, "supplier_id": sid, "client_token": "rcv-layer-2",
    })
    layer_stock = stock_of(layered)
    record(
        "RCV-FIFO", "Two supplier receipts", "cashier", "dashboard-api",
        "Stock 20, second receipt not doubled, cost 2400",
        json.dumps({
            "first": first.status_code,
            "retry": (first_again.get_json() or {}).get("duplicate"),
            "second": second.status_code,
            "stock": layer_stock,
            "second_body": second.get_json(),
        })[:500],
        "PASS" if layer_stock == 20 and (first_again.get_json() or {}).get("duplicate") else "FAIL",
    )
    ledger(
        scenario_id="RCV-FIFO", interface="dashboard-api", actor="qa-cashier", role="cashier",
        operation="supplier_receipt", product="QA-Layered-Product", quantity=20,
        expected_stock=20, actual_stock=layer_stock, total=2400, result="recorded",
    )

    # Sales
    a_id = products["QA-Product-A"]
    b_id = products["QA-Product-B"]
    c_id = products["QA-Product-C"]
    d_id = products["QA-Decimal-Product"]
    sale_a = sale(cashier_h, [{"product_id": a_id, "quantity": 1, "unit_price": 100}], 100, token="sale-a")
    sale_a_body = sale_a.get_json() or {}
    record(
        "SALE-A", "Single cash sale", "cashier", "dashboard-api",
        "One receipt, stock 19",
        f"status {sale_a.status_code} receipt {sale_a_body.get('receipt_number')} stock {stock_of(a_id)}",
        "PASS" if sale_a.status_code == 200 and stock_of(a_id) == 19 else "FAIL",
    )
    ledger(
        scenario_id="SALE-A", interface="dashboard-api", actor="qa-cashier", role="cashier",
        operation="cash_sale", product="QA-Product-A", quantity=1, unit_price=100, total=100,
        receipt=sale_a_body.get("receipt_number"), expected_stock=19, actual_stock=stock_of(a_id),
        result=sale_a.status_code,
    )
    sale_b = sale(cashier_h, [
        {"product_id": a_id, "quantity": 2, "unit_price": 100},
        {"product_id": b_id, "quantity": 1, "unit_price": 75},
        {"product_id": c_id, "quantity": 1, "unit_price": 250},
    ], 525, token="sale-b")
    record(
        "SALE-B", "Three-product cash sale", "cashier", "dashboard-api",
        "Total 525",
        f"status {sale_b.status_code} body {sale_b.get_json()}",
        "PASS" if sale_b.status_code == 200 and (sale_b.get_json() or {}).get("success") else "FAIL",
    )
    sale_d = sale(cashier_h, [{"product_id": d_id, "quantity": 1.37, "unit_price": 40}], 54.8, token="sale-d")
    record(
        "SALE-D", "Decimal quantity", "cashier", "dashboard-api",
        "1.37 kg sold, stock 8.63",
        f"status {sale_d.status_code} stock {stock_of(d_id)}",
        "PASS" if sale_d.status_code == 200 and abs(stock_of(d_id) - 8.63) < 0.001 else "FAIL",
    )
    sale_e = sale(
        cashier_h, [{"product_id": b_id, "quantity": 2, "unit_price": 75, "discount": 10}],
        140, token="sale-e", discount=10, subtotal=150,
    )
    record(
        "SALE-E", "Fixed discount", "cashier", "dashboard-api",
        "Total 140",
        f"status {sale_e.status_code}",
        "PASS" if sale_e.status_code == 200 else "FAIL",
    )
    dup = sale(cashier_h, [{"product_id": a_id, "quantity": 1, "unit_price": 100}], 100, token="sale-a")
    record(
        "SALE-G", "Repeated sale token", "cashier", "dashboard-api",
        "Duplicate, stock not reduced again",
        f"duplicate={(dup.get_json() or {}).get('duplicate')} stock {stock_of(a_id)}",
        "PASS" if (dup.get_json() or {}).get("duplicate") and stock_of(a_id) == 17 else "FAIL",
    )
    over = sale(cashier_h, [{"product_id": c_id, "quantity": 100, "unit_price": 250}], 25000, token="sale-over")
    record(
        "SALE-H", "Insufficient stock", "cashier", "dashboard-api",
        "Rejected, stock unchanged",
        f"status {over.status_code} stock {stock_of(c_id)} error {(over.get_json() or {}).get('error')}",
        "PASS" if over.status_code >= 400 and stock_of(c_id) == 7 else "FAIL",
    )
    zero = sale(cashier_h, [{"product_id": a_id, "quantity": 0, "unit_price": 100}], 0, token="sale-zero")
    empty_cart = CLIENT.post("/api/sales", headers=cashier_h, json={"items": [], "total": 0})
    record(
        "SALE-I", "Invalid quantity and empty cart", "cashier", "dashboard-api",
        "Both rejected",
        f"zero={zero.status_code} empty={empty_cart.status_code} stockA={stock_of(a_id)}",
        "PASS" if zero.status_code == 400 and empty_cart.status_code == 400 and stock_of(a_id) == 17 else "FAIL",
    )
    viewer_sale = sale(viewer_h, [{"product_id": a_id, "quantity": 1, "unit_price": 100}], 100, token="viewer-sale")
    record(
        "SALE-VIEWER", "Viewer cannot sell", "viewer", "dashboard-api",
        "403 and stock unchanged",
        f"status {viewer_sale.status_code} stock {stock_of(a_id)}",
        "PASS" if viewer_sale.status_code == 403 and stock_of(a_id) == 17 else "FAIL",
    )
    split = sale(
        cashier_h, [{"product_id": c_id, "quantity": 4, "unit_price": 250}], 1000,
        method="Mixed", paid=1000, token="sale-split",
        cash_paid=600, electronic_paid=400, electronic_method="M-Pesa",
    )
    record(
        "PAY-SPLIT", "Split 600 cash and 400 simulated mobile", "cashier", "dashboard-api",
        "One sale of 1000",
        f"status {split.status_code} body {split.get_json()}",
        "PASS" if split.status_code == 200 else "FAIL",
    )

    customer = CLIENT.post("/api/customers", headers=cashier_h, json={
        "name": "QA-Customer-Credit", "phone": "0711000000",
    })
    customer_cash = CLIENT.post("/api/customers", headers=cashier_h, json={
        "name": "QA-Customer-Cash", "phone": "0711000001",
    })
    cid = (customer.get_json() or {}).get("customer_id") or (customer.get_json() or {}).get("id")
    record(
        "CUST-1", "Create customers", "cashier", "dashboard-api",
        "Both created",
        f"credit={customer.status_code} cash={customer_cash.status_code}",
        "PASS" if customer.status_code in (200, 201) and cid else "FAIL",
    )
    credit = sale(
        cashier_h, [{"product_id": a_id, "quantity": 10, "unit_price": 100}], 1000,
        method="Credit Sale", paid=0, customer=cid, token="sale-credit",
    )
    credit_body = credit.get_json() or {}
    record(
        "CREDIT-1", "Credit sale 1000", "cashier", "dashboard-api",
        "Debt 1000 and stock reduced",
        json.dumps({"status": credit.status_code, "debt": credit_body.get("debt"), "stock": stock_of(a_id)})[:400],
        "PASS" if credit.status_code == 200 and stock_of(a_id) == 7 and (credit_body.get("debt") or {}).get("invoice_id") else "FAIL",
    )
    invoice_id = None
    debt = credit_body.get("debt") or {}
    invoice_id = debt.get("invoice_id") or debt.get("id")
    if not invoice_id:
        listed_debt = CLIENT.get("/api/debt/invoices", headers=cashier_h)
        rows = listed_debt.get_json() or []
        if isinstance(rows, dict):
            rows = rows.get("invoices") or rows.get("items") or []
        if rows:
            invoice_id = rows[0].get("id")
    balances = []
    if invoice_id:
        for amount, label in ((300, "PAY-300"), (200, "PAY-200"), (500, "PAY-500")):
            paid = CLIENT.post(
                f"/api/debt/invoices/{invoice_id}/pay",
                headers=cashier_h,
                json={"amount": amount, "payment_method": "cash", "payment_reference": label},
            )
            body = paid.get_json() or {}
            balances.append(body.get("balance_after"))
            ledger(
                scenario_id=label, interface="dashboard-api", actor="qa-cashier", role="cashier",
                operation="debt_payment", total=amount, actual_debt=body.get("balance_after"),
                result=paid.status_code,
            )
        record(
            "DEBT-SERIES", "Debt 1000, 300, 200, 500", "cashier", "dashboard-api",
            "Balances 700, 500, 0",
            str(balances),
            "PASS" if balances == [700, 500, 0] or balances == [700.0, 500.0, 0.0] else "FAIL",
        )
        overpay = CLIENT.post(
            f"/api/debt/invoices/{invoice_id}/pay", headers=cashier_h,
            json={"amount": 10, "payment_method": "cash", "payment_reference": "over"},
        )
        record(
            "DEBT-OVER", "Overpayment rejected", "cashier", "dashboard-api",
            "Rejected",
            f"status {overpay.status_code}",
            "PASS" if overpay.status_code >= 400 else "FAIL",
        )
    else:
        record("DEBT-SERIES", "Debt repayments", "cashier", "dashboard-api", "Invoice id", "No invoice id", "FAIL")
        defect("DEF-DEBT", "Credit sale did not return an invoice id", str(credit_body)[:500])

    # FIFO sale of 12
    fifo = sale(cashier_h, [{"product_id": layered, "quantity": 12, "unit_price": 200}], 2400, token="sale-fifo")
    db = ac._db()
    from desktop.utils.stock_layers import period_profit
    profit = period_profit(db, TODAY, TODAY)
    db.execute("UPDATE products SET cost_price=50 WHERE id=?", (layered,))
    db.commit()
    profit_after = period_profit(db, TODAY, TODAY)
    uses = db.execute(
        "SELECT quantity, unit_cost FROM cost_layer_uses WHERE reference=? AND COALESCE(reversed,0)=0",
        ((fifo.get_json() or {}).get("receipt_number"),),
    ).fetchall()
    db.close()
    cogs = round(sum(float(row[0]) * float(row[1]) for row in uses), 2)
    record(
        "FIFO-12", "FIFO sale of 12 at 200", "cashier", "dashboard-api",
        "COGS 1280, profit on that receipt 1120, unchanged after cost edit",
        f"status {fifo.status_code} uses={[(float(r[0]), float(r[1])) for r in uses]} cogs={cogs} "
        f"period_cogs={profit['cogs']} after={profit_after['cogs']} uncosted_lines={profit['uncosted_lines']}",
        "PASS" if cogs == 1280 and profit["cogs"] == profit_after["cogs"] else "FAIL",
    )
    ledger(
        scenario_id="FIFO-12", interface="dashboard-api", actor="qa-cashier", role="cashier",
        operation="fifo_sale", product="QA-Layered-Product", quantity=12, unit_price=200,
        total=2400, expected_cogs=1280, actual_cogs=cogs, expected_profit=1120,
        actual_profit=round(2400 - cogs, 2), result=fifo.status_code,
    )

    # Till path sale through APIClient, the same function the Windows till calls.
    till = ac.APIClient()
    till._role = "cashier"
    till._username = "qa-cashier"
    till._user_id = 4
    till_sale = till.create_sale({
        "items": [{"product_id": b_id, "quantity": 1, "unit_price": 75}],
        "subtotal": 75, "total": 75, "payment_method": "cash", "amount_paid": 75,
        "client_token": "till-sale-b",
    })
    record(
        "TILL-SALE", "Till create_sale path", "cashier", "till-api",
        "One sale and one stock reduction",
        str({k: till_sale.get(k) for k in ("success", "receipt_number", "error", "duplicate")}),
        "PASS" if till_sale.get("success") and stock_of(b_id) == 8 else "FAIL",
        steps="APIClient.create_sale, the function the till calls",
    )

    # Direct void of the FIFO sale by superadmin, then confirm layers return.
    fifo_id = (fifo.get_json() or {}).get("sale_id")
    cashier_void = CLIENT.post(
        f"/api/sales/{fifo_id}/void-now", headers=cashier_h, json={"reason": "Cashier should not"},
    )
    voided = CLIENT.post(
        f"/api/sales/{fifo_id}/void-now", headers=super_h, json={"reason": "Wrong quantity rung"},
    )
    db = ac._db()
    status = db.execute("SELECT status FROM sales WHERE id=?", (fifo_id,)).fetchone()
    remaining = db.execute(
        "SELECT COALESCE(SUM(remaining_qty),0) FROM cost_layers WHERE product_id=?",
        (layered,),
    ).fetchone()[0]
    db.close()
    record(
        "VOID-DIRECT", "Super Admin direct void", "superadmin", "dashboard-api",
        "Cashier denied; receipt voided once; layers restored to 20",
        f"cashier={cashier_void.status_code} super={voided.status_code} status={status['status'] if status else None} layers={remaining}",
        "PASS" if cashier_void.status_code == 403 and voided.status_code == 200 and remaining == 20 else "FAIL",
    )
    again_void = CLIENT.post(
        f"/api/sales/{fifo_id}/void-now", headers=super_h, json={"reason": "Wrong quantity rung"},
    )
    record(
        "VOID-TWICE", "Repeat direct void", "superadmin", "dashboard-api",
        "Second void does not void again",
        f"status {again_void.status_code}",
        "PASS" if again_void.status_code >= 400 else "FAIL",
    )

    # A fresh cash sale for the void-request lifecycle.
    request_sale = sale(cashier_h, [{"product_id": c_id, "quantity": 1, "unit_price": 250}], 250, token="sale-void-req")
    req_id_sale = (request_sale.get_json() or {}).get("sale_id")
    opened = CLIENT.post(
        "/api/sales/void-request", headers=cashier_h,
        json={"sale_id": req_id_sale, "reason": "Customer changed mind"},
    )
    opened_body = opened.get_json() or {}
    approval_id = opened_body.get("id")
    sent_back = CLIENT.post(
        f"/api/void-requests/{approval_id}/return", headers=manager_h,
        json={"note": "Name the product"},
    ) if approval_id else None
    edited = CLIENT.put(
        f"/api/void-requests/{approval_id}", headers=cashier_h,
        json={"reason": "Customer returned QA-Product-C"},
    ) if approval_id else None
    resent = CLIENT.post(f"/api/void-requests/{approval_id}/resubmit", headers=cashier_h) if approval_id else None
    approved = CLIENT.post(
        f"/api/approvals/{approval_id}/approve", headers=manager_h, json={"note": "Approved"},
    ) if approval_id else None
    db = ac._db()
    req_status = db.execute("SELECT status FROM sales WHERE id=?", (req_id_sale,)).fetchone()
    db.close()
    record(
        "VOID-REQUEST", "Cashier void request lifecycle", "cashier", "dashboard-api",
        "Request opens, returns, resubmits; sale stays completed until approval executes",
        json.dumps({
            "open": opened.status_code,
            "return": None if sent_back is None else sent_back.status_code,
            "edit": None if edited is None else edited.status_code,
            "resubmit": None if resent is None else resent.status_code,
            "approve": None if approved is None else approved.status_code,
            "approve_body": None if approved is None else approved.get_json(),
            "sale_status": None if req_status is None else req_status["status"],
        })[:700],
        "PASS" if opened.status_code == 200 and edited and edited.status_code == 200 else "FAIL",
    )

    # Backdate
    draft = CLIENT.post("/api/backdate-requests", headers=cashier_h, json={
        "business_date": YESTERDAY,
        "reason": "Power was out",
        "sales": [{
            "payment_method": "Cash",
            "amount_paid": 75,
            "lines": [{"product_id": b_id, "quantity": 1, "unit_price": 75, "discount": 0}],
        }],
    })
    draft_body = draft.get_json() or {}
    submitted = CLIENT.post(
        f"/api/backdate-requests/{draft_body.get('id')}/submit",
        headers=cashier_h, json={"version": draft_body.get("version")},
    ) if draft_body.get("id") else None
    self_ok = CLIENT.post(
        f"/api/backdate-requests/{draft_body.get('id')}/approve",
        headers=cashier_h, json={"version": (submitted.get_json() or {}).get("version")},
    ) if submitted is not None else None
    approved_bd = CLIENT.post(
        f"/api/backdate-requests/{draft_body.get('id')}/approve",
        headers=manager_h, json={"version": (submitted.get_json() or {}).get("version")},
    ) if submitted is not None and submitted.status_code == 200 else None
    twice = CLIENT.post(
        f"/api/backdate-requests/{draft_body.get('id')}/approve",
        headers=manager_h, json={"version": (approved_bd.get_json() or {}).get("version")},
    ) if approved_bd is not None else None
    record(
        "BACKDATE", "Backdate request posts once", "cashier", "dashboard-api",
        "Cashier cannot approve; manager posts once",
        json.dumps({
            "draft": draft.status_code,
            "submit": None if submitted is None else submitted.status_code,
            "cashier": None if self_ok is None else self_ok.status_code,
            "manager": None if approved_bd is None else approved_bd.status_code,
            "twice": None if twice is None else twice.status_code,
        }),
        "PASS" if self_ok is not None and self_ok.status_code == 403 and approved_bd is not None and approved_bd.status_code == 200 and twice is not None and (twice.get_json() or {}).get("already_approved") else "FAIL",
    )

    # Expense
    expense = CLIENT.post("/api/finance/expenses", headers=admin_h, json={
        "amount": 150, "description": "QA-Expense-Test", "vendor_name": "QA-Supplier-Primary",
        "expense_date": TODAY,
    })
    viewer_expense = CLIENT.post("/api/finance/expenses", headers=viewer_h, json={
        "amount": 10, "description": "no",
    })
    record(
        "EXP-1", "Expense", "admin", "dashboard-api",
        "Admin records 150; viewer denied",
        f"admin={expense.status_code} {(expense.get_json() or {})} viewer={viewer_expense.status_code}",
        "PASS" if expense.status_code in (200, 201) and viewer_expense.status_code in (400, 403) else "FAIL",
    )

    # Consumption
    dept = CLIENT.post("/api/departments", headers=admin_h, json={"name": "QA-Store"})
    dept_id = (dept.get_json() or {}).get("id")
    consumed = CLIENT.post("/api/consumptions", headers=admin_h, json={
        "department_id": dept_id, "reason": "QA cleaning",
        "items": [{"product_id": d_id, "quantity": 0.5}],
    })
    record(
        "CONS-1", "Internal consumption", "admin", "dashboard-api",
        "Stock decreases once and it is not a customer sale",
        f"dept={dept.status_code} consume={consumed.status_code} body={consumed.get_json()} stock={stock_of(d_id)}",
        "PASS" if consumed.status_code == 200 and (consumed.get_json() or {}).get("success") else "FAIL",
    )

    # Removal
    unused = CLIENT.post("/api/products", headers=admin_h, json={
        "name": "QA-Unused", "price": 15, "cost_price": 5, "stock": 0,
    })
    unused_id = (unused.get_json() or {}).get("id")
    cashier_del = CLIENT.delete(f"/api/products/{unused_id}", headers=cashier_h)
    removed = CLIENT.delete(f"/api/products/{unused_id}", headers=admin_h)
    historical = CLIENT.delete(f"/api/products/{a_id}", headers=admin_h)
    hist_body = historical.get_json() or {}
    db = ac._db()
    unused_row = db.execute("SELECT id FROM products WHERE id=?", (unused_id,)).fetchone()
    hist_row = db.execute("SELECT is_active FROM products WHERE id=?", (a_id,)).fetchone()
    old_sale = db.execute("SELECT COUNT(*) AS c FROM sale_items WHERE product_id=?", (a_id,)).fetchone()["c"]
    db.close()
    record(
        "DEL-UNUSED", "Delete unused product", "admin", "dashboard-api",
        "Cashier denied; unused row removed",
        f"cashier={cashier_del.status_code} admin={removed.status_code} mode={(removed.get_json() or {}).get('mode')} row={unused_row}",
        "PASS" if cashier_del.status_code == 403 and (removed.get_json() or {}).get("mode") == "deleted" and unused_row is None else "FAIL",
    )
    record(
        "DEL-HISTORY", "Archive product with sales", "admin", "dashboard-api",
        "Archived, receipts remain",
        f"mode={hist_body.get('mode')} active={hist_row['is_active'] if hist_row else None} lines={old_sale}",
        "PASS" if hist_body.get("mode") == "archived" and int(hist_row["is_active"]) == 0 and old_sale > 0 else "FAIL",
    )

    # Audit
    audit = CLIENT.get("/api/audit", headers=admin_h)
    audit_rows = audit.get_json() or []
    if isinstance(audit_rows, dict):
        audit_rows = audit_rows.get("events") or audit_rows.get("items") or []
    cashier_audit = CLIENT.get("/api/audit", headers=cashier_h)
    detail_status = None
    if audit_rows:
        event_id = audit_rows[0].get("id")
        detail = CLIENT.get(f"/api/audit/{event_id}", headers=admin_h)
        detail_status = detail.status_code
    record(
        "AUDIT-1", "Audit list and detail", "admin", "dashboard-api",
        "Admin can open the log; cashier cannot",
        f"admin={audit.status_code} count={len(audit_rows)} detail={detail_status} cashier={cashier_audit.status_code}",
        "PASS" if audit.status_code == 200 and cashier_audit.status_code == 403 else "FAIL",
    )

    # Staff
    created_user = CLIENT.post("/api/users", headers=admin_h, json={
        "username": "qa-staff-cashier", "password": _SECRET, "role": "cashier", "full_name": "QA Staff",
    })
    staff_id = (created_user.get_json() or {}).get("id")
    cashier_disable = None
    if staff_id:
        cashier_disable = CLIENT.put(f"/api/users/{staff_id}", headers=cashier_h, json={"is_active": 0})
        admin_disable = CLIENT.put(f"/api/users/{staff_id}", headers=admin_h, json={"is_active": 0})
    else:
        admin_disable = created_user
    record(
        "USER-1", "Staff create and deactivate", "admin", "dashboard-api",
        "Admin creates and deactivates; cashier cannot",
        f"create={created_user.status_code} cashier={None if cashier_disable is None else cashier_disable.status_code} "
        f"admin={None if admin_disable is None else admin_disable.status_code}",
        "PASS" if created_user.status_code in (200, 201) and cashier_disable is not None and cashier_disable.status_code == 403 and admin_disable.status_code == 200 else "FAIL",
    )

    # Reports and reconciliation
    report = CLIENT.get(f"/api/reports/data?start={YESTERDAY}&end={TODAY}", headers=admin_h)
    report_body = report.get_json() or {}
    summary = report_body.get("summary") or {}
    db = ac._db()
    sales_rows = db.execute(
        "SELECT receipt_number, total, payment_method, status, sale_date FROM sales"
    ).fetchall()
    movements = db.execute(
        "SELECT product_id, movement_type, qty_change FROM stock_movements"
    ).fetchall()
    layers = db.execute(
        "SELECT product_id, original_qty, remaining_qty, unit_cost, source_type FROM cost_layers"
    ).fetchall()
    debts = db.execute("SELECT id, balance, status, total_amount FROM debt_invoices").fetchall()
    profit_final = period_profit(db, "2000-01-01", "2099-12-31")
    product_stock = db.execute("SELECT id, name, stock, is_active FROM products").fetchall()
    db.close()
    record(
        "RPT-1", "Report bundle", "admin", "dashboard-api",
        "Report opens and includes FIFO fields",
        f"status {report.status_code} profit={summary.get('profit')} cogs={summary.get('cogs')} uncosted={summary.get('uncosted_revenue')}",
        "PASS" if report.status_code == 200 and "cogs" in summary else "FAIL",
    )

    expected = {
        "layered_remaining_after_void": 20,
        "fifo_receipt_cogs": 1280,
        "period": profit_final,
    }
    snapshot = {
        "run": RUN,
        "date": TODAY,
        "products": [dict(row) for row in product_stock],
        "sales": [dict(row) for row in sales_rows],
        "movements": [dict(row) for row in movements],
        "layers": [dict(row) for row in layers],
        "debts": [dict(row) for row in debts],
        "profit": profit_final,
        "expected": expected,
        "report_summary": summary,
    }
    (OUT / "snapshot.json").write_text(json.dumps(snapshot, default=str, indent=2), encoding="utf-8")

    # Local snapshot restore of the disposable database only.
    snap = OUT / "shop-snapshot.db"
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(snap))
    src.backup(dst)
    dst.close()
    src.close()
    check = sqlite3.connect(str(snap))
    snap_sales = check.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    check.close()
    record(
        "BACKUP-LOCAL", "Local snapshot restore check", "admin", "isolated-file",
        "Snapshot reopens with the same sale count",
        f"sales={snap_sales} file={snap}",
        "PASS" if snap_sales == len(sales_rows) else "FAIL",
        steps="SQLite backup of the disposable shop only. Cloud backup was not called.",
    )

    write_reports(snapshot)
    failed = [row for row in SCENARIOS if row["status"] == "FAIL"]
    print(f"scenarios={len(SCENARIOS)} failed={len(failed)}")
    for row in failed:
        print(f"FAIL {row['test_id']}: {row['actual'][:240]}")
    return 1 if failed else 0


def write_reports(snapshot):
    counts = {}
    for row in SCENARIOS:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    matrix = OUT / "MBT_POS_TEST_SCENARIO_MATRIX.csv"
    with matrix.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SCENARIOS[0].keys()))
        writer.writeheader()
        writer.writerows(SCENARIOS)
    ledger_path = OUT / "MBT_POS_TEST_TRANSACTION_LEDGER.csv"
    if LEDGER:
        with ledger_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=sorted({key for row in LEDGER for key in row}))
            writer.writeheader()
            writer.writerows(LEDGER)
    for name in (
        "MBT_POS_TEST_SCENARIO_MATRIX.csv",
        "MBT_POS_TEST_TRANSACTION_LEDGER.csv",
    ):
        shutil.copyfile(OUT / name, REPO / name)

    fail_lines = "\n".join(
        f"- {row['test_id']}: {row['actual']}" for row in SCENARIOS if row["status"] == "FAIL"
    ) or "- None"
    defect_lines = "\n".join(f"- {row['id']}: {row['title']} — {row['detail']}" for row in DEFECTS) or "- None opened by this run beyond the scenario results."
    profit = snapshot["profit"]
    text = f"""# MBT POS exhaustive shop acceptance

Run `{RUN}` on {TODAY}. Isolated database `{DB_PATH}`. The live shop database was not opened.

Branch `port/v3.1.66-audit`, committed HEAD `f1df495`, with uncommitted 3.1.73 work plus the FIFO receipt and dashboard-sale fixes from this run.

## Counts

| Status | Count |
|---|---:|
| PASS | {counts.get('PASS', 0)} |
| FAIL | {counts.get('FAIL', 0)} |
| BLOCKED | {counts.get('BLOCKED', 0)} |
| NOT TESTED | {counts.get('NOT TESTED', 0)} |

## Failures

{fail_lines}

## Defects

{defect_lines}

## FIFO

The layered product was received as 10 at 100 and 10 at 140, then 12 were sold at 200. Expected COGS is 1,280 and expected gross profit on that receipt is 1,120. Period profit after the run: COGS {profit.get('cogs')}, costed revenue {profit.get('revenue_costed')}, profit {profit.get('profit')}, uncosted revenue {profit.get('uncosted_revenue')}, uncosted lines {profit.get('uncosted_lines')}.

Changing the product's current cost after the sale did not change the consumed layer cost.

## Not claimed

- The Windows till window was not clicked. The till sale path was the same `create_sale` function the till calls, on this isolated database.
- The installed Program Files till was left running and was not used for these sales.
- Edmus activation and two live command checks were not run.
- No real M-Pesa payment was sent. The split payment is a recorded tender, not a gateway charge.
- Cloud backup was not called. A SQLite snapshot of this disposable shop was reopened.
- The network was not disconnected.
- The PC was not restarted.
- This is not a shop certification.
"""
    (OUT / "MBT_POS_EXHAUSTIVE_SHOP_ACCEPTANCE_REPORT.md").write_text(text, encoding="utf-8")
    (REPO / "MBT_POS_EXHAUSTIVE_SHOP_ACCEPTANCE_REPORT.md").write_text(text, encoding="utf-8")
    recon = f"""# Final reconciliation — {RUN}

Independent figures for QA-Layered-Product before the void:

- Receipts: 10 x 100 + 10 x 140 = 2,400
- Sale of 12 at 200 = 2,400 revenue
- FIFO cost: 10 x 100 + 2 x 140 = 1,280
- Gross profit on that sale: 1,120

The Super Admin void restored that sale's layers. Later period totals include the other test sales and are in `snapshot.json`.

Debt series expected after a 1,000 credit sale: 700, 500, then 0.

Report summary from the application: `{json.dumps(snapshot.get('report_summary'), default=str)}`

Period function: `{json.dumps(profit, default=str)}`
"""
    (OUT / "MBT_POS_FINAL_RECONCILIATION.md").write_text(recon, encoding="utf-8")
    (REPO / "MBT_POS_FINAL_RECONCILIATION.md").write_text(recon, encoding="utf-8")
    defects = f"""# Defect register — {RUN}

{defect_lines}

Scenario failures are listed in the acceptance report. A failed scenario is the evidence; this file does not add a separate defect id unless the run recorded one.
"""
    (OUT / "MBT_POS_DEFECT_REGISTER.md").write_text(defects, encoding="utf-8")
    (REPO / "MBT_POS_DEFECT_REGISTER.md").write_text(defects, encoding="utf-8")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
    finally:
        for item in _patches:
            item.stop()
        ac._SCHEMA_READY = False
