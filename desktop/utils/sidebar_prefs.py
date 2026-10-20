"""Local UI preferences for the collapsible / resizable shell sidebar.

Why QSettings and not ``system_settings``
-----------------------------------------
Sidebar collapse state and width are per-till *chrome*, not shop policy.  Two
reasons rule out the usual ``api.update_settings`` / ``system_settings`` path:

* ``update_settings`` is permission gated.  A cashier or viewer would not be
  able to save their own sidebar preference, and requirement is that every
  logged-in user can.
* ``system_settings`` is shop-wide and syncs.  One till collapsing its sidebar
  would move the sidebar on every other till in the shop.

``QSettings`` (organisation ``MugoByte``, application ``MBT POS``) stores the
preference under the Windows user profile: permission free, offline safe, and
local to the machine account that set it.  Every other shop preference keeps
using ``system_settings``; only UI chrome lives here.

All widths in this module are *logical* pixels.  Qt scales them for the active
device pixel ratio, so they hold on 100% / 125% / 150% / 200% displays.
"""
from __future__ import annotations

ORG_NAME = 'MugoByte'
APP_NAME = 'MBT POS'

SETTINGS_GROUP = 'ui/sidebar'
KEY_COLLAPSED = 'ui_sidebar_collapsed'
KEY_WIDTH = 'ui_sidebar_width'

# Icon-only rail: 64px keeps an 18px icon plus the 3px active rail centred and
# still lands inside the 56-72px band that reads as a nav strip rather than a
# stray toolbar.
COLLAPSED_WIDTH = 64
# Narrowest expanded sidebar that still shows a label next to the icon.
EXPANDED_MIN = 200
# Widest the sidebar may ever get — beyond this it starts eating the POS pane.
EXPANDED_MAX = 340
# Shipping default on a roomy display.
DEFAULT_WIDTH = 240
# Shipping default on a cramped display (1366x768 class hardware).
COMPACT_WIDTH = 208

# A sidebar may never take more than this share of the window, whatever the
# saved width says.  0.32 of a 960px minimum window still clears EXPANDED_MIN.
MAX_WINDOW_FRACTION = 0.32

# Screens at or below this logical width get the compact default.
SMALL_SCREEN_WIDTH = 1366
# Screens at or below this logical width boot collapsed so the POS pane wins.
TINY_SCREEN_WIDTH = 1024


def max_width_for_window(window_width: int = 0) -> int:
    """Widest allowed expanded sidebar for a window of ``window_width``."""
    try:
        window_width = int(window_width or 0)
    except (TypeError, ValueError):
        window_width = 0
    if window_width <= 0:
        return EXPANDED_MAX
    share = int(window_width * MAX_WINDOW_FRACTION)
    return max(EXPANDED_MIN, min(EXPANDED_MAX, share))


def clamp_sidebar_width(width, window_width: int = 0) -> int:
    """Coerce any stored/dragged width into a width that is safe to apply."""
    try:
        value = int(round(float(width)))
    except (TypeError, ValueError):
        value = DEFAULT_WIDTH
    upper = max_width_for_window(window_width)
    return max(EXPANDED_MIN, min(upper, value))


def is_small_screen(available_width: int = 0) -> bool:
    try:
        available_width = int(available_width or 0)
    except (TypeError, ValueError):
        available_width = 0
    return 0 < available_width <= SMALL_SCREEN_WIDTH


def default_sidebar_state(available_width: int = 0) -> tuple[bool, int]:
    """(collapsed, width) for a first run / unreadable preference.

    Unknown screen size is treated as roomy so a headless or offscreen boot
    behaves like the shipping desktop default.
    """
    try:
        available_width = int(available_width or 0)
    except (TypeError, ValueError):
        available_width = 0
    if available_width <= 0:
        return False, DEFAULT_WIDTH
    if available_width <= TINY_SCREEN_WIDTH:
        return True, COMPACT_WIDTH
    if available_width <= SMALL_SCREEN_WIDTH:
        return False, COMPACT_WIDTH
    return False, DEFAULT_WIDTH


def sidebar_settings():
    """QSettings scoped to this Windows user (organisation / application)."""
    from PyQt5.QtCore import QSettings
    return QSettings(ORG_NAME, APP_NAME)


def _as_bool(value, fallback: bool) -> bool:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'on'):
        return True
    if text in ('0', 'false', 'no', 'off'):
        return False
    return fallback


def load_sidebar_prefs(available_width: int = 0, window_width: int = 0,
                       settings=None) -> dict:
    """Read the saved sidebar state, falling back to a safe default.

    A width that is impossible on this monitor/DPI (saved on a 4K panel, now
    booting on a 1024x768 till) is clamped rather than rejected, so the user
    keeps a sidebar that is as close to their preference as still fits.
    """
    collapsed_default, width_default = default_sidebar_state(available_width)
    if settings is None:
        try:
            settings = sidebar_settings()
        except Exception:
            return {'collapsed': collapsed_default,
                    'width': clamp_sidebar_width(width_default, window_width)}
    try:
        settings.beginGroup(SETTINGS_GROUP)
        try:
            raw_collapsed = settings.value(KEY_COLLAPSED, None)
            raw_width = settings.value(KEY_WIDTH, None)
        finally:
            settings.endGroup()
    except Exception:
        raw_collapsed, raw_width = None, None
    collapsed = _as_bool(raw_collapsed, collapsed_default)
    width = clamp_sidebar_width(
        width_default if raw_width in (None, '') else raw_width, window_width)
    return {'collapsed': bool(collapsed), 'width': int(width)}


def save_sidebar_prefs(collapsed: bool, width, settings=None) -> bool:
    """Persist collapse flag + expanded width. Never raises."""
    if settings is None:
        try:
            settings = sidebar_settings()
        except Exception:
            return False
    try:
        settings.beginGroup(SETTINGS_GROUP)
        try:
            settings.setValue(KEY_COLLAPSED, bool(collapsed))
            settings.setValue(KEY_WIDTH, int(clamp_sidebar_width(width)))
        finally:
            settings.endGroup()
        settings.sync()
        return True
    except Exception:
        return False
