"""Compare the installed shop version with the trusted release feed.

The dashboard reports the result. It does not download or install anything.
"""
import json
import os
import urllib.request

GITHUB_LATEST = "https://api.github.com/repos/MugoJnr/mbt-pos/releases/latest"


def parse_version(value) -> tuple | None:
    text = str(value or "").strip()
    if text[:1].lower() == "v":
        text = text[1:]
    parts = text.split(".")
    if not text or not parts or any(not part.isdigit() for part in parts[:3]):
        return None
    numbers = [int(part) for part in parts[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)


def classify_release(installed_version: str, release: dict | None, *, reachable: bool) -> dict:
    """Turn one feed response into a dashboard state. Versions are compared numerically."""
    installed = parse_version(installed_version)
    base = {
        "installed_version": str(installed_version or ""),
        "available_version": "",
        "summary": "",
        "released": "",
        "action": "",
        "download_url": "",
        "source": "release feed",
        "installed": False,
    }
    if installed is None:
        return {
            **base,
            "state": "invalid",
            "message": "The installed version could not be read.",
        }
    if not reachable:
        return {
            **base,
            "state": "unavailable",
            "message": "The latest version could not be checked. The shop is unchanged.",
        }
    if not release:
        return {
            **base,
            "state": "current",
            "message": "This shop is up to date.",
        }
    remote_text = str(release.get("version") or "").strip()
    remote = parse_version(remote_text)
    if remote is None:
        return {
            **base,
            "state": "invalid",
            "message": "The published version is not a valid release number.",
        }
    summary = str(release.get("notes") or release.get("release_notes") or "")[:500]
    released = str(release.get("published_at") or release.get("released") or "")[:40]
    shared = {
        **base,
        "available_version": remote_text.lstrip("vV"),
        "summary": summary,
        "released": released,
        "source": str(release.get("source") or "release feed"),
    }
    if release.get("compatible") is False:
        return {
            **shared,
            "state": "incompatible",
            "message": "A newer release exists, but it is not a compatible update for this shop.",
        }
    if remote > installed:
        return {
            **shared,
            "state": "available",
            "message": f"Version {shared['available_version']} is available. This shop is still on {installed_version}.",
            "action": "Install the update on this shop till. The dashboard does not install it and does not change the licence.",
            "download_url": str(release.get("download_url") or ""),
        }
    return {
        **shared,
        "state": "current",
        "message": "This shop is up to date.",
    }


def _release_from_github(payload: dict) -> dict:
    tag = str(payload.get("tag_name") or "")
    asset_url = ""
    for asset in payload.get("assets") or []:
        if str(asset.get("name") or "").lower() == "mbt_pos_setup.exe":
            asset_url = str(asset.get("browser_download_url") or "")
            break
    return {
        "version": tag.lstrip("vV"),
        "notes": str(payload.get("body") or "")[:500],
        "published_at": str(payload.get("published_at") or ""),
        "download_url": asset_url,
        "source": "GitHub releases",
        "compatible": True,
    }


def load_release_feed() -> tuple[dict | None, bool]:
    """Return (release or None, reachable).

    MBT_UPDATE_FEED_JSON is a controlled test feed. It is not the shop release.
    """
    override = os.environ.get("MBT_UPDATE_FEED_JSON", "").strip()
    if override:
        if override.lower() in ("offline", "unavailable"):
            return None, False
        try:
            parsed = json.loads(override)
        except json.JSONDecodeError:
            return {"version": override}, True
        if not isinstance(parsed, dict):
            return {"version": ""}, True
        parsed.setdefault("source", "controlled test feed")
        return parsed, True
    try:
        request = urllib.request.Request(
            GITHUB_LATEST,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "MBT-POS-dashboard",
            },
        )
        with urllib.request.urlopen(request, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict) and payload.get("tag_name"):
            return _release_from_github(payload), True
    except Exception:
        pass
    try:
        from backend.cloud.update_center import get_update_center
        latest = get_update_center().get_latest()
    except Exception:
        latest = None
    if not latest:
        return None, False
    return {
        "version": latest.get("version"),
        "notes": latest.get("release_notes") or "",
        "published_at": latest.get("published_at") or "",
        "download_url": latest.get("download_url") or "",
        "compatible": latest.get("compatible", True),
        "source": "Portal update center",
    }, True
