"""Confirm request and approval effects on a disposable shop."""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

REPO = Path(r"C:\MBT_Build\mbt-pos-port")
SHOP = Path(r"C:\MBT_Build\qa-approvals-20261027\shop")
DB_PATH = SHOP / "data" / "mbt_pos.db"
SECRET = "Qa-Approve-20261027!"
PIN = "246810"
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()

os.environ["MBT_DATA_ROOT"] = str(SHOP)
os.environ["LOCALAPPDATA"] = str(SHOP.parent / "local")
os.environ["APPDATA"] = str(SHOP.parent / "roaming")
os.environ["PROGRAMDATA"] = str(SHOP.parent / "programdata")
for folder in (SHOP / "data", SHOP.parent / "local", SHOP.parent / "roaming", SHOP.parent / "programdata"):
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
from desktop.utils.security import _pin_hash  # noqa: E402

ac._SCHEMA_READY = False
appmod.DB_PATH = str(DB_PATH)
CLIENT = appmod.app.test_client()
RESULTS = []


def check(name, ok, detail):
    RESULTS.append((name, "PASS" if ok else "FAIL", detail))
    print(("PASS" if ok else "FAIL"), name, detail[:220])


def sale_status(sale_id):
    db = ac._db()
    try:
        row = db.execute("SELECT status FROM sales WHERE id=?", (sale_id,)).fetchone()
        return None if row is None else row["status"]
    finally:
        db.close()


def stock():
    db = ac._db()
    try:
        return float(db.execute("SELECT stock FROM products WHERE sku='QA-REQ'").fetchone()["stock"])
    finally:
        db.close()


