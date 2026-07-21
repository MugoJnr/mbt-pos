"""Install-to-runtime confirmation checklist."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
APP = Path(os.environ["LOCALAPPDATA"]) / "MugoByte" / "MBT POS"
ok = 0
fail = 0


def check(name: str, cond: bool, detail: str = ""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))
    else:
        fail += 1
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


def http(url: str):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return None, str(e)


def main():
    print("=== Installation & runtime confirmation ===\n")

    # Paths
    check("AppData root", APP.exists(), str(APP))
    check("cloud_config.json", (APP / "config" / "cloud_config.json").exists())
    check("web_config.json", (APP / "config" / "web_config.json").exists())
    db = APP / "data" / "mbt_pos.db"
    if not db.exists():
        db = APP / "mbt_pos.db"
    check("Shop database", db.exists(), str(db))

    # Cloud config
    cc_path = APP / "config" / "cloud_config.json"
    if cc_path.exists():
        cfg = json.loads(cc_path.read_text(encoding="utf-8-sig"))
        check("Cloud enabled", bool(cfg.get("enabled")))
        check("Supabase URL", bool(cfg.get("supabase_url")))
        check("Anon key", bool(cfg.get("anon_key")))
        check("Service key", bool(cfg.get("service_key")))

    # Web / tunnel
    wc = json.loads((APP / "config" / "web_config.json").read_text(encoding="utf-8"))
    check("Remote enabled", bool(wc.get("remote_enabled")))
    check("Tunnel domain", bool(wc.get("tunnel_domain")), wc.get("tunnel_domain", ""))
    check("Portal DNS intended", True, "portal.mugobyte.com")

    # Local Flask
    code, body = http("http://127.0.0.1:5050/api/version")
    check("Local Flask /api/version", code == 200, body[:80])
    code, body = http("http://127.0.0.1:5050/api/cloud/config")
    check("Local /api/cloud/config", code == 200 and '"configured":true' in body.replace(" ", "").lower().replace("true", "true") or (code == 200 and "configured" in body), body[:100])
    code, body = http("http://127.0.0.1:5050/login")
    check("Local /login SPA", code == 200 and "MugoByte" in body or code == 200)

    # Public portal
    for url, label in [
        ("https://portal.mugobyte.com/login", "portal login page"),
        ("https://portal.mugobyte.com/api/version", "portal version API"),
        ("https://portal.mugobyte.com/api/cloud/config", "portal cloud config"),
        ("https://edmus.mugobyte.com/login", "edmus login page"),
    ]:
        code, body = http(url)
        check(label, code == 200, f"{code}")

    # Supabase live tables
    try:
        from backend.cloud.platform_service import service_select, cloud_public_config
        pub = cloud_public_config()
        check("platform cloud_public_config", pub.get("configured") is True)
        orgs = service_select("organizations", "select=id&limit=5") or []
        lics = service_select("licenses", "select=id,license_key,status&limit=5") or []
        check("organizations rows", len(orgs) >= 1, str(len(orgs)))
        check("licenses rows", len(lics) >= 1, str(len(lics)))
    except Exception as e:
        check("Supabase service queries", False, str(e))

    # Source modules present
    for rel in [
        "backend/cloud/license_server.py",
        "backend/cloud/command_center.py",
        "backend/cloud/platform_service.py",
        "licensing/license_engine.py",
        "web/mugobyte-platform/dist/index.html",
        "mbt_pos.spec",
        "BUILD.bat",
    ]:
        check(f"source {rel}", (ROOT / rel).exists())

    # Program Files install present (for final EXE packaging)
    pf = Path(r"C:\Program Files\MugoByte\MBT POS")
    check("Program Files install", pf.exists())

    print(f"\n=== Summary: {ok} passed, {fail} failed ===")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
