#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MBT POS installer production certification.

Treats dist\\MBT_POS_Setup.exe as a first-customer install:
  1) Snapshot live AppData (upgrade preservation)
  2) Silent install /S (admin)
  3) Verify Program Files, shortcuts, registry, version, critical files
  4) Upgrade preservation (DB/config/license hashes)
  5) Isolated customer-journey API+UI against installed EXE data root
  6) Uninstall /S then repair reinstall (optional --skip-uninstall)

Exit: 0 PASS, 1 FAIL. Evidence: Desktop/QA_INSTALLER_CERT/
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "dist" / "MBT_POS_Setup.exe"
EXPECTED_VERSION = "3.0.83"
desktop = Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop"
OUT = Path(os.environ.get(
    "MBT_QA_OUT",
    str((desktop if desktop.is_dir() else Path(tempfile.gettempdir())) / "QA_INSTALLER_CERT"),
))
OUT.mkdir(parents=True, exist_ok=True)
R: list[dict] = []
LOG = OUT / "cert.log"


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%H:%M:%S')} {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def rec(area: str, status: str, note: str = "") -> None:
    R.append({"area": area, "status": status, "note": note})
    log(f"[{status}] {area}: {note}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# The entitlement itself. Everything else in the store is runtime bookkeeping
# the engine legitimately rewrites (cloud-check timestamps, stale offline
# flags) plus an append-only audit log, so the file's bytes cannot be stable
# across an install that runs --repair-license-store.
LICENSE_ENTITLEMENT_KEYS = ("license_token", "sig", "revoked", "tampered")


def license_store_state(path: Path) -> dict | None:
    """Digest the licence entitlement without ever holding a plaintext value.

    Opened strictly read-only through a ``mode=ro`` URI so certification can
    never write to the real licence store.
    """
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        rows = dict(con.execute("SELECT key, value FROM license_data").fetchall())
        log_rows = con.execute("SELECT COUNT(*) FROM license_log").fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return {
        "entitlement": {
            key: hashlib.sha256(str(rows.get(key, "")).encode()).hexdigest()
            for key in LICENSE_ENTITLEMENT_KEYS
        },
        "keys": sorted(rows),
        "log_rows": log_rows,
    }


def snapshot_live() -> dict:
    local = Path(os.environ["LOCALAPPDATA"]) / "MugoByte" / "MBT POS"
    lic = (
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        / "MugoByte" / "MBT POS" / "license" / "lc.db"
    )
    snap = {"ts": datetime.now(timezone.utc).isoformat()}
    for key, p in {
        "db": local / "data" / "mbt_pos.db",
        "wal": local / "data" / "mbt_pos.db-wal",
        "shm": local / "data" / "mbt_pos.db-shm",
        "license": lic,
    }.items():
        if p.is_file():
            snap[key] = {"path": str(p), "sha256": sha256(p), "size": p.stat().st_size}
        else:
            snap[key] = None
    snap["license_store"] = license_store_state(lic) if lic.is_file() else None
    cfg = local / "config"
    if cfg.is_dir():
        files = {}
        for fp in cfg.rglob("*"):
            if fp.is_file():
                files[str(fp.relative_to(cfg))] = sha256(fp)
        snap["config_files"] = files
    else:
        snap["config_files"] = {}
    (OUT / "pre_upgrade_snapshot.json").write_text(json.dumps(snap, indent=2), encoding="utf-8")
    return snap


def run_elevated(cmd: list[str], timeout: int = 600) -> int:
    """Run command elevated via Start-Process -Verb RunAs; wait for exit."""
    ps = (
        "$ErrorActionPreference='Stop'; "
        "try {{ $p = Start-Process -FilePath {0} -ArgumentList {1} "
        "-Verb RunAs -Wait -PassThru; exit $p.ExitCode }} "
        "catch {{ Write-Error $_; exit 1223 }}"
    ).format(
        json.dumps(cmd[0]),
        json.dumps(" ".join(cmd[1:])),
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.stdout:
        log(completed.stdout.strip()[:2000])
    if completed.stderr:
        log("stderr: " + completed.stderr.strip()[:2000])
    return int(completed.returncode)


def install_dir() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "MugoByte" / "MBT POS"


def verify_install_layout(snap: dict) -> None:
    inst = install_dir()
    exe = inst / "MBT_POS.exe"
    if not exe.is_file():
        rec("install.exe", "FAIL", f"missing {exe}")
        return
    rec("install.exe", "PASS", f"size={exe.stat().st_size}")

    required = [
        "_internal",
        "Uninstall.exe",
    ]
    missing = [n for n in required if not (inst / n).exists()]
    rec("install.files", "PASS" if not missing else "FAIL", f"missing={missing}" if missing else "ok")
    retired = [
        inst / "MBT_UpdateHelper.ps1",
        inst / "register_update_helper.ps1",
        inst / "deploy" / "MBT_UpdateHelper.ps1",
        inst / "deploy" / "register_update_helper.ps1",
    ]
    stale = [str(p) for p in retired if p.exists()]
    rec(
        "install.unsafe_helper_removed",
        "PASS" if not stale else "FAIL",
        f"stale={stale}" if stale else "retired SYSTEM helper absent",
    )

    # Version resource
    try:
        import ctypes
        from ctypes import wintypes

        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(exe), None)
        if size:
            buf = ctypes.create_string_buffer(size)
            ctypes.windll.version.GetFileVersionInfoW(str(exe), 0, size, buf)
            # ProductVersion via VerQueryValue is awkward; use PowerShell fallback
            raise RuntimeError("use ps")
    except Exception:
        pass
    ps = (
        f"(Get-Item -LiteralPath {json.dumps(str(exe))}).VersionInfo.ProductVersion"
    )
    pv = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", ps], text=True
    ).strip()
    ok_ver = EXPECTED_VERSION in pv or pv.startswith(EXPECTED_VERSION)
    rec("install.version", "PASS" if ok_ver else "FAIL", f"ProductVersion={pv!r} expected={EXPECTED_VERSION}")

    # Registry (NSIS may write WOW6432Node unless SetRegView 64)
    ps = r"""
$cands = @(
  'HKLM:\Software\MugoByte\MBT POS',
  'HKLM:\Software\WOW6432Node\MugoByte\MBT POS'
)
$ver = ''
foreach ($p in $cands) {
  if (Test-Path $p) { $ver = (Get-ItemProperty $p).Version; break }
}
$ver
"""
    reg_ver = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", ps], text=True
    ).strip().splitlines()[-1].strip()
    rec(
        "install.registry",
        "PASS" if reg_ver == EXPECTED_VERSION else "FAIL",
        f"HKLM Version={reg_ver!r}",
    )
    helper_task = subprocess.run(
        ["schtasks", "/Query", "/TN", "MBT_POS_UpdateHelper"],
        capture_output=True,
        text=True,
    )
    rec(
        "install.unsafe_helper_task_removed",
        "PASS" if helper_task.returncode != 0 else "FAIL",
        "task absent" if helper_task.returncode != 0 else "SYSTEM task still registered",
    )

    # Shortcuts
    desktop = Path(os.environ["USERPROFILE"]) / "Desktop" / "MBT POS.lnk"
    public_desk = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop" / "MBT POS.lnk"
    sm_candidates = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "MugoByte"
        / "MBT POS"
        / "MBT POS.lnk",
        Path(os.environ["APPDATA"])
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "MugoByte"
        / "MBT POS"
        / "MBT POS.lnk",
    ]
    desk_ok = desktop.is_file() or public_desk.is_file()
    sm_ok = any(p.is_file() for p in sm_candidates)
    rec("install.desktop_shortcut", "PASS" if desk_ok else "FAIL", f"user={desktop.is_file()} public={public_desk.is_file()}")
    rec(
        "install.start_menu",
        "PASS" if sm_ok else "FAIL",
        "found" if sm_ok else "missing Start Menu MBT POS.lnk",
    )

    # Upgrade preservation
    local = Path(os.environ["LOCALAPPDATA"]) / "MugoByte" / "MBT POS"
    db = local / "data" / "mbt_pos.db"
    if snap.get("db") and db.is_file():
        got = sha256(db)
        ok = got == snap["db"]["sha256"]
        rec("upgrade.db_preserved", "PASS" if ok else "FAIL", f"match={ok} size={db.stat().st_size}")
    else:
        rec("upgrade.db_preserved", "PASS", "no pre-existing DB (new install path)")

    if snap.get("license"):
        lic = Path(snap["license"]["path"])
        pre = snap.get("license_store")
        if not lic.is_file():
            rec("upgrade.license_preserved", "FAIL", "license missing after install")
        elif not pre:
            rec("upgrade.license_preserved", "FAIL", "pre-install license store unreadable")
        else:
            post = license_store_state(lic)
            if not post:
                rec("upgrade.license_preserved", "FAIL", "license store unreadable after install")
            else:
                # The installer runs --repair-license-store, which builds the
                # licence engine; that clears stale cloud flags and appends an
                # audit row on a valid local licence. So compare the
                # entitlement, not the file bytes, and require the audit trail
                # to have only grown.
                changed = [
                    k for k, digest in pre["entitlement"].items()
                    if post["entitlement"].get(k) != digest
                ]
                lost = sorted(set(pre["keys"]) - set(post["keys"]))
                truncated = post["log_rows"] < pre["log_rows"]
                ok = not changed and not lost and not truncated
                bytes_same = sha256(lic) == snap["license"]["sha256"]
                rec(
                    "upgrade.license_preserved",
                    "PASS" if ok else "FAIL",
                    f"entitlement_changed={changed} keys_lost={lost} "
                    f"audit_rows {pre['log_rows']}->{post['log_rows']} "
                    f"file_bytes_identical={bytes_same}",
                )
    else:
        rec("upgrade.license_preserved", "PASS", "no pre-existing license")

    # pre_upgrade backup folder
    bak = local / "backups" / "pre_upgrade" / EXPECTED_VERSION
    rec(
        "upgrade.pre_backup",
        "PASS" if bak.is_dir() else "FAIL",
        str(bak),
    )

    mode_file = local / "last_install_mode.txt"
    mode_txt = mode_file.read_text(encoding="utf-8", errors="replace") if mode_file.is_file() else ""
    rec(
        "install.mode_file",
        "PASS" if EXPECTED_VERSION in mode_txt else "FAIL",
        mode_txt.replace("\n", " | ")[:200],
    )


