"""
Disable mouse-wheel scrolling on *small* panels/sections (app-wide).

Cashiers often wheel intending to scroll a large list (cart, product grid,
main tables). Tiny QScrollArea / list / table panes steal the wheel and
cause accidental content jumps — same class of UX risk as spinbox nudges.

Rules
-----
1. Dynamic property ``mbtWheelScroll``:
   - True  → always allow wheel scroll
   - False → never allow (propagate to a larger parent when possible)
2. Else objectName allow / deny lists (intentional large lists vs known rails).
3. Else height heuristic: viewport/host height < SMALL_HEIGHT_PX → block.

Large intentional lists (product grid, Current Sale cart, full-page tables)
keep normal wheel scrolling. Spinbox no-wheel behavior is unchanged.
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QScrollArea,
)

# Panels shorter than this (px) are treated as "small" unless opted in.
SMALL_HEIGHT_PX = 280

# Explicit allow — always keep wheel (even if temporarily short).
_ALLOW_OBJECT_NAMES = frozenset({
    'posCartListScroll',
    'posProductScroll',
    'posSaleCartScroll',
    'posExplorerScroll',
    'posNavScroll',
    'mbtPageScroll',
})

# Explicit deny — never steal wheel (classic payment rail, side chips, etc.).
_DENY_OBJECT_NAMES = frozenset({
    'posClassicActionsScroll',
})

_PROP = 'mbtWheelScroll'
_FILTER = None


def mark_wheel_scroll(widget, allow: bool) -> None:
    """Opt a scroll host in/out of wheel scrolling."""
    if widget is None:
        return
    try:
        widget.setProperty(_PROP, bool(allow))
    except Exception:
        pass


def is_small_scroll_host(widget) -> bool:
    """True when this scroll host should ignore wheel."""
    if widget is None:
        return False
    prop = widget.property(_PROP)
    if prop is True or prop == 1 or prop == '1':
        return False
    if prop is False or prop == 0 or prop == '0':
        return True
    name = ''
    try:
        name = widget.objectName() or ''
    except Exception:
        name = ''
    if name in _ALLOW_OBJECT_NAMES:
        return False
    if name in _DENY_OBJECT_NAMES:
        return True
    # Designed-small: explicit maxHeight below the threshold (classic rails, chip strips)
    try:
        mh = int(widget.maximumHeight())
        if 0 < mh < SMALL_HEIGHT_PX:
            return True
    except Exception:
        pass
    # Runtime height — only trust after the widget is visible/laid out
    try:
        if not widget.isVisible():
            return False
        h = int(widget.height() or 0)
    except Exception:
        return False
    return h > 0 and h < SMALL_HEIGHT_PX


def _find_scroll_host(obj):
    """Nearest QScrollArea / QAbstractItemView for a wheel target widget."""
    if obj is None:
        return None
    # Never treat spin boxes as scroll hosts (handled by no_wheel_spinbox).
    if isinstance(obj, QAbstractSpinBox):
        return None
    w = obj
    if isinstance(w, (QScrollArea, QAbstractItemView)):
        return w
    # Viewport → parent scroll area / item view
    try:
        p = w.parentWidget()
    except Exception:
        p = None
    if p is not None and isinstance(p, (QScrollArea, QAbstractItemView)):
        try:
            if p.viewport() is w:
                return p
        except Exception:
            return p
    # Walk ancestors (e.g. wheel over child chrome inside a scroll area)
    cur = p if p is not None else None
    while cur is not None:
        if isinstance(cur, QAbstractSpinBox):
            return None
        if isinstance(cur, (QScrollArea, QAbstractItemView)):
            return cur
        cur = cur.parentWidget()
    return None


def _apply_wheel_to_host(host, event) -> bool:
    """Scroll ``host`` by ``event``; return True if handled."""
    if host is None:
        return False
    if isinstance(host, QScrollArea):
        vp = host.viewport()
        if vp is not None:
            # Avoid re-entering our filter as a "small" host: mark transient
            QApplication.sendEvent(vp, event)
            return True
    bar = getattr(host, 'verticalScrollBar', None)
    if callable(bar):
        sb = bar()
        if sb is not None and sb.maximum() > 0:
            delta = event.angleDelta().y()
            if delta:
                step = sb.singleStep() or 16
                sb.setValue(sb.value() - int(delta / 120) * step * 3)
                return True
    return False


def _forward_wheel_past(blocked, event) -> bool:
    """Propagate wheel to the next larger (allowed) scrollable ancestor."""
    try:
        w = blocked.parentWidget()
    except Exception:
        w = None
    while w is not None:
        if isinstance(w, (QScrollArea, QAbstractItemView)) and not is_small_scroll_host(w):
            if _apply_wheel_to_host(w, event):
                return True
        # Generic scrollable with visible bar (rare non-view widgets)
        if not isinstance(w, (QScrollArea, QAbstractItemView)):
            bar = getattr(w, 'verticalScrollBar', None)
            if callable(bar):
                sb = bar()
                if sb is not None and sb.isVisible() and sb.maximum() > 0:
                    if not is_small_scroll_host(w):
                        delta = event.angleDelta().y()
                        if delta:
                            step = sb.singleStep() or 16
                            sb.setValue(sb.value() - int(delta / 120) * step * 3)
                            return True
        w = w.parentWidget()
    return False


class NoWheelSmallScrollFilter(QObject):
    """App filter: small scroll hosts ignore wheel; large lists keep it."""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel:
            return False
        # Spinboxes / their line-edits: leave to no_wheel_spinbox
        if isinstance(obj, QAbstractSpinBox):
            return False
        try:
            p = obj.parentWidget() if hasattr(obj, 'parentWidget') else None
        except Exception:
            p = None
        if p is not None and isinstance(p, QAbstractSpinBox):
            return False

        host = _find_scroll_host(obj)
        if host is None:
            return False
        if not is_small_scroll_host(host):
            return False
        # Consume: do not scroll the tiny pane; try parent instead
        _forward_wheel_past(host, event)
        event.accept()
        return True


def install_no_wheel_small_scroll(app=None) -> NoWheelSmallScrollFilter:
    """Install once on QApplication. Safe to call repeatedly."""
    global _FILTER
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError('QApplication required before install_no_wheel_small_scroll')
    if _FILTER is not None:
        return _FILTER
    _FILTER = NoWheelSmallScrollFilter(app)
    app.installEventFilter(_FILTER)
    return _FILTER


def small_scroll_ignores_wheel(host) -> bool:
    """Test helper: True when a synthetic wheel would not move ``host``'s bar."""
    if host is None or not is_small_scroll_host(host):
        return False
    from PyQt5.QtGui import QWheelEvent
    from PyQt5.QtCore import QPoint, QPointF

    sb = host.verticalScrollBar() if hasattr(host, 'verticalScrollBar') else None
    if sb is None:
        return True
    # Ensure there is room to scroll so a failure would be detectable
    before = sb.value()
    # Force content taller than viewport when possible
    try:
        sb.setMaximum(max(sb.maximum(), 200))
        sb.setValue(0)
        before = 0
    except Exception:
        pass
    ev = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10),
        QPoint(0, 0), QPoint(0, -120),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
    )
    filt = _FILTER or NoWheelSmallScrollFilter()
    # Deliver as if over the viewport
    target = host.viewport() if hasattr(host, 'viewport') and host.viewport() else host
    handled = filt.eventFilter(target, ev)
    after = sb.value()
    return bool(handled) and after == before
