"""Read-only final system checkup for MBT POS v3.0.76 rollout."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

INSTALLED = Path(r"C:\Program Files\MugoByte\MBT POS\MBT_POS.exe")
DATA_ROOT = Path(os.environ.get("LOCALAPPDATA", "")) / "MugoByte" / "MBT POS"
LIVE_DB = DATA_ROOT / "data" / "mbt_pos.db"
VERSION_JSON = ROOT / "version.json"
DIST_SETUP = ROOT / "dist" / "MBT_POS_Setup.exe"
DIST_SHA = ROOT / "dist" / "MBT_POS_Setup.exe.sha256"

EXPECTED_EXE_SHA = "e54c2fc3eb4a096325301918671b90853baae0dcb757297c9d9b28f40a315120"
EXPECTED_SETUP_SHA = "e4c060e89ab1d85f2f57742bd3acfd266042ad855995713fdacee43946a2cadf"
EXPECTED_DB_SHA = "1d9a0d8028604068a311ec404bed2203269adc96ccc10baf5b66e0ceab2949c7"
EXPECTED_DB_SIZE = 757760


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def status(name: str, ok: bool, detail: str = "") -> dict:
    return {"check": name, "ok": ok, "detail": detail}


def check_installed() -> list[dict]:
    out: list[dict] = []
    if not INSTALLED.is_file():
        return [status("installed_exe", False, "MBT_POS.exe missing")]
    ver = INSTALLED.stat()
    product = __import__("win32api", fromlist=["GetFileVersionInfo"]).GetFileVersionInfo(
        str(INSTALLED), "\\"
    ) if False else None
    try:
        import win32api  # type: ignore
        info = win32api.GetFileVersionInfo(str(INSTALLED), "\\")
        ms = info["FileVersionMS"]
        ls = info["FileVersionLS"]
        pv = f"{win32api.HIWORD(ms)}.{win32api.LOWORD(ms)}.{win32api.HIWORD(ls)}.{win32api.LOWORD(ls)}"
    except Exception:
        pv = "unknown"
    exe_sha = sha256_file(INSTALLED)
    out.append(status("installed_version", pv.startswith("3.0.76"), pv))
    out.append(status("installed_exe_sha", exe_sha == EXPECTED_EXE_SHA, exe_sha[:16] + "..."))
    out.append(status("installed_exe_size", INSTALLED.stat().st_size > 10_000_000, str(INSTALLED.stat().st_size)))
    return out


def check_live_db() -> list[dict]:
    out: list[dict] = []
    if not LIVE_DB.is_file():
        return [status("live_db", False, "missing")]
    db_sha = sha256_file(LIVE_DB)
    out.append(status("live_db_size", LIVE_DB.stat().st_size == EXPECTED_DB_SIZE, str(LIVE_DB.stat().st_size)))
    out.append(status("live_db_sha", db_sha == EXPECTED_DB_SHA, db_sha[:16] + "..."))
    try:
        conn = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
        out.append(status("live_db_integrity", ic == "ok", ic))
        counts = {}
        for table in ("users", "products", "customers", "sales", "stock_movements"):
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except Exception:
                counts[table] = -1
        out.append(status("live_db_counts", counts.get("sales", -1) == 32, json.dumps(counts)))
        qa = conn.execute(
            "SELECT COUNT(*) FROM products WHERE name LIKE 'QA_%' OR sku LIKE 'QA_%'"
        ).fetchone()[0]
        out.append(status("live_db_no_qa_rows", qa == 0, f"qa_products={qa}"))
        conn.close()
    except Exception as e:
        out.append(status("live_db_read", False, str(e)))
    return out


def check_license() -> list[dict]:
    out: list[dict] = []
    for name in ("device.id", "crypto.secret", "lc.db"):
        p = DATA_ROOT / name
        out.append(status(f"license_{name}", p.is_file(), f"size={p.stat().st_size if p.is_file() else 0}"))
    try:
        from licensing.license_engine import collect_activation_diagnostics
        diag = collect_activation_diagnostics()
        active = bool(diag.get("license_active") or diag.get("activated"))
        out.append(status("license_active", active, json.dumps({
            k: diag.get(k) for k in (
                "license_active", "activated", "device_id", "shop_name",
                "license_status", "offline_valid", "pending_commands",
            ) if k in diag
        }, default=str)[:500]))
    except Exception as e:
        out.append(status("license_diagnostics", False, str(e)))
    return out


def check_github_release() -> list[dict]:
    out: list[dict] = []
    url = "https://api.github.com/repos/MugoJnr/mbt-pos/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "MBT-POS-checkup/3.0.76"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    tag = data.get("tag_name", "")
    out.append(status("github_latest_tag", tag == "v3.0.76", tag))
    assets = {a["name"]: a for a in data.get("assets", [])}
    setup = assets.get("MBT_POS_Setup.exe")
    sidecar = assets.get("MBT_POS_Setup.exe.sha256")
    out.append(status("github_setup_asset", bool(setup), str(setup.get("size") if setup else "missing")))
    out.append(status("github_sha_sidecar", bool(sidecar), "present" if sidecar else "missing"))
    if setup:
        digest = (setup.get("digest") or "").replace("sha256:", "")
        out.append(status("github_setup_digest", digest == EXPECTED_SETUP_SHA, digest[:16] + "..."))
    return out


def check_updater_path() -> list[dict]:
    out: list[dict] = []
    try:
        from backend.updater import UpdateChecker, resolve_release_checksum, _ensure_ssl_certs
        _ensure_ssl_certs()
        uc = UpdateChecker("3.0.76")
        info = uc._fetch_release_info()
        if not info:
            return [status("updater_fetch", False, "no info")]
        remote = info.get("version", "")
        chk = info.get("checksum_sha256", "")
        out.append(status("updater_current_uptodate", remote == "3.0.76" and not __import__(
            "backend.updater", fromlist=["_version_gt"])._version_gt(remote, "3.0.76"), f"remote={remote}"))
        out.append(status("updater_checksum_resolved", bool(chk), chk[:16] + "..." if chk else "missing"))
        out.append(status("updater_asset_url", bool(info.get("asset_url")), "ok" if info.get("asset_url") else "missing"))
    except Exception as e:
        out.append(status("updater_fetch", False, str(e)))
    log = Path(os.environ.get("TEMP", "")) / "mbt_update.log"
    if log.is_file():
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]
        ok_line = any("Install OK v3.0.76" in ln for ln in tail)
        out.append(status("update_log_install_ok", ok_line, " | ".join(t.strip() for t in tail[-2:])))
    else:
        out.append(status("update_log", False, "missing"))
    return out


def check_build_artifacts() -> list[dict]:
    out: list[dict] = []
    if VERSION_JSON.is_file():
        vj = json.loads(VERSION_JSON.read_text(encoding="utf-8"))
        out.append(status("version_json", vj.get("version") == "3.0.76", vj.get("version", "?")))
    else:
        out.append(status("version_json", False, "missing"))
    if DIST_SETUP.is_file():
        out.append(status("dist_setup_sha", sha256_file(DIST_SETUP) == EXPECTED_SETUP_SHA, "match"))
    else:
        out.append(status("dist_setup", False, "missing"))
    if DIST_SHA.is_file():
        line = DIST_SHA.read_text(encoding="utf-8").strip().split()[0]
        out.append(status("dist_sha_sidecar", line == EXPECTED_SETUP_SHA, line[:16] + "..."))
    return out


def check_cloud_readonly() -> list[dict]:
    out: list[dict] = []
    try:
        from backend.cloud_backup.paths import (
            is_cloud_configured, is_logged_in, load_cloud_config, load_identity,
            backup_state_path, load_json,
        )
        out.append(status("cloud_configured", is_cloud_configured(), ""))
        out.append(status("cloud_logged_in", is_logged_in(), ""))
        ident = load_identity()
        out.append(status("cloud_device_id", bool(ident.get("device_id")), str(ident.get("device_id", ""))[:12] + "..."))
        st = load_json(backup_state_path(), {})
        out.append(status("cloud_backup_state", True, json.dumps({
            k: st.get(k) for k in (
                "last_success_at", "last_error", "last_reason", "queue_depth",
            ) if k in st
        }, default=str)[:300] or "empty"))
    except Exception as e:
        out.append(status("cloud_readonly", False, str(e)))
    try:
        from backend.cloudflare_setup import get_tunnel_status_summary
        ts = get_tunnel_status_summary()
        out.append(status("tunnel_status", ts.get("status") in ("ACTIVE", "INACTIVE", "DEGRADED"), json.dumps(ts, default=str)[:400]))
    except Exception as e:
        try:
            from backend.cloudflare_setup import run_diagnostics
            rep = run_diagnostics()
            out.append(status("cloudflare_diag", rep.get("overall") != "FAIL", json.dumps(rep, default=str)[:400]))
        except Exception as e2:
            out.append(status("cloudflare", False, f"{e}; {e2}"))
    return out


def main() -> int:
    sections = {
        "installed": check_installed(),
        "live_db": check_live_db(),
        "license": check_license(),
        "github": check_github_release(),
        "updater": check_updater_path(),
        "build": check_build_artifacts(),
        "cloud": check_cloud_readonly(),
    }
    report = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sections": sections,
    }
    all_checks = [c for sec in sections.values() for c in sec]
    failed = [c for c in all_checks if not c["ok"]]
    report["summary"] = {
        "total": len(all_checks),
        "passed": len(all_checks) - len(failed),
        "failed": len(failed),
        "failures": failed,
        "ready": len(failed) == 0,
    }
    out_path = ROOT / "_qa_v3075_evidence" / "final_system_checkup.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    for f in failed:
        print(f"FAIL: {f['check']} — {f['detail']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
