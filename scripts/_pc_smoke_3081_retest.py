# -*- coding: utf-8 -*-
"""Retest remaining 3.0.81 smoke gaps with elevated offline firewall."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos_v3071_cert")
EXE = Path(r"C:\Program Files\MugoByte\MBT POS\MBT_POS.exe")
RULE = "MBT POS 3081 Offline Test"
R = []


def rec(a, s, n=""):
    R.append({"area": a, "status": s, "note": n})
    print(f"[{s}] {a}: {n}", flush=True)


def http_get(url, timeout=3):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def main():
    iv = Path(os.environ["LOCALAPPDATA"]) / "MugoByte" / "MBT POS" / "installed_version.json"
    data = json.loads(iv.read_text(encoding="utf-8-sig"))
    rec(
        "version.installed_json",
        "PASS" if data.get("version") == "3.0.82" else "FAIL",
        json.dumps(data)[:180],
    )

    # Confirm firewall rule present
    show = subprocess.run(
        ["netsh", "advfirewall", "firewall", "show", "rule", f"name={RULE}"],
        capture_output=True,
        text=True,
    )
    fw_ok = "Enabled:                              Yes" in (show.stdout or "")
    rec("offline.firewall", "PASS" if fw_ok else "FAIL", (show.stdout or "")[:120])

    subprocess.run(["taskkill", "/F", "/IM", "MBT_POS.exe"], capture_output=True)
    time.sleep(1)
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        [str(EXE)], cwd=str(EXE.parent), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    ready = None
    body = ""
    for _ in range(40):
        time.sleep(0.5)
        if proc.poll() is not None:
            break
        try:
            st, body = http_get("http://127.0.0.1:5050/api/version")
            if st == 200:
                ready = time.perf_counter() - t0
                break
        except Exception:
            pass
    rec(
        "offline.launch_blocked",
        "PASS" if proc.poll() is None and ready and ready < 20 else "FAIL",
        f"secs={ready} alive={proc.poll() is None}",
    )
    rec("version.api", "PASS" if "3.0.82" in body else "FAIL", body[:160])

    # Keep blocked for one more poll interval then cleanup
    time.sleep(35)
    still = proc.poll() is None
    rec("offline.still_alive_poll", "PASS" if still else "FAIL", f"alive={still}")

    subprocess.run(["taskkill", "/F", "/IM", "MBT_POS.exe"], capture_output=True)
    # Remove firewall elevated
    code = (
        f'netsh advfirewall firewall delete rule name="{RULE}"; '
        f'if ($LASTEXITCODE -eq 0) {{ "DEL_OK" }} else {{ "DEL_FAIL" }}'
    )
    tmp = Path(os.environ["TEMP"]) / "mbt_fw_del.ps1"
    tmp.write_text(code, encoding="utf-8")
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"{tmp}\"'",
        ],
        capture_output=True,
    )
    rec("offline.firewall_cleanup", "PASS", "requested delete")

    # Isolated stock + debt retest
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    os.chdir(ROOT)
    cert = Path(tempfile.mkdtemp(prefix="mbt_3081_fix_"))
    os.environ["MBT_DATA_ROOT"] = str(cert)
    os.environ["MBT_QA_ALLOW_DEV_BOOTSTRAP"] = "1"
    os.environ["MBT_BOOTSTRAP_ADMIN_PASSWORD"] = "admin123"
    os.environ["MBT_AUTO_SUPERADMIN_PIN"] = "1110"

    import backend.cloud.net_gate as ng

    ng.network_up = lambda *a, **k: False
    from desktop.utils.api_client import APIClient
    from _qa_local_auth import qa_login
    import bcrypt

    api = APIClient("http://127.0.0.1:5050")
    api.get_products()
    login = qa_login(api)
    api.set_token(login["token"])
    dbp = cert / "data" / "mbt_pos.db"
    h = bcrypt.hashpw(b"1110", bcrypt.gensalt()).decode()
    con = sqlite3.connect(str(dbp))
    con.execute(
        "INSERT OR REPLACE INTO system_settings(key,value) VALUES(?,?)",
        ("superadmin_pin_hash", h),
    )
    con.commit()
    con.close()

    created = api.create_product(
        {
            "name": "Fix Widget",
            "sku": f"FIX-{int(time.time())}",
            "price": 100.0,
            "cost_price": 40.0,
            "stock": 0,
            "min_stock": 1,
            "unit": "pcs",
        }
    )
    pid = created.get("id") or (created.get("product") or {}).get("id")
    api.receive_stock(int(pid), 20, notes="fix", unit_cost=40.0, pin="1110")
    cust = api.create_customer({"name": "Debt Cust", "phone": "0722222222"})
    cid = cust.get("id") or (cust.get("customer") or {}).get("id")

    adj = api.adjust_stock(int(pid), "remove", 1, reason="smoke adjust", pin="1110")
    rec("stock.adjust", "PASS" if adj and adj.get("success") else "FAIL", str(adj)[:160])

    credit = api.create_sale(
        {
            "items": [
                {
                    "product_id": int(pid),
                    "product_name": "Fix Widget",
                    "sku": "FIX",
                    "quantity": 1,
                    "unit_price": 100.0,
                    "discount": 0,
                    "total": 100.0,
                }
            ],
            "subtotal": 100,
            "total": 100,
            "payment_method": "Credit Sale",
            "amount_paid": 0,
            "change_amount": 0,
            "customer_id": cid,
        }
    )
    rec(
        "sales.credit_sale",
        "PASS" if credit and credit.get("success") else "FAIL",
        str(credit)[:160],
    )
    inv_id = credit.get("debt_invoice_id") if credit else None
    if not inv_id:
        con = sqlite3.connect(str(dbp))
        row = con.execute(
            "SELECT id FROM debt_invoices WHERE customer_id=? ORDER BY id DESC LIMIT 1",
            (int(cid),),
        ).fetchone()
        con.close()
        inv_id = row[0] if row else None
    if not inv_id:
        rec("other.debt_collect", "FAIL", f"no invoice credit={credit}")
    else:
        d = api.record_debt_payment(int(inv_id), 40.0, "Cash")
        rec(
            "other.debt_collect",
            "PASS" if d and d.get("success") else "FAIL",
            f"inv={inv_id} {str(d)[:140]}",
        )

    # Offline cash under net_gate
    t1 = time.perf_counter()
    cash = api.create_sale(
        {
            "items": [
                {
                    "product_id": int(pid),
                    "product_name": "Fix Widget",
                    "sku": "FIX",
                    "quantity": 1,
                    "unit_price": 100.0,
                    "discount": 0,
                    "total": 100.0,
                }
            ],
            "subtotal": 100,
            "total": 100,
            "payment_method": "Cash",
            "amount_paid": 100,
            "change_amount": 0,
            "customer_id": cid,
        }
    )
    dt = time.perf_counter() - t1
    rec(
        "offline.cash_sale",
        "PASS" if cash and cash.get("success") and dt < 5 else "FAIL",
        f"dt={dt:.3f} {str(cash)[:120]}",
    )

    fails = [x for x in R if x["status"] == "FAIL"]
    print("\n=== RETEST ===", flush=True)
    for x in R:
        print(f"{x['status']} {x['area']}: {x['note']}", flush=True)
    print(f"FAIL_COUNT={len(fails)}", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        subprocess.run(["taskkill", "/F", "/IM", "MBT_POS.exe"], capture_output=True)
        # best-effort cleanup
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE}"],
            capture_output=True,
        )
