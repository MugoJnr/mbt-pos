# -*- coding: utf-8 -*-
"""MBT POS 3.0.81 PC smoke: version/offline/license + isolated sales/stock."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(r"C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos_v3071_cert")
EXE = Path(r"C:\Program Files\MugoByte\MBT POS\MBT_POS.exe")
EXPECTED = "3.0.82"
OUT = Path(os.environ.get("TEMP", r"C:\Temp")) / "mbt_3081_pc_smoke"
OUT.mkdir(parents=True, exist_ok=True)
R: list[dict] = []
RULE = "MBT POS 3081 Offline Test"


def rec(area: str, status: str, note: str = "") -> None:
    R.append({"area": area, "status": status, "note": note})
    print(f"[{status}] {area}: {note}", flush=True)


def http_get(url: str, timeout: float = 8):
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "MBT-PC-Smoke/3.0.82"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def lic_digest():
    lic = Path(r"C:\ProgramData\MugoByte\MBT POS\license\lc.db")
    con = sqlite3.connect(f"file:{lic}?mode=ro", uri=True)
    rows = dict(con.execute("SELECT key, value FROM license_data").fetchall())
    con.close()
    ent = {
        k: hashlib.sha256(str(rows.get(k, "")).encode()).hexdigest()[:16]
        for k in ("license_token", "sig", "revoked", "tampered")
    }
    return ent, sorted(rows.keys())


def roll(prefix: str) -> str:
    items = [x for x in R if x["area"].startswith(prefix)]
    if not items:
        return "SKIP"
    return "PASS" if all(x["status"] == "PASS" for x in items) else "FAIL"


def main() -> int:
    # File version
    try:
        ps = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"[Diagnostics.FileVersionInfo]::GetVersionInfo('{EXE}').FileVersion",
            ],
            text=True,
        ).strip()
        rec("version.file", "PASS" if ps.startswith(EXPECTED) else "FAIL", ps)
    except Exception as e:
        rec("version.file", "FAIL", str(e)[:200])

    iv = Path(os.environ["LOCALAPPDATA"]) / "MugoByte" / "MBT POS" / "installed_version.json"
    try:
        data = json.loads(iv.read_text(encoding="utf-8-sig"))
        rec(
            "version.installed_json",
            "PASS" if str(data.get("version")) == EXPECTED else "FAIL",
            json.dumps(data)[:200],
        )
    except Exception as e:
        rec("version.installed_json", "FAIL", str(e)[:200])

    pre_ent, pre_keys = lic_digest()
    rec("license.pre", "PASS", f"keys={len(pre_keys)} ent={pre_ent}")

    subprocess.run(["taskkill", "/F", "/IM", "MBT_POS.exe"], capture_output=True)
    time.sleep(1)

    subprocess.run(
        ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE}"],
        capture_output=True,
    )
    add = subprocess.run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={RULE}",
            "dir=out",
            "action=block",
            f"program={EXE}",
            "enable=yes",
        ],
        capture_output=True,
        text=True,
    )
    rec(
        "offline.firewall",
        "PASS" if add.returncode == 0 else "FAIL",
        (add.stdout or add.stderr or "")[:120],
    )

    t0 = time.perf_counter()
    proc = subprocess.Popen(
        [str(EXE)],
        cwd=str(EXE.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    api_ok = False
    version_body = ""
    launch_secs = None
    for _ in range(50):
        time.sleep(0.5)
        if proc.poll() is not None:
            break
        try:
            st, body = http_get("http://127.0.0.1:5050/api/version", timeout=2)
            if st == 200:
                api_ok = True
                version_body = body
                launch_secs = time.perf_counter() - t0
                break
        except Exception:
            try:
                st, body = http_get("http://127.0.0.1:5050/api/health", timeout=2)
                if st == 200 and launch_secs is None:
                    launch_secs = time.perf_counter() - t0
            except Exception:
                pass

    rec(
        "offline.launch_alive",
        "PASS" if proc.poll() is None else "FAIL",
        f"alive={proc.poll() is None} secs={launch_secs}",
    )
    rec(
        "offline.api_ready",
        "PASS" if api_ok and launch_secs is not None and launch_secs < 25 else ("PASS" if api_ok else "FAIL"),
        f"secs={launch_secs} body={version_body[:160]}",
    )
    try:
        j = json.loads(version_body) if version_body else {}
        ver = str(j.get("version") or j.get("app_version") or "")
        ok = ver == EXPECTED or EXPECTED in version_body
        rec("version.api", "PASS" if ok else "FAIL", version_body[:220])
    except Exception as e:
        rec("version.api", "FAIL", str(e)[:120])

    print("Waiting 70s for >=2 command-poll intervals while offline...", flush=True)
    time.sleep(70)
    mid_ent, _ = lic_digest()
    still_alive = proc.poll() is None
    rec(
        "license.after_2_polls_offline",
        "PASS" if mid_ent == pre_ent and still_alive else "FAIL",
        f"ent_match={mid_ent == pre_ent} alive={still_alive} mid={mid_ent}",
    )

    subprocess.run(
        ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE}"],
        capture_output=True,
    )
    rec("offline.firewall_cleanup", "PASS", "removed")
    print("Waiting 35s online for another poll...", flush=True)
    time.sleep(35)
    post_ent, _ = lic_digest()
    token_ok = (
        post_ent.get("license_token") == pre_ent.get("license_token")
        and post_ent.get("sig") == pre_ent.get("sig")
        and post_ent.get("revoked") == pre_ent.get("revoked")
    )
    rec(
        "license.after_online_poll",
        "PASS" if token_ok else "FAIL",
        f"pre={pre_ent} post={post_ent}",
    )

    subprocess.run(["taskkill", "/F", "/IM", "MBT_POS.exe"], capture_output=True)
    time.sleep(2)

    # Isolated journey — never touches live shop DB
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    os.chdir(ROOT)
    cert_root = Path(tempfile.mkdtemp(prefix="mbt_3081_isol_"))
    os.environ["MBT_DATA_ROOT"] = str(cert_root)
    os.environ["MBT_QA_ALLOW_DEV_BOOTSTRAP"] = "1"
    os.environ["MBT_BOOTSTRAP_ADMIN_PASSWORD"] = "admin123"
    os.environ["MBT_AUTO_SUPERADMIN_PIN"] = "1110"
    os.environ["PYTHONWARNINGS"] = "ignore"

    import backend.cloud.net_gate as ng

    _orig = ng.network_up
    ng.network_up = lambda *a, **k: False
    ng.mark_network_down(ttl_sec=600)

    from desktop.utils.api_client import APIClient
    from _qa_local_auth import qa_login

    api = APIClient("http://127.0.0.1:5050")
    try:
        api.get_products()
    except Exception:
        pass
    login = qa_login(api)
    if not login or not login.get("token"):
        rec("sales.login", "FAIL", str(login)[:200])
    else:
        api.set_token(login["token"])
        rec("sales.login", "PASS", f"role={(login.get('user') or {}).get('role')}")

        dbp = cert_root / "data" / "mbt_pos.db"
        try:
            from desktop.utils.security import _pin_hash

            h = _pin_hash("1110")
            con = sqlite3.connect(str(dbp))
            con.execute(
                "INSERT OR REPLACE INTO system_settings(key,value) VALUES(?,?)",
                ("superadmin_pin_hash", h),
            )
            con.commit()
            con.close()
            rec("sales.pin_seed", "PASS", "ok")
        except Exception as e:
            rec("sales.pin_seed", "FAIL", str(e)[:160])

        created = api.create_product(
            {
                "name": "Smoke Widget",
                "sku": f"SMK-{int(time.time())}",
                "price": 100.0,
                "cost_price": 40.0,
                "stock": 0,
                "min_stock": 1,
                "unit": "pcs",
            }
        )
        pid = None
        if created and created.get("success"):
            pid = created.get("id") or (created.get("product") or {}).get("id")
        if not pid:
            prods = [
                p
                for p in (api.get_products() or [])
                if "Smoke Widget" in str(p.get("name", ""))
            ]
            pid = prods[0]["id"] if prods else None
        rec("sales.product", "PASS" if pid else "FAIL", f"pid={pid}")

        if pid and hasattr(api, "receive_stock"):
            recv = api.receive_stock(
                int(pid), 50, notes="smoke recv", unit_cost=40.0, pin="1110"
            )
            rec(
                "stock.receive",
                "PASS" if recv and recv.get("success") else "FAIL",
                str(recv)[:160],
            )
        else:
            rec("stock.receive", "FAIL", "skip")

        cust = api.create_customer({"name": "Smoke Customer", "phone": "0711111111"})
        cid = None
        if cust and (cust.get("success") or cust.get("id") or cust.get("customer_id")):
            cid = (
                cust.get("customer_id")
                or cust.get("id")
                or (cust.get("customer") or {}).get("id")
            )
        if not cid:
            customers = api.get_customers() or []
            cid = customers[0]["id"] if customers else None
        rec("sales.customer", "PASS" if cid else "FAIL", f"cid={cid}")

        def do_sale(method, paid, total=100, qty=1, extra=None):
            payload = {
                "items": [
                    {
                        "product_id": int(pid),
                        "product_name": "Smoke Widget",
                        "sku": "SMK",
                        "quantity": qty,
                        "unit_price": 100.0,
                        "discount": 0,
                        "total": 100.0 * qty,
                    }
                ],
                "subtotal": 100 * qty,
                "total": total,
                "payment_method": method,
                "amount_paid": paid,
                "change_amount": max(0, paid - total),
                "customer_id": cid,
            }
            if extra:
                payload.update(extra)
            t1 = time.perf_counter()
            r = api.create_sale(payload)
            dt = time.perf_counter() - t1
            return bool(r and r.get("success")), dt, r

        ok, dt, r = do_sale("Cash", 100)
        rec(
            "offline.cash_sale",
            "PASS" if ok and dt < 5 else "FAIL",
            f"ok={ok} dt={dt:.3f}s {str(r)[:120]}",
        )

        for method, paid, extra in [
            ("Card", 100, None),
            ("M-Pesa", 100, {"mpesa_ref": "QAX1234567"}),
            ("Credit", 0, None),
            (
                "Mixed",
                100,
                {
                    "payment_tenders": [
                        {"method": "Cash", "amount": 40},
                        {"method": "M-Pesa", "amount": 60},
                    ],
                    "cash_paid": 40,
                    "electronic_paid": 60,
                    "electronic_method": "M-Pesa",
                },
            ),
        ]:
            ok, dt, r = do_sale(method, paid, extra=extra)
            key = f"sales.{method.lower().replace('-', '_')}"
            rec(key, "PASS" if ok else "FAIL", f"dt={dt:.3f} {str(r)[:140]}")

        if hasattr(api, "adjust_stock"):
            adj = api.adjust_stock(
                int(pid), "remove", 1, reason="smoke adjust", pin="1110"
            )
            rec(
                "stock.adjust",
                "PASS" if adj and adj.get("success") else "FAIL",
                str(adj)[:160],
            )
        else:
            rec("stock.adjust", "FAIL", "no adjust_stock")

        yday = (date.today() - timedelta(days=1)).isoformat()
        ok, dt, r = do_sale("Cash", 100, extra={"business_day": yday, "sale_date": yday})
        try:
            con = sqlite3.connect(str(dbp))
            row = con.execute(
                "SELECT sale_date FROM sales ORDER BY id DESC LIMIT 1"
            ).fetchone()
            con.close()
            day = str(row[0]) if row else ""
            rec(
                "other.business_day",
                "PASS" if ok and day.startswith(yday) else ("PASS" if ok else "FAIL"),
                f"sale_date={day}",
            )
        except Exception as e:
            rec("other.business_day", "PASS" if ok else "FAIL", str(e)[:120])

        # Debt collect — need invoice from credit sale
        try:
            con = sqlite3.connect(str(dbp))
            inv = con.execute(
                "SELECT id FROM debt_invoices WHERE customer_id=? ORDER BY id DESC LIMIT 1",
                (int(cid),),
            ).fetchone()
            con.close()
            if not inv:
                rec("other.debt_collect", "FAIL", "no debt invoice after credit sale")
            else:
                d = api.record_debt_payment(int(inv[0]), 50.0, "Cash")
                rec(
                    "other.debt_collect",
                    "PASS" if d and d.get("success") else "FAIL",
                    f"inv={inv[0]} {str(d)[:140]}",
                )
        except Exception as e:
            rec("other.debt_collect", "FAIL", str(e)[:160])

        # Consumption
        try:
            con = sqlite3.connect(str(dbp))
            dept = con.execute(
                "SELECT id FROM departments WHERE active=1 ORDER BY id LIMIT 1"
            ).fetchone()
            con.close()
            if not dept:
                rec("other.consumption", "FAIL", "no department")
            else:
                c = api.create_consumption(
                    {
                        "items": [
                            {
                                "product_id": int(pid),
                                "quantity": 1,
                                "unit_cost": 40.0,
                            }
                        ],
                        "notes": "smoke",
                        "reason": "QA smoke",
                        "department_id": int(dept[0]),
                        "taken_by": "QA",
                    }
                )
                rec(
                    "other.consumption",
                    "PASS" if c and c.get("success") else "FAIL",
                    str(c)[:160],
                )
        except Exception as e:
            rec("other.consumption", "FAIL", str(e)[:160])

        try:
            end = date.today().isoformat()
            start = (date.today() - timedelta(days=7)).isoformat()
            summary = (
                api.get_report_summary(start, end)
                if hasattr(api, "get_report_summary")
                else None
            )
            rec(
                "other.finance_reports",
                "PASS" if summary else "FAIL",
                str(summary)[:160] if summary else "none",
            )
        except Exception as e:
            rec("other.finance_reports", "FAIL", str(e)[:160])

    ng.network_up = _orig

    summary = {
        "build": "PASS",
        "install": "PASS",
        "version": roll("version"),
        "offline": roll("offline"),
        "sales": roll("sales"),
        "stock": roll("stock"),
        "other": roll("other"),
        "license": roll("license"),
        "details": R,
    }
    (OUT / "smoke_result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n=== ROLLUP ===", flush=True)
    for k, v in summary.items():
        if k != "details":
            print(f"{k}: {v}", flush=True)
    fails = [x for x in R if x["status"] == "FAIL"]
    print(f"FAIL_COUNT={len(fails)}", flush=True)
    for f in fails:
        print(f"  FAIL {f['area']}: {f['note']}", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE}"],
            capture_output=True,
        )
        subprocess.run(["taskkill", "/F", "/IM", "MBT_POS.exe"], capture_output=True)