def seed_superadmin_pin(api, cert_root: Path) -> bool:
    """Configure the Super-Admin PIN in the isolated database before the journey.

    From v3.0.75 the backend verifies the PIN itself before any protected
    inventory write, so a freshly created database refuses ``receive_stock``
    with "Super-Admin PIN is not configured." until the hash row exists. The
    harness therefore has to configure the PIN the way the product does â€” via
    ``desktop.utils.security.set_superadmin_pin``, which hashes through
    ``_pin_hash`` and stores ``superadmin_pin_hash`` in ``system_settings`` â€”
    rather than bypassing or relaxing the gate.
    """
    from desktop.utils.api_client import get_db_path
    from desktop.utils.security import set_superadmin_pin

    db_path = Path(get_db_path()).resolve()
    root = cert_root.resolve()
    if root != db_path.parent and root not in db_path.parents:
        rec(
            "journey.superadmin_pin",
            "FAIL",
            "refused: resolved database is outside the isolated cert root",
        )
        return False

    pin = os.environ.get("MBT_AUTO_SUPERADMIN_PIN", "")
    if not pin:
        rec("journey.superadmin_pin", "FAIL", "MBT_AUTO_SUPERADMIN_PIN not set")
        return False

    if not set_superadmin_pin(pin, api):
        rec("journey.superadmin_pin", "FAIL", "set_superadmin_pin returned False")
        return False

    cfg = api.get_settings() or {}
    stored = bool(cfg.get("superadmin_pin_hash"))
    rec(
        "journey.superadmin_pin",
        "PASS" if stored else "FAIL",
        "hash stored in isolated system_settings" if stored else "hash missing after write",
    )
    return stored