def main():
    db = ac._db()
    for username, role, name in (
        ("qa-cashier", "cashier", "QA Cashier"),
        ("qa-manager", "manager", "QA Manager"),
        ("qa-super", "superadmin", "QA Super"),
        ("qa-viewer", "viewer", "QA Viewer"),
    ):
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            (username, ac._hash_pw(SECRET), role, name),
        )
    db.execute(
        "INSERT INTO products (name, sku, price, cost_price, stock, is_active) VALUES (?,?,?,?,?,1)",
        ("QA Request Item", "QA-REQ", 100, 40, 20),
    )
    db.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('superadmin_pin_hash', ?)",
        (_pin_hash(PIN),),
    )
    db.commit()
    product = db.execute("SELECT id FROM products").fetchone()["id"]
    db.close()

    def login(username):
        response = CLIENT.post("/api/auth/login", json={"username": username, "password": SECRET})
        body = response.get_json() or {}
        return {"Authorization": f"Bearer {body['token']}"}

    cashier = login("qa-cashier")
    manager = login("qa-manager")
    super_h = login("qa-super")
    viewer = login("qa-viewer")

    def sell(token):
        return CLIENT.post("/api/sales", headers=cashier, json={
            "items": [{"product_id": product, "quantity": 1, "unit_price": 100}],
            "subtotal": 100, "total": 100, "payment_method": "cash",
            "amount_paid": 100, "client_token": token,
        })

    opened_sale = sell("req-void-1")
    sale_id = (opened_sale.get_json() or {}).get("sale_id")
    before = stock()
    requested = CLIENT.post("/api/sales/void-request", headers=cashier, json={
        "sale_id": sale_id, "reason": "Customer changed mind",
    })
    body = requested.get_json() or {}
    approval_id = body.get("id")
    check(
        "VOID-REQUEST",
        requested.status_code == 200 and sale_status(sale_id) == "completed" and stock() == before,
        f"open={requested.status_code} sale={sale_status(sale_id)} stock={stock()}",
    )
    again = CLIENT.post("/api/sales/void-request", headers=cashier, json={
        "sale_id": sale_id, "reason": "Customer changed mind",
    })
    check(
        "VOID-REQUEST-ONCE",
        (again.get_json() or {}).get("duplicate") is True and (again.get_json() or {}).get("id") == approval_id,
        f"body={again.get_json()}",
    )
    viewer_req = CLIENT.post("/api/sales/void-request", headers=viewer, json={
        "sale_id": sale_id, "reason": "Viewer should not",
    })
    check("VOID-VIEWER", viewer_req.status_code == 403, f"status={viewer_req.status_code}")
    cashier_approve = CLIENT.post(f"/api/approvals/{approval_id}/approve", headers=cashier, json={"pin": PIN})
    no_pin = CLIENT.post(f"/api/approvals/{approval_id}/approve", headers=manager, json={"note": "Approved"})
    check(
        "VOID-PIN-REQUIRED",
        cashier_approve.status_code == 403 and no_pin.status_code == 403 and sale_status(sale_id) == "completed",
        f"cashier={cashier_approve.status_code} manager={no_pin.status_code} sale={sale_status(sale_id)}",
    )
    sent_back = CLIENT.post(f"/api/void-requests/{approval_id}/return", headers=manager, json={"note": "Name the product"})
    too_soon = CLIENT.post(f"/api/approvals/{approval_id}/approve", headers=manager, json={"pin": PIN, "note": "Approved"})
    edited = CLIENT.put(f"/api/void-requests/{approval_id}", headers=cashier, json={"reason": "Customer returned the item"})
    resent = CLIENT.post(f"/api/void-requests/{approval_id}/resubmit", headers=cashier)
    approved = CLIENT.post(f"/api/approvals/{approval_id}/approve", headers=manager, json={"pin": PIN, "note": "Approved"})
    after = stock()
    second = CLIENT.post(f"/api/approvals/{approval_id}/approve", headers=manager, json={"pin": PIN, "note": "Approved"})
    check(
        "VOID-APPROVE-ONCE",
        sent_back.status_code == 200
        and too_soon.status_code >= 400
        and edited.status_code == 200
        and resent.status_code == 200
        and approved.status_code == 200
        and sale_status(sale_id) == "voided"
        and after == before + 1
        and stock() == after
        and (second.get_json() or {}).get("duplicate") is True,
        f"return={sent_back.status_code} early={too_soon.status_code} edit={edited.status_code} "
        f"resubmit={resent.status_code} approve={approved.status_code} second={second.status_code} "
        f"sale={sale_status(sale_id)} stock={stock()} body={approved.get_json()}",
    )

    reject_sale = sell("req-void-reject")
    reject_id = (reject_sale.get_json() or {}).get("sale_id")
    reject_stock = stock()
    reject_req = CLIENT.post("/api/sales/void-request", headers=cashier, json={
        "sale_id": reject_id, "reason": "Wrong item",
    })
    rejected = CLIENT.post(
        f"/api/approvals/{(reject_req.get_json() or {}).get('id')}/reject",
        headers=manager, json={"note": "Sale stands"},
    )
    check(
        "VOID-REJECT",
        rejected.status_code == 200 and sale_status(reject_id) == "completed" and stock() == reject_stock,
        f"reject={rejected.status_code} sale={sale_status(reject_id)} stock={stock()}",
    )

    direct = sell("req-direct")
    direct_id = (direct.get_json() or {}).get("sale_id")
    direct_before = stock()
    cashier_direct = CLIENT.post(f"/api/sales/{direct_id}/void-now", headers=cashier, json={"reason": "No"})
    super_direct = CLIENT.post(f"/api/sales/{direct_id}/void-now", headers=super_h, json={"reason": "Wrong receipt"})
    super_again = CLIENT.post(f"/api/sales/{direct_id}/void-now", headers=super_h, json={"reason": "Wrong receipt"})
    check(
        "VOID-DIRECT",
        cashier_direct.status_code == 403
        and super_direct.status_code == 200
        and sale_status(direct_id) == "voided"
        and stock() == direct_before + 1
        and super_again.status_code >= 400,
        f"cashier={cashier_direct.status_code} super={super_direct.status_code} again={super_again.status_code} stock={stock()}",
    )

    start_stock = stock()
    draft = CLIENT.post("/api/backdate-requests", headers=cashier, json={
        "business_date": YESTERDAY,
        "reason": "Power was out",
        "sales": [{
            "payment_method": "Cash",
            "amount_paid": 100,
            "lines": [{"product_id": product, "quantity": 1, "unit_price": 100, "discount": 0}],
        }],
    })
    draft_body = draft.get_json() or {}
    check("BACKDATE-DRAFT", draft.status_code == 200 and stock() == start_stock, f"draft={draft.status_code} stock={stock()}")
    submitted = CLIENT.post(
        f"/api/backdate-requests/{draft_body.get('id')}/submit",
        headers=cashier, json={"version": draft_body.get("version")},
    )
    self_ok = CLIENT.post(
        f"/api/backdate-requests/{draft_body.get('id')}/approve",
        headers=cashier, json={"version": (submitted.get_json() or {}).get("version")},
    )
    approved_bd = CLIENT.post(
        f"/api/backdate-requests/{draft_body.get('id')}/approve",
        headers=manager, json={"version": (submitted.get_json() or {}).get("version")},
    )
    posted_stock = stock()
    twice = CLIENT.post(
        f"/api/backdate-requests/{draft_body.get('id')}/approve",
        headers=manager, json={"version": (approved_bd.get_json() or {}).get("version")},
    )
    check(
        "BACKDATE-APPROVE-ONCE",
        submitted.status_code == 200
        and self_ok.status_code == 403
        and approved_bd.status_code == 200
        and posted_stock == start_stock - 1
        and stock() == posted_stock
        and (twice.get_json() or {}).get("already_approved") is True,
        f"submit={submitted.status_code} cashier={self_ok.status_code} manager={approved_bd.status_code} "
        f"twice={(twice.get_json() or {}).get('already_approved')} stock={stock()}",
    )

    adjust_before = stock()
    asked = CLIENT.post("/api/stock-adjustment-requests", headers=cashier, json={
        "product_id": product, "requested_qty": adjust_before - 2, "reason": "Count was short",
    })
    asked_id = (asked.get_json() or {}).get("id") or (asked.get_json() or {}).get("request_id")
    manager_adjust = CLIENT.post(
        f"/api/stock-adjustment-requests/{asked_id}/review",
        headers=manager, json={"decision": "approved", "pin": PIN},
    )
    super_adjust = CLIENT.post(
        f"/api/stock-adjustment-requests/{asked_id}/review",
        headers=super_h, json={"decision": "approved"},
    )
    adjusted = stock()
    super_again_adjust = CLIENT.post(
        f"/api/stock-adjustment-requests/{asked_id}/review",
        headers=super_h, json={"decision": "approved"},
    )
    check(
        "STOCK-APPROVE-ONCE",
        asked.status_code == 200
        and manager_adjust.status_code == 403
        and super_adjust.status_code == 200
        and adjusted == adjust_before - 2
        and stock() == adjusted
        and (super_again_adjust.get_json() or {}).get("duplicate") is True,
        f"ask={asked.status_code} manager={manager_adjust.status_code} super={super_adjust.status_code} "
        f"again={(super_again_adjust.get_json() or {}).get('duplicate')} before={adjust_before} after={stock()}",
    )
    failed = [row for row in RESULTS if row[1] == "FAIL"]
    print(f"checked={len(RESULTS)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        for item in patches:
            item.stop()
        ac._SCHEMA_READY = False
