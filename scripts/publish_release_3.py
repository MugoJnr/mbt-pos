"""Stamp version.json checksum from dist Setup and optionally publish.

Usage:
  python scripts/publish_release_3.py [--publish] [--install]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
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
    SIDECAR.write_text(f"{digest}  MBT_POS_Setup.exe\n", encoding="utf-8", newline="\n")
    print(f"version={vj['version']} sha256={digest} size={SETUP.stat().st_size}")
    return vj


def embed_checksum_before_nsis() -> None:
    """Write a runtime manifest with no enclosing-installer checksum.

    An installer cannot contain its own final SHA-256: embedding that digest
    changes the installer bytes. Integrity is published externally in the root
    release manifest, sidecar, GitHub notes, and cloud update row.
    """
    vj = json.loads(VERSION_JSON.read_text(encoding="utf-8-sig"))
    vj["checksum_sha256"] = ""
    internal = ROOT / "dist" / "MBT_POS" / "_internal" / "version.json"
    if not internal.parent.is_dir():
        raise SystemExit(f"Missing freeze tree: {internal.parent}")
    payload = json.dumps(vj, indent=4) + "\n"
    internal.write_text(payload, encoding="utf-8", newline="\n")
    (ROOT / "dist" / "MBT_POS" / "version.json").write_text(
        payload, encoding="utf-8", newline="\n"
    )
    print("embedded runtime manifest (external installer checksum)")


def release_body(vj: dict) -> str:
    notes = vj.get("release_notes") or f"MBT POS {vj['version']}"
    return f"""## Summary
{notes}

## Installer
- `MBT_POS_Setup.exe`
- SHA-256: `{vj['checksum_sha256']}`

