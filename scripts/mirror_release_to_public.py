"""Copy one source-repo release onto the public releases repository.

GitHub Actions runs this from .github/workflows/mirror-public-release.yml.
It can also be run locally:

  RELEASE_TAG=v3.1.84 RELEASES_REPO_TOKEN=... python scripts/mirror_release_to_public.py

The token is a fine-grained PAT with Contents read and write on
MugoJnr/mbt-pos-releases only. Reading the source release uses GH_TOKEN
or the logged-in gh user (in Actions, that is the workflow GITHUB_TOKEN).

Only the installer and checksum sidecars are uploaded. Source archives
are never downloaded and never published.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.release_repos import (  # noqa: E402
    LEGACY_RELEASE_REPO,
    PUBLIC_RELEASE_REPO,
    is_mirror_asset,
)

MISSING_TOKEN = """RELEASES_REPO_TOKEN is not set.

Create a fine-grained personal access token:
  - Resource owner: MugoJnr
  - Repository access: only MugoJnr/mbt-pos-releases
  - Permissions: Contents read and write

Then add it as the Actions secret RELEASES_REPO_TOKEN on MugoJnr/mbt-pos.
Do not commit the token.
"""


def _run(cmd: list[str], env: dict, check: bool = True) -> subprocess.CompletedProcess:
    printable = " ".join(cmd[:8])
    print("Running:", printable, "...")
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def select_mirror_files(paths: list[Path]) -> list[Path]:
    """Keep installer and checksum files. Reject everything else."""
    chosen: list[Path] = []
    for path in paths:
        if not path.is_file():
            continue
        if not is_mirror_asset(path.name):
            raise SystemExit(
                f"Refusing to publish {path.name} to {PUBLIC_RELEASE_REPO}. "
                "The public repository must not receive source code."
            )
        chosen.append(path)
    if not any(path.name.lower() == "mbt_pos_setup.exe" for path in chosen):
        raise SystemExit(
            "Release has no MBT_POS_Setup.exe asset; nothing was mirrored."
        )
    return chosen


def _env_for(token: str | None) -> dict:
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
        env["GITHUB_TOKEN"] = token
    return env


def _release_exists(repo: str, tag: str, env: dict) -> bool:
    result = _run(
        ["gh", "release", "view", tag, "--repo", repo],
        env,
        check=False,
    )
    return result.returncode == 0


def download_release_assets(source_repo: str, tag: str, dest: Path, env: dict) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    # No --archive: GitHub's source zip/tar must not be downloaded or re-uploaded.
    _run(
        [
            "gh", "release", "download", tag,
            "--repo", source_repo,
            "--dir", str(dest),
        ],
        env,
    )
    return select_mirror_files(list(dest.iterdir()))


def load_release_meta(source_repo: str, tag: str, env: dict) -> dict:
    result = _run(
        [
            "gh", "release", "view", tag,
            "--repo", source_repo,
            "--json", "name,body,tagName,isPrerelease",
        ],
        env,
    )
    data = json.loads(result.stdout or "{}")
    if not isinstance(data, dict):
        raise SystemExit(f"Could not read release {tag} on {source_repo}")
    return data


def publish_assets(tag: str, files: list[Path], title: str, notes: str,
                   token: str, prerelease: bool) -> None:
    env = _env_for(token)
    file_args = [str(path) for path in files]
    if _release_exists(PUBLIC_RELEASE_REPO, tag, env):
        _run(
            [
                "gh", "release", "upload", tag, *file_args,
                "--repo", PUBLIC_RELEASE_REPO,
                "--clobber",
            ],
            env,
        )
        edit = [
            "gh", "release", "edit", tag,
            "--repo", PUBLIC_RELEASE_REPO,
            "--title", title,
            "--notes", notes,
        ]
        edit.append("--prerelease" if prerelease else "--latest")
        _run(edit, env)
    else:
        # No --target: the public tag stays on that repo's README history.
        cmd = [
            "gh", "release", "create", tag, *file_args,
            "--repo", PUBLIC_RELEASE_REPO,
            "--title", title,
            "--notes", notes,
        ]
        cmd.append("--prerelease" if prerelease else "--latest")
        _run(cmd, env)
    print(f"Mirrored {tag} to {PUBLIC_RELEASE_REPO} ({len(files)} files)")


def mirror(tag: str, source_repo: str, token: str, prerelease: bool = False) -> None:
    source_env = _env_for(None)
    meta = load_release_meta(source_repo, tag, source_env)
    with tempfile.TemporaryDirectory(prefix="mbt-release-") as tmp:
        files = download_release_assets(source_repo, tag, Path(tmp), source_env)
        title = str(meta.get("name") or f"MBT POS {tag.lstrip('v')}")
        notes = str(meta.get("body") or f"MBT POS {tag}")
        if meta.get("isPrerelease"):
            prerelease = True
        publish_assets(tag, files, title, notes, token, prerelease)


def main() -> None:
    token = os.environ.get("RELEASES_REPO_TOKEN", "").strip()
    tag = os.environ.get("RELEASE_TAG", "").strip()
    source = os.environ.get("SOURCE_REPO", LEGACY_RELEASE_REPO).strip() or LEGACY_RELEASE_REPO
    prerelease = os.environ.get("RELEASE_PRERELEASE", "").strip().lower() in {
        "1", "true", "yes",
    }
    if not token:
        raise SystemExit(MISSING_TOKEN)
    if not tag:
        raise SystemExit("RELEASE_TAG is required, for example v3.1.84")
    mirror(tag, source, token, prerelease)


if __name__ == "__main__":
    main()
