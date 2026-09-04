"""Small Windows/Qt bridge for power and interactive-session notifications."""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Optional

log = logging.getLogger("mbt.windows_session")

WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1

PBT_APMSUSPEND = 0x0004
PBT_APMRESUMECRITICAL = 0x0006
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012

WTS_CONSOLE_CONNECT = 0x0001
WTS_CONSOLE_DISCONNECT = 0x0002
WTS_REMOTE_CONNECT = 0x0003
WTS_REMOTE_DISCONNECT = 0x0004
WTS_SESSION_LOGON = 0x0005
WTS_SESSION_LOGOFF = 0x0006
WTS_SESSION_LOCK = 0x0007
WTS_SESSION_UNLOCK = 0x0008

NOTIFY_FOR_THIS_SESSION = 0

_POWER_RESUME_EVENTS = {
    PBT_APMRESUMECRITICAL,
    PBT_APMRESUMESUSPEND,
    PBT_APMRESUMEAUTOMATIC,
}
_SESSION_RESUME_EVENTS = {
    WTS_CONSOLE_CONNECT,
    WTS_REMOTE_CONNECT,
    WTS_SESSION_LOGON,
    WTS_SESSION_UNLOCK,
}
_SESSION_PAUSE_EVENTS = {
    WTS_CONSOLE_DISCONNECT,
    WTS_REMOTE_DISCONNECT,
    WTS_SESSION_LOGOFF,
    WTS_SESSION_LOCK,
}


def classify_message(message_id: int, event_code: int) -> Optional[str]:
    """Map a Win32 notification to a stable action used by the Qt window."""
    if message_id == WM_POWERBROADCAST:
        if event_code == PBT_APMSUSPEND:
            return "suspend"
        if event_code in _POWER_RESUME_EVENTS:
            return "resume"
    elif message_id == WM_WTSSESSION_CHANGE:
        if event_code in _SESSION_RESUME_EVENTS:
            return "session-resume"
        if event_code in _SESSION_PAUSE_EVENTS:
            return "session-pause"
    return None


def decode_native_message(message) -> tuple[int, int]:
    """Read message and wParam from Qt's MSG pointer."""
    address = int(message)
    msg = wintypes.MSG.from_address(address)
    return int(msg.message), int(msg.wParam)


def register_session_notifications(hwnd: int) -> bool:
    """Ask Windows to deliver WTS session events to the Qt native window."""
    if sys.platform != "win32":
        return False
    try:
        wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
        register = wtsapi32.WTSRegisterSessionNotification
        register.argtypes = (wintypes.HWND, wintypes.DWORD)
        register.restype = wintypes.BOOL
        if not register(wintypes.HWND(hwnd), NOTIFY_FOR_THIS_SESSION):
            raise ctypes.WinError(ctypes.get_last_error())
        return True
    except Exception:
        log.exception("Could not register Windows session notifications")
        return False


def unregister_session_notifications(hwnd: int) -> None:
    if sys.platform != "win32":
        return
    try:
        wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
        unregister = wtsapi32.WTSUnRegisterSessionNotification
        unregister.argtypes = (wintypes.HWND,)
        unregister.restype = wintypes.BOOL
        unregister(wintypes.HWND(hwnd))
    except Exception:
        log.exception("Could not unregister Windows session notifications")
