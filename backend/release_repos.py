"""Where MBT POS installers are published.

Tills download Setup.exe with no token. Those bytes live on the public
repository ``MugoJnr/mbt-pos-releases``. The source repository
``MugoJnr/mbt-pos`` stays in the list so a till still on the old feed,
or a feed that has not been mirrored yet, can fall back while the source
repository is still public.

The public repository must contain release assets only. Never upload
source archives, a git checkout, or anything except the installer and
its checksum sidecars.
"""
from __future__ import annotations

ASSET_NAME = "MBT_POS_Setup.exe"
PUBLIC_RELEASE_REPO = "MugoJnr/mbt-pos-releases"
LEGACY_RELEASE_REPO = "MugoJnr/mbt-pos"
# Public mirror first. Legacy source repository second.
RELEASE_REPOS = (PUBLIC_RELEASE_REPO, LEGACY_RELEASE_REPO)

# Names that are safe to copy onto the public releases repository.
MIRROR_ASSET_NAMES = frozenset({
    "MBT_POS_Setup.exe",
    "MBT_POS_Setup.exe.sha256",
    "MBT_POS_Setup.sha256",
    "checksums.sha256",
    "SHA256SUMS",
    "checksums.txt",
})

CHECKSUM_ASSET_NAMES = (
    "MBT_POS_Setup.exe.sha256",
    "MBT_POS_Setup.sha256",
    "checksums.sha256",
    "SHA256SUMS",
    "checksums.txt",
)


def release_api_url(repo: str) -> str:
    return f"https://api.github.com/repos/{repo}/releases/latest"


def latest_installer_url(repo: str) -> str:
    return f"https://github.com/{repo}/releases/latest/download/{ASSET_NAME}"


def versioned_installer_url(repo: str, version: str) -> str:
    ver = str(version or "").strip().lstrip("vV")
    return f"https://github.com/{repo}/releases/download/v{ver}/{ASSET_NAME}"


def public_installer_url(version: str = "") -> str:
    """Installer URL that keeps working after the source repo is private."""
    if str(version or "").strip():
        return versioned_installer_url(PUBLIC_RELEASE_REPO, version)
    return latest_installer_url(PUBLIC_RELEASE_REPO)


def is_mirror_asset(name: str) -> bool:
    """True only for the installer and checksum sidecars."""
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    return base in MIRROR_ASSET_NAMES


def version_key(value: str) -> tuple:
    text = str(value or "").strip().lstrip("vV")
    parts = []
    for piece in text.split(".")[:3]:
        if not piece.isdigit():
            return (0, 0, 0)
        parts.append(int(piece))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def pick_best_release(candidates: list) -> dict:
    """Highest version that has an installer URL. Earlier entries win ties.

    A higher version with no installer loses to a lower version that has one,
    so a release note without Setup.exe cannot hide a downloadable build.
    """
    usable = [c for c in candidates if c.get("version") and c.get("asset_url")]
    pool = usable or [c for c in candidates if c.get("version")]
    best: dict = {}
    best_key = None
    for info in pool:
        key = version_key(str(info.get("version") or ""))
        if best_key is None or key > best_key:
            best = info
            best_key = key
    return best
