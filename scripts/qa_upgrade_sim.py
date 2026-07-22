#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Installer gate #4 / L4 — non-destructive upgrade simulation.

Simulates NSIS upgrade backup + binary replace under TEMP only.

Safety rules:
  - NEVER write to real AppData / Program Files production paths.
  - Prefer fabricated fixtures under TEMP (default).
  - Optional READ-ONLY peek of live markers (hashes only) when --peek-live is set;
    still never copies *into* or mutates those paths.

Exit codes: 0 = PASS, 1 = FAIL, 2 = usage/setup error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

VERSION_TAG = "3.0.2"
MARKER_DB = b"MBT_POS_SIM_DB_v1\n" + b"\x00" * 64 + b"payload-ok\n"
MARKER_WAL = b"MBT_POS_SIM_WAL_v1\n"
MARKER_SHM = b"MBT_POS_SIM_SHM_v1\n"
MARKER_CFG = {
    "shop_name": "Upgrade Sim Shop",
    "theme": "professional",
    "sim_marker": "qa_upgrade_sim_v1",
}
MARKER_LIC = b"MBT_LIC_SIM_ENCRYPTED_BLOB_v1\n" + os.urandom(32)
OLD_EXE = b"MBT_POS.exe stub OLD build\n"
NEW_EXE = b"MBT_POS.exe stub NEW build after upgrade\n"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_bytes(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _sha256(path)


def _write_json(path: Path, obj: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    return _sha256(path)


def _assert_same(label: str, path: Path, expected_sha: str, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"{label}: missing {path}")
        return
    got = _sha256(path)
    if got != expected_sha:
        errors.append(f"{label}: hash mismatch {path.name} expected={expected_sha[:12]}… got={got[:12]}…")


def _live_roots() -> tuple[Path, Path]:
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "MugoByte" / "MBT POS"
    roaming = Path(os.environ.get("APPDATA", "")) / "MugoByte" / ".mbt_lic"
    return local, roaming


def peek_live_readonly() -> dict:
    """READ-ONLY inventory of live markers (no copy, no write)."""
    local, lic_root = _live_roots()
    candidates = {
        "db": local / "data" / "mbt_pos.db",
        "wal": local / "data" / "mbt_pos.db-wal",
        "shm": local / "data" / "mbt_pos.db-shm",
        "config_dir": local / "config",
        "license_db": lic_root / "lc.db",
    }
    out: dict = {"roots": {"localappdata": str(local), "license": str(lic_root)}, "files": {}}
    for key, p in candidates.items():
        if p.is_file():
            out["files"][key] = {"path": str(p), "size": p.stat().st_size, "sha256": _sha256(p)}
        elif p.is_dir():
            out["files"][key] = {"path": str(p), "exists": True, "type": "dir"}
        else:
            out["files"][key] = {"path": str(p), "exists": False}
    return out


def build_fixtures(root: Path) -> dict:
    """Create fake install + AppData-like trees under TEMP."""
    install = root / "install"
    userdata = root / "userdata"  # LOCALAPPDATA\MugoByte\MBT POS
    license_dir = root / "license"  # APPDATA\MugoByte\.mbt_lic

    hashes: dict[str, str] = {}
    hashes["exe_old"] = _write_bytes(install / "MBT_POS.exe", OLD_EXE)
    hashes["db"] = _write_bytes(userdata / "data" / "mbt_pos.db", MARKER_DB)
    hashes["wal"] = _write_bytes(userdata / "data" / "mbt_pos.db-wal", MARKER_WAL)
    hashes["shm"] = _write_bytes(userdata / "data" / "mbt_pos.db-shm", MARKER_SHM)
    hashes["config"] = _write_json(userdata / "config" / "settings.json", MARKER_CFG)
    hashes["license"] = _write_bytes(license_dir / "lc.db", MARKER_LIC)

    # Optional companion file (config tree depth)
    hashes["config_extra"] = _write_bytes(
        userdata / "config" / "printers.json",
        b'{"default":"sim-printer"}\n',
    )
    return {
        "install": install,
        "userdata": userdata,
        "license_dir": license_dir,
        "hashes": hashes,
    }


def simulate_pre_upgrade_backup(userdata: Path, license_dir: Path, hashes: dict) -> Path:
    """Mirror installer.nsi backup layout under TEMP userdata only."""
    bak = userdata / "backups" / "pre_upgrade" / VERSION_TAG
    (bak / "config").mkdir(parents=True, exist_ok=True)
    (bak / "license").mkdir(parents=True, exist_ok=True)

    shutil.copy2(userdata / "data" / "mbt_pos.db", bak / "mbt_pos.db")
    shutil.copy2(userdata / "data" / "mbt_pos.db-wal", bak / "mbt_pos.db-wal")
    shutil.copy2(userdata / "data" / "mbt_pos.db-shm", bak / "mbt_pos.db-shm")
    shutil.copytree(userdata / "config", bak / "config", dirs_exist_ok=True)
    shutil.copy2(license_dir / "lc.db", bak / "license" / "lc.db")

    # Record backup hashes for later assert
    hashes["bak_db"] = _sha256(bak / "mbt_pos.db")
    hashes["bak_wal"] = _sha256(bak / "mbt_pos.db-wal")
    hashes["bak_shm"] = _sha256(bak / "mbt_pos.db-shm")
    hashes["bak_config"] = _sha256(bak / "config" / "settings.json")
    hashes["bak_license"] = _sha256(bak / "license" / "lc.db")
    return bak


def dry_run_binary_replace(install: Path) -> str:
    """Replace only the install-dir binary (AppData untouched)."""
    exe = install / "MBT_POS.exe"
    exe.write_bytes(NEW_EXE)
    return _sha256(exe)


def assert_data_intact(fx: dict, new_exe_sha: str) -> list[str]:
    """Assert live userdata/license unchanged and backup matches originals."""
    errors: list[str] = []
    ud: Path = fx["userdata"]
    lic: Path = fx["license_dir"]
    h = fx["hashes"]
    bak = ud / "backups" / "pre_upgrade" / VERSION_TAG

    # Live AppData-like markers must be byte-identical to pre-upgrade
    _assert_same("live.db", ud / "data" / "mbt_pos.db", h["db"], errors)
    _assert_same("live.wal", ud / "data" / "mbt_pos.db-wal", h["wal"], errors)
    _assert_same("live.shm", ud / "data" / "mbt_pos.db-shm", h["shm"], errors)
    _assert_same("live.config", ud / "config" / "settings.json", h["config"], errors)
    _assert_same("live.config_extra", ud / "config" / "printers.json", h["config_extra"], errors)
    _assert_same("live.license", lic / "lc.db", h["license"], errors)

    # Backup must match originals (and live)
    _assert_same("bak.db", bak / "mbt_pos.db", h["db"], errors)
    _assert_same("bak.wal", bak / "mbt_pos.db-wal", h["wal"], errors)
    _assert_same("bak.shm", bak / "mbt_pos.db-shm", h["shm"], errors)
    _assert_same("bak.config", bak / "config" / "settings.json", h["config"], errors)
    _assert_same("bak.license", bak / "license" / "lc.db", h["license"], errors)

    # Binary must have changed
    exe = fx["install"] / "MBT_POS.exe"
    if not exe.is_file():
        errors.append("install: MBT_POS.exe missing after replace")
    else:
        got = _sha256(exe)
        if got != new_exe_sha:
            errors.append("install: exe hash drift after replace")
        if got == h["exe_old"]:
            errors.append("install: binary replace did not change MBT_POS.exe")
        if exe.read_bytes() != NEW_EXE:
            errors.append("install: exe content is not NEW stub")

    return errors


def run_simulation(keep: bool = False, peek_live: bool = False) -> dict:
    """Execute full TEMP upgrade sim. Returns result dict."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(tempfile.mkdtemp(prefix=f"mbt_upgrade_sim_{ts}_"))
    result: dict = {
        "ok": False,
        "root": str(root),
        "version_tag": VERSION_TAG,
        "started_at": ts,
        "peek_live": None,
        "errors": [],
        "steps": [],
        "root_cleaned": False,
    }
    try:
        if peek_live:
            result["peek_live"] = peek_live_readonly()
            result["steps"].append("peek_live_readonly")

        fx = build_fixtures(root)
        result["steps"].append("fabricate_fixtures")
        result["pre_hashes"] = {k: v for k, v in fx["hashes"].items()}

        bak = simulate_pre_upgrade_backup(fx["userdata"], fx["license_dir"], fx["hashes"])
        result["steps"].append(f"pre_upgrade_backup->{bak}")

        new_sha = dry_run_binary_replace(fx["install"])
        result["steps"].append("dry_run_binary_replace")
        result["exe_new_sha256"] = new_sha

        errors = assert_data_intact(fx, new_sha)
        result["errors"] = errors
        result["ok"] = len(errors) == 0
        result["steps"].append("assert_data_intact")
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        result["errors"].append(f"exception: {exc}")
        result["ok"] = False
    finally:
        # Clean TEMP on PASS unless --keep; keep tree on FAIL for inspection.
        if keep:
            result["note"] = "TEMP tree kept (--keep)"
        elif result.get("ok") and root.exists():
            shutil.rmtree(root, ignore_errors=True)
            result["root_cleaned"] = True
        elif root.exists():
            result["note"] = "TEMP tree kept on failure for inspection"
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="TEMP-only MBT POS upgrade simulation (installer gate #4)")
    p.add_argument("--keep", action="store_true", help="Keep TEMP tree even on PASS")
    p.add_argument(
        "--peek-live",
        action="store_true",
        help="READ-ONLY hash inventory of real AppData markers (never mutates)",
    )
    p.add_argument("--json", action="store_true", help="Print machine-readable JSON result")
    args = p.parse_args(argv)

    # Force keep when peeking so operators can correlate; peek itself is read-only.
    result = run_simulation(keep=bool(args.keep), peek_live=bool(args.peek_live))

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"[qa_upgrade_sim] {status}")
        print(f"  root: {result.get('root')}")
        print(f"  steps: {' | '.join(result.get('steps') or [])}")
        if result.get("peek_live"):
            files = (result["peek_live"] or {}).get("files") or {}
            present = [k for k, v in files.items() if v.get("exists") is not False and (v.get("sha256") or v.get("type"))]
            print(f"  peek-live present: {', '.join(present) or '(none)'}")
        for err in result.get("errors") or []:
            print(f"  ERROR: {err}")
        if result.get("note"):
            print(f"  note: {result['note']}")
        if result.get("root_cleaned"):
            print("  TEMP cleaned after PASS")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
