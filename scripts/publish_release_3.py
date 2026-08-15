"""Stamp version.json checksum from dist Setup and optionally publish.

Usage:
  python scripts/publish_release_3.py [--publish] [--install]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "dist" / "MBT_POS_Setup.exe"
VERSION_JSON = ROOT / "version.json"
SIDECAR = ROOT / "dist" / "MBT_POS_Setup.exe.sha256"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stamp_checksum() -> dict:
    if not SETUP.is_file():
        raise SystemExit(f"Missing Setup: {SETUP}")
    digest = sha256_file(SETUP)
    vj = json.loads(VERSION_JSON.read_text(encoding="utf-8-sig"))
    vj["checksum_sha256"] = digest
    VERSION_JSON.write_text(json.dumps(vj, indent=4) + "\n", encoding="utf-8", newline="\n")
    # Also stamp into packaged tree if present (next NSIS / local run)
    packaged = ROOT / "dist" / "MBT_POS" / "_internal" / "version.json"
    if packaged.is_file():
        packaged.write_text(json.dumps(vj, indent=4) + "\n", encoding="utf-8", newline="\n")
    # Keep a root-level copy next to the frozen EXE when present
    packaged_root = ROOT / "dist" / "MBT_POS" / "version.json"
    if packaged_root.parent.is_dir():
        packaged_root.write_text(json.dumps(vj, indent=4) + "\n", encoding="utf-8", newline="\n")
    SIDECAR.write_text(f"{digest}  MBT_POS_Setup.exe\n", encoding="utf-8", newline="\n")
    # Patch installed Program Files copy when present (QA / same-PC upgrade)
    for pf in (
        Path(r"C:\Program Files\MugoByte\MBT POS\_internal\version.json"),
        Path(r"C:\Program Files\MugoByte\MBT POS\version.json"),
    ):
        if pf.is_file():
            try:
                pf.write_text(json.dumps(vj, indent=4) + "\n", encoding="utf-8", newline="\n")
                print(f"stamped install: {pf}")
            except OSError as e:
                print(f"warn: could not stamp {pf}: {e}")
    print(f"version={vj['version']} sha256={digest} size={SETUP.stat().st_size}")
    return vj


def embed_checksum_before_nsis() -> None:
    """Copy root version.json (must already carry checksum_sha256) into freeze tree.

    Call after PyInstaller and before makensis so Setup embeds a non-empty SHA.
    After makensis, run stamp_checksum() so root/sidecar match the new Setup bytes.
    One optional second makensis after stamp embeds the matching Setup SHA into the
    next installer build (BUILD.bat does freeze → nsis → stamp → nsis → stamp).
    """
    vj = json.loads(VERSION_JSON.read_text(encoding="utf-8-sig"))
    digest = (vj.get("checksum_sha256") or "").strip()
    if len(digest) != 64:
        # Prefer existing Setup hash if we are rebuilding installer only
        if SETUP.is_file():
            vj["checksum_sha256"] = sha256_file(SETUP)
            VERSION_JSON.write_text(
                json.dumps(vj, indent=4) + "\n", encoding="utf-8", newline="\n"
            )
            digest = vj["checksum_sha256"]
        else:
            raise SystemExit(
                "version.json checksum_sha256 empty and no dist Setup to hash — "
                "build Setup once, then re-run with stamp"
            )
    internal = ROOT / "dist" / "MBT_POS" / "_internal" / "version.json"
    if not internal.parent.is_dir():
        raise SystemExit(f"Missing freeze tree: {internal.parent}")
    payload = json.dumps(vj, indent=4) + "\n"
    internal.write_text(payload, encoding="utf-8", newline="\n")
    (ROOT / "dist" / "MBT_POS" / "version.json").write_text(
        payload, encoding="utf-8", newline="\n"
    )
    print(f"embedded checksum into freeze tree: {digest}")


def gh_release(vj: dict) -> None:
    ver = vj["version"]
    tag = f"v{ver}"
    notes = vj.get("release_notes") or f"MBT POS {ver}"
    body = f"""## Summary
{notes}

## Installer
- `MBT_POS_Setup.exe`
- SHA-256: `{vj['checksum_sha256']}`

[checksum_sha256: {vj['checksum_sha256']}]
"""
    # Delete draft if exists with same tag
    subprocess.run(
        ["gh", "release", "delete", tag, "--yes", "--cleanup-tag"],
        cwd=str(ROOT),
        check=False,
        capture_output=True,
    )
    cmd = [
        "gh",
        "release",
        "create",
        tag,
        str(SETUP),
        str(SIDECAR),
        "--title",
        f"MBT POS {ver}",
        "--notes",
        body,
        "--latest",
    ]
    print("Running:", " ".join(cmd[:6]), "...")
    subprocess.check_call(cmd, cwd=str(ROOT))
    print(f"GitHub release {tag} published")


def publish_app_updates(vj: dict) -> None:
    sys.path.insert(0, str(ROOT))
    from backend.cloud.update_center import UpdateCenter

    uc = UpdateCenter()
    row = uc.publish_update(
        version=vj["version"],
        download_url=vj.get("download_url")
        or "https://github.com/MugoJnr/mbt-pos/releases/latest/download/MBT_POS_Setup.exe",
        checksum=vj["checksum_sha256"],
        release_notes=vj.get("release_notes") or "",
        is_mandatory=False,
        published_by=None,
    )
    if not row:
        raise SystemExit("app_updates publish failed")
    print("app_updates:", row)


def silent_install() -> None:
    ps = (
        f'$p = Start-Process -FilePath {json.dumps(str(SETUP))} '
        f'-ArgumentList "/S" -Verb RunAs -Wait -PassThru; exit $p.ExitCode'
    )
    print("Silent installing Setup (UAC)...")
    rc = subprocess.call(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps]
    )
    print("install exit", rc)
    if rc != 0:
        raise SystemExit(rc)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--stamp-only", action="store_true")
    ap.add_argument(
        "--embed-before-nsis",
        action="store_true",
        help="Copy version.json with checksum into dist/MBT_POS before makensis",
    )
    args = ap.parse_args()
    if args.embed_before_nsis:
        embed_checksum_before_nsis()
        return
    vj = stamp_checksum()
    if args.stamp_only:
        return
    if args.install:
        silent_install()
    if args.publish:
        gh_release(vj)
        publish_app_updates(vj)


if __name__ == "__main__":
    main()