[checksum_sha256: {vj['checksum_sha256']}]
"""


def gh_release(vj: dict, replace_assets: bool = False) -> None:
    ver = vj["version"]
    tag = f"v{ver}"
    body = release_body(vj)
    exists = subprocess.run(
        ["gh", "release", "view", tag],
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    if exists.returncode == 0 and not replace_assets:
        raise SystemExit(
            f"GitHub release {tag} already exists; refusing destructive replacement")
    if exists.returncode == 0:
        # Same version rebuilt: the notes must advertise the checksum of the
        # installer that is actually attached, or shops verify against a
        # digest no asset has.
        subprocess.check_call(
            ["gh", "release", "edit", tag, "--notes", body],
            cwd=str(ROOT),
        )
        print(f"GitHub release {tag} notes refreshed; re-uploading assets")
    else:
        # Create the release first, then upload the ~60 MB installer separately.
        # gh deletes a brand-new release when an asset upload fails, so a single
        # combined call turns one slow upload into a lost release and tag.
        subprocess.check_call(
            [
                "gh", "release", "create", tag,
                "--title", f"MBT POS {ver}",
                "--notes", body,
                "--latest",
            ],
            cwd=str(ROOT),
        )
        print(f"GitHub release {tag} created; uploading assets")

    for attempt in range(1, 5):
        rc = subprocess.call(
            ["gh", "release", "upload", tag, str(SETUP), str(SIDECAR), "--clobber"],
            cwd=str(ROOT),
        )
        if rc == 0:
            break
        print(f"asset upload attempt {attempt} failed (exit {rc}); retrying")
        time.sleep(15)

    listing = subprocess.run(
        ["gh", "release", "view", tag, "--json", "assets"],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
        text=True,
    )
    assets = {
        a["name"]: int(a.get("size") or 0)
        for a in json.loads(listing.stdout).get("assets") or []
    }
    if assets.get(SETUP.name) != SETUP.stat().st_size:
        raise SystemExit(
            f"{tag} asset upload incomplete: {assets} — release left in place, "
            f"re-run publish to finish the upload"
        )
    print(f"GitHub release {tag} published with assets {assets}")


FLY_APP = "mbt-portal"

REMOTE_PUBLISH = r'''
import base64, json, os, sys, urllib.error, urllib.request

row = json.loads(base64.b64decode(sys.argv[1]).decode())
base = (os.environ.get("MBT_SUPABASE_URL") or os.environ.get("SUPABASE_URL") or "").rstrip("/")
key = (
    os.environ.get("MBT_SUPABASE_SERVICE_KEY")
    or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SERVICE_ROLE_KEY")
    or ""
)
if not base or not key:
    print("PUBLISH_RESULT " + json.dumps({"ok": False, "error": "portal service key unavailable"}))
    raise SystemExit(1)


def call(method, path, body=None, prefer=""):
    headers = {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode() or ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode() or ""


status, text = call(
    "POST", "/rest/v1/app_updates?on_conflict=version", row,
    "resolution=merge-duplicates,return=representation",
)
if status == 400 and "42P10" in text:
    status, existing = call(
        "GET",
        "/rest/v1/app_updates?version=eq." + row["version"] + "&select=id&limit=1",
    )
    found = json.loads(existing or "[]") if status < 400 else []
    if found:
        status, text = call(
            "PATCH", "/rest/v1/app_updates?id=eq." + str(found[0]["id"]),
            row, "return=representation",
        )
    else:
        status, text = call("POST", "/rest/v1/app_updates", row, "return=representation")

ok = status < 400
print("PUBLISH_RESULT " + json.dumps({"ok": ok, "status": status, "body": text[:400]}))
raise SystemExit(0 if ok else 1)
'''


def app_updates_row(vj: dict) -> dict:
    return {
        "version": vj["version"],
        "download_url": vj.get("download_url")
        or "https://github.com/MugoJnr/mbt-pos/releases/latest/download/MBT_POS_Setup.exe",
        "checksum_sha256": vj["checksum_sha256"],
        "release_notes": vj.get("release_notes") or "",
        "file_size_bytes": SETUP.stat().st_size,
        "is_mandatory": False,
        "is_active": True,
    }


def publish_app_updates_via_fly(vj: dict) -> None:
    """Insert the update row from the Portal server, which holds the service key.

    Keeps the service-role credential off developer machines while still
    guaranteeing the fleet sees the release the GitHub assets belong to.
    """
    row_b64 = base64.b64encode(
        json.dumps(app_updates_row(vj)).encode()
    ).decode()
    script_b64 = base64.b64encode(REMOTE_PUBLISH.encode()).decode()
    inner = (
        f"python3 -c \"import base64;open('/tmp/_publish_update.py','wb')"
        f".write(base64.b64decode('{script_b64}'))\" && "
        f"python3 /tmp/_publish_update.py {row_b64}"
    )
    proc = subprocess.run(
        ["flyctl", "ssh", "console", "-a", FLY_APP, "-C", f"bash -lc {json.dumps(inner)}"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = f"{proc.stdout}\n{proc.stderr}"
    result = None
    for line in output.splitlines():
        if line.strip().startswith("PUBLISH_RESULT "):
            result = json.loads(line.strip()[len("PUBLISH_RESULT "):])
    if not result or not result.get("ok"):
        raise SystemExit(f"app_updates publish failed via {FLY_APP}: {result or output[-400:]}")
    print("app_updates:", result["body"][:200])


def publish_app_updates(vj: dict) -> None:
    sys.path.insert(0, str(ROOT))
    from backend.cloud_backup.paths import load_cloud_config

    if (load_cloud_config().get("service_key") or "").strip():
        from backend.cloud.update_center import UpdateCenter

        row = UpdateCenter().publish_update(
            version=vj["version"],
            download_url=app_updates_row(vj)["download_url"],
            checksum=vj["checksum_sha256"],
            release_notes=vj.get("release_notes") or "",
            is_mandatory=False,
            published_by=None,
        )
        if not row:
            raise SystemExit("app_updates publish failed")
        print("app_updates:", row)
        return
    print("No local service key — publishing app_updates from the Portal server")
    publish_app_updates_via_fly(vj)


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
        "--cloud-only",
        action="store_true",
        help="Publish only the app_updates row for an existing GitHub release",
    )
    ap.add_argument(
        "--replace-assets",
        action="store_true",
        help="Re-upload assets and refresh notes/cloud row for a rebuilt same-version release",
    )
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
    if args.cloud_only:
        publish_app_updates(vj)
        return
    if args.publish or args.replace_assets:
        gh_release(vj, replace_assets=args.replace_assets)
        publish_app_updates(vj)


if __name__ == "__main__":
    main()
