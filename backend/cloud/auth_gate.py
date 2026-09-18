"""
Auth fail-open gate for Supabase session refresh (v3.0.94).

Stops Invalid Refresh Token / dead-session storms from spinning SyncManager,
command JWT refresh, and UI toasts. POS sales stay local and never wait on
cloud re-auth.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger('cloud.auth_gate')

# After a failed refresh, refuse another attempt for this long (seconds).
REFRESH_COOLDOWN_SEC = 7 * 60  # ~7 minutes — within the 5–10 min window

# Terminal / non-recoverable refresh failure markers (GoTrue).
_TERMINAL_REFRESH_MARKERS = (
    'invalid refresh token',
    'refresh token not found',
    'refresh_token_not_found',
    'invalid_grant',
    'session not found',
    'token not found',
    'user not found',
)

_AUTH_ERROR_INVALID_REFRESH = 'invalid_refresh_token'

_lock = threading.RLock()
_terminal_dead = False
_last_refresh_attempt = 0.0
_last_refresh_failure = 0.0
_toast_silenced = False
_toast_shown_this_process = False


def reset_for_tests() -> None:
    """Clear in-process gate state (unit tests only)."""
    global _terminal_dead, _last_refresh_attempt, _last_refresh_failure
    global _toast_silenced, _toast_shown_this_process
    with _lock:
        _terminal_dead = False
        _last_refresh_attempt = 0.0
        _last_refresh_failure = 0.0
        _toast_silenced = False
        _toast_shown_this_process = False


def is_terminal_auth_dead() -> bool:
    """In-process terminal death from Invalid Refresh Token this session."""
    with _lock:
        return _terminal_dead


def identity_blocks_cloud_sync() -> bool:
    """True when saved identity requires portal re-login (any process)."""
    try:
        from backend.cloud_backup.paths import identity_needs_reauth
        return bool(identity_needs_reauth())
    except Exception:
        return False


def looks_like_terminal_refresh_failure(
    message: str | Exception | None = None,
    *,
    status: int = 0,
    payload: object = None,
) -> bool:
    """True when the refresh token can never succeed without a fresh login."""
    parts = [str(message or '')]
    if payload is not None:
        parts.append(str(payload))
        if isinstance(payload, dict):
            for key in ('error', 'error_code', 'msg', 'message', 'error_description'):
                if payload.get(key):
                    parts.append(str(payload.get(key)))
    text = ' '.join(parts).lower()
    if any(marker in text for marker in _TERMINAL_REFRESH_MARKERS):
        return True
    # Bare 401/403 on the refresh grant with an empty body is usually terminal.
    if status in (400, 401, 403) and 'refresh' in text:
        return True
    return False


def allow_refresh_attempt(*, force: bool = False) -> bool:
    """Gate refresh_session — False means fail-open without touching the network."""
    with _lock:
        if _terminal_dead and not force:
            return False
        now = time.monotonic()
        if (
            not force
            and _last_refresh_failure > 0
            and (now - _last_refresh_failure) < REFRESH_COOLDOWN_SEC
        ):
            return False
        _last_refresh_attempt = now
        return True


def seconds_until_refresh_allowed() -> float:
    with _lock:
        if _terminal_dead:
            return float('inf')
        if _last_refresh_failure <= 0:
            return 0.0
        return max(0.0, REFRESH_COOLDOWN_SEC - (time.monotonic() - _last_refresh_failure))


def note_refresh_success() -> None:
    global _terminal_dead, _last_refresh_failure, _toast_silenced, _toast_shown_this_process
    with _lock:
        _terminal_dead = False
        _last_refresh_failure = 0.0
        _toast_silenced = False
        _toast_shown_this_process = False


def note_refresh_failure(
    error: Exception | str | None = None,
    *,
    status: int = 0,
    payload: object = None,
    terminal: Optional[bool] = None,
) -> bool:
    """Record a refresh failure. Returns True when it became a terminal death."""
    global _terminal_dead, _last_refresh_failure
    is_terminal = (
        bool(terminal)
        if terminal is not None
        else looks_like_terminal_refresh_failure(error, status=status, payload=payload)
    )
    with _lock:
        _last_refresh_failure = time.monotonic()
        if is_terminal:
            _terminal_dead = True
    if is_terminal:
        try:
            from backend.cloud_backup.paths import invalidate_cloud_session
            invalidate_cloud_session(reason=_AUTH_ERROR_INVALID_REFRESH)
        except Exception as e:
            logger.warning('Failed to clear dead cloud session: %s', e)
        logger.warning(
            'Terminal cloud auth failure — tokens cleared; sync paused until re-login (%s)',
            str(error or '')[:160],
        )
        try:
            _pause_cloud_workers()
        except Exception as e:
            logger.debug('pause cloud workers: %s', e)
    return is_terminal


def clear_auth_gate_on_login() -> None:
    """Called after a successful portal sign-in restores tokens."""
    note_refresh_success()


def cloud_sync_should_run() -> bool:
    """False when SyncManager / backup / entity sync must stay idle.

    Single definition (v3.0.97): terminal death, durable reauth_required,
    or no refreshable session all keep cloud workers quiet.
    """
    if is_terminal_auth_dead() or identity_blocks_cloud_sync():
        return False
    try:
        from backend.cloud_backup.paths import is_logged_in
        return bool(is_logged_in())
    except Exception:
        return False


def should_show_platform_auth_toast() -> bool:
    """Toast platform auth errors once per process until re-auth / cold start."""
    global _toast_shown_this_process, _toast_silenced
    with _lock:
        if _toast_silenced or _toast_shown_this_process:
            return False
        _toast_shown_this_process = True
        _toast_silenced = True
        return True


def silence_platform_auth_toasts() -> None:
    global _toast_silenced, _toast_shown_this_process
    with _lock:
        _toast_silenced = True
        _toast_shown_this_process = True


def is_platform_auth_message(text: str | None) -> bool:
    low = str(text or '').lower()
    if not low:
        return False
    if 'mugobyte platform' in low:
        return True
    return any(marker in low for marker in _TERMINAL_REFRESH_MARKERS) or (
        'refresh token' in low and ('invalid' in low or 'not found' in low)
    )


def assert_not_ui_thread(action: str = 'cloud session refresh') -> None:
    """Refuse cloud auth network I/O on the Qt UI thread (fail-open)."""
    try:
        from PyQt5.QtCore import QThread
        from PyQt5.QtWidgets import QApplication
    except Exception:
        return
    app = QApplication.instance()
    if app is None:
        return
    try:
        if QThread.currentThread() is app.thread():
            raise RuntimeError(
                f'{action} refused on UI thread — use a background worker'
            )
    except RuntimeError:
        raise
    except Exception:
        return


def _pause_cloud_workers() -> None:
    """Best-effort: stop backup loop from hammering a dead session.

    SyncManager's loop still runs but ``cloud_sync_should_run`` / ``is_logged_in``
    gate the work. Command JWT refresh is gated via ``allow_refresh_attempt``.
    """
    try:
        from backend.cloud_backup.sync_manager import SyncManager
        sm = SyncManager.instance()
        sm._last_status = 'Cloud auth required — sign in again (POS still works)'
        sm._last_error = 'reauth_required'
    except Exception:
        pass


def snapshot() -> dict:
    with _lock:
        return {
            'terminal_dead': _terminal_dead,
            'toast_silenced': _toast_silenced,
            'toast_shown': _toast_shown_this_process,
            'refresh_cooldown_sec': REFRESH_COOLDOWN_SEC,
            'seconds_until_refresh': (
                float('inf') if _terminal_dead
                else max(
                    0.0,
                    REFRESH_COOLDOWN_SEC - (time.monotonic() - _last_refresh_failure)
                    if _last_refresh_failure else 0.0,
                )
            ),
        }
