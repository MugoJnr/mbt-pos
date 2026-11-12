"""What the till and dashboard say during an update.

The check and the download run on a background thread. This module only
decides which installer files to keep and which short line to show.
"""
from __future__ import annotations

MIN_INSTALLER_BYTES = 1_000_000
# A real NSIS setup is about 62 MB and will grow. The old 60_000_000 byte
# cutoff treated that file as a broken one-file build and deleted it.
MAX_INSTALLER_BYTES = 250_000_000
FIRST_CHECK_DELAY = 60
RECHECK_INTERVAL = 3 * 60
RETRY_INTERVAL = 3 * 60
DOWNLOAD_RETRY_INTERVAL = 2 * 60


def _parse_version(value: str) -> tuple:
    text = str(value or '').lstrip('v').strip()
    try:
        parts = [int(piece) for piece in text.split('.')[:3]]
    except ValueError:
        return (0, 0, 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def cached_installer_action(size: int, version: str, current: str, blocked) -> str:
    """keep, or a reason the file should be removed.

    A newer installer inside the size window is always kept, including one
    larger than 60 MB.
    """
    if version in (blocked or ()):
        return 'drop_blocked'
    if _parse_version(version) <= _parse_version(current):
        return 'drop_old'
    try:
        nbytes = int(size or 0)
    except (TypeError, ValueError):
        nbytes = 0
    if nbytes < MIN_INSTALLER_BYTES:
        return 'drop_small'
    if nbytes > MAX_INSTALLER_BYTES:
        return 'drop_huge'
    return 'keep'


def session_view(state: str, version: str = '', percent=None, detail: str = '') -> dict:
    """Short copy for one update step. No network and no waiting."""
    ver = f"v{version}" if version else "the update"
    pct = None
    if isinstance(percent, (int, float)) and not isinstance(percent, bool):
        pct = max(0, min(100, int(percent)))
    kind = state or 'idle'
    title = ''
    line = ''
    primary = ''
    secondary = ''
    bar = 'hidden'
    if kind == 'available':
        title = f"Update {ver} found"
        line = "Download is starting. You can keep selling."
        bar = 'busy'
    elif kind == 'downloading':
        title = f"Downloading {ver}"
        line = "You can keep selling."
        bar = 'percent' if pct is not None else 'busy'
    elif kind == 'verifying':
        title = "Checking the download"
        line = "Almost ready."
        bar = 'busy'
    elif kind == 'complete':
        title = f"{ver} is ready"
        line = "The till will close and reopen. Your sales stay."
        primary = "Install now"
        secondary = "Later"
        bar = 'percent'
        pct = 100
    elif kind == 'installing':
        title = f"Installing {ver}"
        line = "The till will close and reopen. Windows may ask once. Click Yes."
        bar = 'busy'
    elif kind == 'failed':
        title = "Update did not finish"
        line = (detail or "Try again.").replace('\n', ' ').strip()[:120]
        primary = "Try again"
        secondary = "Later"
    else:
        kind = 'idle'
    return {
        'state': kind,
        'title': title,
        'detail': line,
        'percent': pct,
        'bar': bar,
        'primary': primary,
        'secondary': secondary,
        'visible': kind != 'idle',
    }