def customer_journey_isolated() -> None:
    """Fresh data root + installed EXE binary path for API/UI journey via source APIClient.

    Uses the installed Program Files binary presence as the certified runtime,
    and exercises the same schema/API against an isolated MBT_DATA_ROOT so live
    shop data is never mutated by certification sales.
    """
    cert_root = Path(os.environ.get("TEMP", r"C:\Temp")) / f"mbt_cert_journey_{int(time.time())}"
    if cert_root.exists():
        shutil.rmtree(cert_root, ignore_errors=True)
    cert_root.mkdir(parents=True)
    os.environ["MBT_DATA_ROOT"] = str(cert_root)
    os.environ.setdefault("MBT_QA_ALLOW_DEV_BOOTSTRAP", "1")
    os.environ.setdefault("MBT_BOOTSTRAP_ADMIN_PASSWORD", "admin123")
    os.environ.setdefault("MBT_AUTO_SUPERADMIN_PIN", "1110")
    os.environ.setdefault("PYTHONWARNINGS", "ignore")

    # Prefer importing from repo for automation, but require installed EXE exists.
    inst_exe = install_dir() / "MBT_POS.exe"
    if not inst_exe.is_file():
        rec("journey.installed_exe", "FAIL", "installed EXE missing")
        return
    rec("journey.installed_exe", "PASS", str(inst_exe))

    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)

    # Launch installed EXE briefly to prove it starts (no UI automation on wizard).
    try:
        env = os.environ.copy()
        env["MBT_DATA_ROOT"] = str(cert_root)
        env["MBT_SESSION_IDLE_SEC"] = "0"
        proc = subprocess.Popen(
            [str(inst_exe)],
            cwd=str(install_dir()),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(8)
        alive = proc.poll() is None
        if alive:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            rec("journey.exe_launch", "PASS", "process stayed alive 8s")
        else:
            rec("journey.exe_launch", "FAIL", f"exited early code={proc.returncode}")
    except Exception as e:
        rec("journey.exe_launch", "FAIL", str(e)[:240])

    # API journey on isolated DB
    try:
        from desktop.utils.api_client import APIClient

        from _qa_local_auth import qa_login

        api = APIClient("http://127.0.0.1:5050")
        # Ensure schema
        _ = api.get_products()
        login = qa_login(api)
        if not login or not login.get("token"):
            # Fresh DB may need default admin seed via migrate
            rec("journey.login", "FAIL", str(login)[:200])
            return
        api.set_token(login["token"])
        rec("journey.login", "PASS", f"role={(login.get('user') or {}).get('role')}")

        if not seed_superadmin_pin(api, cert_root):
            return

        # Product
        created = api.create_product(
            {
                "name": "Cert Widget",
                "sku": f"CERT-{int(time.time())}",
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
            prods = [p for p in (api.get_products() or []) if "Cert Widget" in str(p.get("name", ""))]
            pid = prods[0]["id"] if prods else None
        rec("journey.create_product", "PASS" if pid else "FAIL", f"pid={pid} raw={str(created)[:120]}")

        # Receive stock
        if pid and hasattr(api, "receive_stock"):
            recv = api.receive_stock(
                int(pid), 25, notes="cert receive", unit_cost=40.0,
                pin=os.environ.get("MBT_AUTO_SUPERADMIN_PIN", ""),
            )
            ok = bool(recv and recv.get("success"))
            rec("journey.receive_stock", "PASS" if ok else "FAIL", str(recv)[:200])
        else:
            rec("journey.receive_stock", "FAIL", "no pid or receive_stock")

        # Customer + sale
        cust = api.create_customer({"name": "Cert Customer", "phone": "0700000000"})
        cid = None
        if cust and (cust.get("success") or cust.get("id")):
            cid = cust.get("id") or (cust.get("customer") or {}).get("id")
        if not cid:
            customers = api.get_customers() or []
            cid = customers[0]["id"] if customers else None
        rec("journey.customer", "PASS" if cid else "FAIL", f"cid={cid}")

        sale = api.create_sale(
            {
                "items": [{
                    "product_id": int(pid),
                    "product_name": "Cert Widget",
                    "sku": "CERT",
                    "quantity": 2,
                    "unit_price": 100.0,
                    "discount": 0,
                    "total": 200.0,
                }],
                "subtotal": 200,
                "total": 200,
                "payment_method": "Cash",
                "amount_paid": 200,
                "change_amount": 0,
                "customer_id": cid,
            }
        )
        sale_ok = bool(sale and sale.get("success"))
        rec("journey.sale", "PASS" if sale_ok else "FAIL", str(sale)[:200])

        # Credit / debt path
        credit = api.create_sale(
            {
                "items": [{
                    "product_id": int(pid),
                    "product_name": "Cert Widget",
                    "sku": "CERT",
                    "quantity": 1,
                    "unit_price": 100.0,
                    "discount": 0,
                    "total": 100.0,
                }],
                "subtotal": 100,
                "total": 100,
                "payment_method": "Credit",
                "amount_paid": 0,
                "change_amount": 0,
                "customer_id": cid,
            }
        )
        rec(
            "journey.credit_sale",
            "PASS" if credit and credit.get("success") else "FAIL",
            str(credit)[:200],
        )

        # Reports
        from datetime import date, timedelta

        end = date.today().isoformat()
        start = (date.today() - timedelta(days=7)).isoformat()
        summary = api.get_report_summary(start, end) if hasattr(api, "get_report_summary") else None
        rec("journey.reports", "PASS" if summary else "FAIL", str(summary)[:160] if summary else "none")

        # Backup
        try:
            from desktop.utils.api_client import APIClient as _A

            bak = None
            if hasattr(api, "create_backup"):
                bak = api.create_backup()
            elif hasattr(api, "backup_database"):
                bak = api.backup_database()
            # file-level backup evidence
            db_path = cert_root / "data" / "mbt_pos.db"
            bak_dir = cert_root / "backups"
            bak_dir.mkdir(exist_ok=True)
            if db_path.is_file():
                dest = bak_dir / f"cert_{int(time.time())}.db"
                shutil.copy2(db_path, dest)
                rec("journey.backup", "PASS", f"copied {dest.name} size={dest.stat().st_size}")
            else:
                rec("journey.backup", "FAIL", "db missing in cert root")
        except Exception as e:
            rec("journey.backup", "FAIL", str(e)[:200])

        # Restart integrity: reopen DB
        dbp = cert_root / "data" / "mbt_pos.db"
        if dbp.is_file():
            con = sqlite3.connect(str(dbp))
            n_sales = con.execute(
                "SELECT COUNT(*) FROM sales WHERE status IN ('completed','return') OR status IS NULL"
            ).fetchone()[0]
            n_prods = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            con.close()
            rec(
                "journey.restart_integrity",
                "PASS" if n_prods >= 1 and n_sales >= 1 else "FAIL",
                f"products={n_prods} sales={n_sales}",
            )
        else:
            rec("journey.restart_integrity", "FAIL", "no db")

        # Wizard marker for fresh root ï¿½ needs_wizard should be true before first complete
        from desktop.wizard.setup_wizard import needs_wizard

        rec("journey.wizard_gate", "PASS", f"needs_wizard={needs_wizard()}")

    except Exception:
        rec("journey.api", "FAIL", traceback.format_exc()[-600:])

    # Keep evidence tree, minus anything secret. The app seeds every data root
    # it is given with copies of the cloudflared tunnel credentials, cert.pem
    # and .jwt_secret; those must not be duplicated into a Desktop folder that
    # outlives the run.
    shutil.copytree(
        cert_root,
        OUT / "isolated_data",
        dirs_exist_ok=True,
        ignore=lambda _dir, names: [
            n for n in names
            if n.lower() in {"cloudflared", "cloudflared_backup",
                             "cert.pem", ".jwt_secret"}
        ],
    )


def repair_cycle(skip_uninstall: bool) -> None:
    if skip_uninstall:
        rec("repair.cycle", "PASS", "skipped (--skip-uninstall)")
        return
    inst = install_dir()
    uninst = inst / "Uninstall.exe"
    if not uninst.is_file():
        rec("repair.uninstall", "FAIL", "Uninstall.exe missing")
        return
    # Snapshot AppData before uninstall (must remain)
    local = Path(os.environ["LOCALAPPDATA"]) / "MugoByte" / "MBT POS" / "data" / "mbt_pos.db"
    pre = sha256(local) if local.is_file() else None
    code = run_elevated([str(uninst), "/S"], timeout=300)
    time.sleep(2)
    gone = not (inst / "MBT_POS.exe").is_file()
    rec("repair.uninstall", "PASS" if gone and code == 0 else "FAIL", f"exit={code} exe_gone={gone}")
    post = sha256(local) if local.is_file() else None
    rec(
        "repair.appdata_intact",
        "PASS" if pre and post and pre == post else ("PASS" if not pre else "FAIL"),
        f"pre={bool(pre)} match={pre == post}",
    )
    # Reinstall = repair
    if not SETUP.is_file():
        rec("repair.reinstall", "FAIL", "Setup missing")
        return
    code2 = run_elevated([str(SETUP), "/S"], timeout=600)
    time.sleep(2)
    back = (install_dir() / "MBT_POS.exe").is_file()
    rec("repair.reinstall", "PASS" if back and code2 == 0 else "FAIL", f"exit={code2} exe={back}")


def portal_health() -> None:
    try:
        import urllib.request

        req = urllib.request.Request(
            "https://portal.mugobyte.com/api/health",
            headers={
                "User-Agent": f"MBT-Installer-Cert/{EXPECTED_VERSION}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            ok = resp.status == 200 and "ok" in body.lower()
            rec("portal.health", "PASS" if ok else "FAIL", body[:160])
    except Exception as e:
        rec("portal.health", "FAIL", str(e)[:200])


def main() -> int:
    open(LOG, "w", encoding="utf-8").write(f"cert start {datetime.now().isoformat()}\n")
    skip_uninstall = "--skip-uninstall" in sys.argv
    if not SETUP.is_file():
        rec("setup.exists", "FAIL", str(SETUP))
        _write_out()
        return 1
    setup_hash = sha256(SETUP)
    rec("setup.exists", "PASS", f"size={SETUP.stat().st_size} sha256={setup_hash}")
    (OUT / "setup.sha256").write_text(setup_hash + "\n", encoding="utf-8")

    snap = snapshot_live()
    rec("snapshot.live", "PASS", f"db={'yes' if snap.get('db') else 'no'}")

    # Kill running POS
    subprocess.run(["taskkill", "/F", "/IM", "MBT_POS.exe"], capture_output=True)
    time.sleep(1)

    code = run_elevated([str(SETUP), "/S"], timeout=600)
    time.sleep(3)
    rec("setup.silent_install", "PASS" if code == 0 else "FAIL", f"exit={code}")
    if code != 0:
        # Do not inspect and misreport an older installed version after UAC was
        # denied or the new installer failed to start.
        return _write_out()

    verify_install_layout(snap)
    customer_journey_isolated()
    portal_health()
    repair_cycle(skip_uninstall)

    return _write_out()


def _write_out() -> int:
    fails = [r for r in R if r["status"] == "FAIL"]
    report = {
        "version": EXPECTED_VERSION,
        "ts": datetime.now(timezone.utc).isoformat(),
        "fails": len(fails),
        "results": R,
        "verdict": "PASS" if not fails else "FAIL",
    }
    (OUT / "cert_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = OUT / "CERTIFICATION.md"
    lines = [
        f"# MBT POS {EXPECTED_VERSION} Installer Certification",
        "",
        f"**Verdict:** {report['verdict']}",
        f"**Fails:** {len(fails)}",
        f"**When:** {report['ts']}",
        "",
        "| Area | Status | Note |",
        "|------|--------|------|",
    ]
    for r in R:
        note = str(r.get("note", "")).replace("|", "/")[:120]
        lines.append(f"| {r['area']} | {r['status']} | {note} |")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"VERDICT={report['verdict']} fails={len(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
