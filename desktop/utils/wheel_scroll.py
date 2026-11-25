"""Mouse-wheel scroll distance. Touchpad pixel scrolling is left alone."""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import QAbstractItemView, QAbstractSpinBox, QApplication, QScrollArea

_INTERVAL = 3
_FILTER = None


def set_wheel_scroll_interval(value) -> int:
    global _INTERVAL
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return _INTERVAL
    if 1 <= number <= 10:
        _INTERVAL = number
    return _INTERVAL


def wheel_scroll_interval() -> int:
    return _INTERVAL


def apply_saved_interval(api) -> int:
    """Use the signed-in account's interval. A missing account stays at 3."""
    try:
        value = (api.read_wheel_scroll() or {}).get('wheel_scroll_interval')
    except Exception:
        value = 3
    return set_wheel_scroll_interval(value or 3)


def wheel_notch_pixels(angle, pixel, interval, line_px=16):
    """Pixels to move for one mouse-wheel notch. None leaves the event native.

    A touchpad reports a pixel delta and is not scaled.
    """
    try:
        if int(pixel or 0):
            return None
        notches = int(round(float(angle or 0) / 120.0))
    except (TypeError, ValueError):
        return None
    if notches == 0:
        return None
    try:
        step = max(8, int(line_px or 16))
        gap = int(interval)
    except (TypeError, ValueError):
        return None
    if gap < 1:
        gap = 1
    if gap > 10:
        gap = 10
    return -notches * gap * step


def _host(obj):
    if obj is None or isinstance(obj, QAbstractSpinBox):
        return None
    if isinstance(obj, (QScrollArea, QAbstractItemView)):
        return obj
    parent = obj.parentWidget() if hasattr(obj, 'parentWidget') else None
    if isinstance(parent, QAbstractSpinBox):
        return None
    if isinstance(parent, (QScrollArea, QAbstractItemView)):
        return parent
    while parent is not None:
        if isinstance(parent, QAbstractSpinBox):
            return None
        if isinstance(parent, (QScrollArea, QAbstractItemView)):
            return parent
        parent = parent.parentWidget()
    return None


def _move_bar(host, event) -> bool:
    from desktop.utils.no_wheel_small_scroll import is_small_scroll_host
    if host is None or is_small_scroll_host(host):
        return False
    angle = event.angleDelta()
    pixel = event.pixelDelta()
    horizontal = abs(angle.x()) > abs(angle.y())
    bar = host.horizontalScrollBar() if horizontal else host.verticalScrollBar()
    if bar is None or bar.maximum() <= 0:
        return False
    delta = wheel_notch_pixels(
        angle.x() if horizontal else angle.y(),
        pixel.x() if horizontal else pixel.y(),
        wheel_scroll_interval(),
        bar.singleStep() or 16,
    )
    if delta is None:
        return False
    bar.setValue(bar.value() + delta)
    return True


class WheelScrollFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel:
            return False
        if isinstance(obj, QAbstractSpinBox):
            return False
        host = _host(obj)
        if not _move_bar(host, event):
            return False
        event.accept()
        return True


def install_wheel_scroll(app=None) -> WheelScrollFilter:
    global _FILTER
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError('QApplication required before install_wheel_scroll')
    if _FILTER is not None:
        return _FILTER
    _FILTER = WheelScrollFilter(app)
    app.installEventFilter(_FILTER)
    return _FILTER
