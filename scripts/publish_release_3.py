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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.release_repos import (  # noqa: E402
    LEGACY_RELEASE_REPO,
    PUBLIC_RELEASE_REPO,
    is_mirror_asset,
    public_installer_url,
)

SETUP = ROOT / "dist" / "MBT_POS_Setup.exe"
VERSION_JSON = ROOT / "version.json"
SIDECAR = ROOT / "dist" / "MBT_POS_Setup.exe.sha256"
_LEGACY_DOWNLOAD_HOST = "github.com/MugoJnr/mbt-pos/"
_PUBLIC_DOWNLOAD_HOST = "github.com/MugoJnr/mbt-pos-releases/"


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
    vj = ensure_public_download_url(vj)
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


def ensure_public_download_url(vj: dict) -> dict:
    """Point the manifest at the public feed when it still names the source repo."""
    url = str(vj.get("download_url") or "")
    legacy = _LEGACY_DOWNLOAD_HOST in url and _PUBLIC_DOWNLOAD_HOST not in url
    if not url or legacy:
        vj["download_url"] = public_installer_url(vj.get("version") or "")
    return vj


def release_notes_body(vj: dict) -> str:
    ver = vj["version"]
    notes = vj.get("release_notes") or f"MBT POS {ver}"
    return f"""## Summary
{notes}

## Installer
- `MBT_POS_Setup.exe`
- SHA-256: `{vj['checksum_sha256']}`

[checksum_sha256: {vj['checksum_sha256']}]
"""


def _gh_env(token: str | None) -> dict:
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
        env["GITHUB_TOKEN"] = token
    return env


def _release_exists(repo: str, tag: str, env: dict) -> bool:
    result = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo],
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode == 0


def _release_asset_args() -> list[str]:
    files = [SETUP, SIDECAR]
    for path in files:
        if not is_mirror_asset(path.name):
            raise SystemExit(f"Refusing to upload {path.name}")
        if not path.is_file():
            raise SystemExit(f"Missing release file: {path}")
    return [str(path) for path in files]


def publish_source_release(vj: dict) -> None:
    """Publish the installer on the source repo so tills on the old updater can install it."""
    ver = vj["version"]
    tag = f"v{ver}"
    if _release_exists(LEGACY_RELEASE_REPO, tag, _gh_env(None)):
        raise SystemExit(
            f"GitHub release {tag} already exists on {LEGACY_RELEASE_REPO}; "
            "refusing destructive replacement")
    target = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
    ).strip()
    cmd = [
        "gh", "release", "create", tag,
        *_release_asset_args(),
        "--repo", LEGACY_RELEASE_REPO,
        "--title", f"MBT POS {ver}",
        "--notes", release_notes_body(vj),
        "--target", target,
        "--latest",
    ]
    print("Running:", " ".join(cmd[:6]), "...")
    subprocess.check_call(cmd, cwd=str(ROOT), env=_gh_env(None))
    print(f"GitHub release {tag} published on {LEGACY_RELEASE_REPO}")


def publish_public_release(vj: dict, token: str) -> None:
    """Copy the same installer onto the public releases repo. No source commit is attached."""
    if not token:
        raise SystemExit("RELEASES_REPO_TOKEN is required")
    ver = vj["version"]
    tag = f"v{ver}"
    env = _gh_env(token)
    title = f"MBT POS {ver}"
    notes = release_notes_body(vj)
    assets = _release_asset_args()
    if _release_exists(PUBLIC_RELEASE_REPO, tag, env):
        cmd = [
            "gh", "release", "upload", tag, *assets,
            "--repo", PUBLIC_RELEASE_REPO,
            "--clobber",
        ]
        print(f"Updating existing public release {tag}")
        subprocess.check_call(cmd, cwd=str(ROOT), env=env)
        subprocess.check_call(
            [
                "gh", "release", "edit", tag,
                "--repo", PUBLIC_RELEASE_REPO,
                "--title", title,
                "--notes", notes,
                "--latest",
            ],
            cwd=str(ROOT),
            env=env,
        )
    else:
        # Do not pass --target. The source SHA is not a commit on the public repo,
        # and the public repo must not receive the source tree.
        cmd = [
            "gh", "release", "create", tag, *assets,
            "--repo", PUBLIC_RELEASE_REPO,
            "--title", title,
            "--notes", notes,
            "--latest",
        ]
        print("Running:", " ".join(cmd[:6]), "...")
        subprocess.check_call(cmd, cwd=str(ROOT), env=env)
    print(f"GitHub release {tag} published on {PUBLIC_RELEASE_REPO}")


def publish_app_updates(vj: dict) -> None:
    sys.path.insert(0, str(ROOT))
    from backend.cloud.update_center import UpdateCenter

    uc = UpdateCenter()
    row = uc.publish_update(
        version=vj["version"],
        download_url=public_installer_url(vj["version"]),
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
    ap.add_argument(
        "--skip-cloud",
        action="store_true",
        help="Publish the GitHub releases and do not write the portal app_updates row",
    )
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
        source_published = False
        try:
            publish_source_release(vj)
            source_published = True
            token = os.environ.get("RELEASES_REPO_TOKEN", "").strip()
            if token:
                publish_public_release(vj, token)
            else:
                print(
                    "RELEASES_REPO_TOKEN is not set. The source release was published.\n"
                    "Tills still on the old updater can install it from "
                    f"{LEGACY_RELEASE_REPO}.\n"
                    "Create a fine-grained PAT with Contents read/write on "
                    f"{PUBLIC_RELEASE_REPO} only, store it as the repository secret "
                    "RELEASES_REPO_TOKEN, and let "
                    ".github/workflows/mirror-public-release.yml copy this release. "
                    "Until that secret exists, re-run with RELEASES_REPO_TOKEN set "
                    "to publish the public copy from this machine.\n"
                    "Do not make the source repository private until tills are "
                    "running a build that reads the public releases repository.",
                    file=sys.stderr,
                )
        finally:
            if source_published and not args.skip_cloud:
                publish_app_updates(vj)
            elif source_published and args.skip_cloud:
                print(
                    "Skipped portal app_updates. Set MBT_SUPABASE_SERVICE_KEY and "
                    "run publish again without --skip-cloud to record the download URL.",
                    file=sys.stderr,
                )


if __name__ == "__main__":
    main()
