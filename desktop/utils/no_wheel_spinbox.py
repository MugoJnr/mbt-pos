"""
Disable mouse-wheel value changes on numeric spin controls (app-wide).

Wheel over a QSpinBox / QDoubleSpinBox / QAbstractSpinBox must scroll the
containing panel instead of nudging the value. Keyboard, +/- buttons, and
arrow keys still work normally.
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QDoubleSpinBox,
    QScrollArea,
    QSpinBox,
)

_FILTER = None


def _forward_wheel_to_scroll_parent(widget, event) -> bool:
    """Send wheel to nearest scrollable ancestor; return True if handled."""
    w = widget
    while w is not None:
        if isinstance(w, QScrollArea):
            vp = w.viewport()
            if vp is not None:
                QApplication.sendEvent(vp, event)
                return True
        # Widgets with their own vertical scrollbar (lists, tables, text)
        bar = getattr(w, 'verticalScrollBar', None)
        if callable(bar):
            sb = bar()
            if sb is not None and sb.isVisible() and sb.maximum() > 0:
                delta = event.angleDelta().y()
                if delta:
                    step = sb.singleStep() or 16
                    # Typical wheel notch ≈ 120; scroll ~3 steps
                    sb.setValue(sb.value() - int(delta / 120) * step * 3)
                    return True
        w = w.parentWidget()
    return False


class NoWheelSpinBoxFilter(QObject):
    """Application event filter: ignore wheel on spin boxes; scroll parent."""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel:
            return False
        if not isinstance(obj, QAbstractSpinBox):
            return False
        # Focused line-edit inside spinbox still receives wheel via the spinbox
        _forward_wheel_to_scroll_parent(obj, event)
        return True  # consume — never change spin value via wheel


def install_no_wheel_spinboxes(app=None) -> NoWheelSpinBoxFilter:
    """Install once on QApplication. Safe to call repeatedly."""
    global _FILTER
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError('QApplication required before install_no_wheel_spinboxes')
    if _FILTER is not None:
        return _FILTER
    _FILTER = NoWheelSpinBoxFilter(app)
    app.installEventFilter(_FILTER)
    # Also patch wheelEvent as belt-and-suspenders for subclasses created later
    _patch_wheel_event(QSpinBox)
    _patch_wheel_event(QDoubleSpinBox)
    _patch_wheel_event(QAbstractSpinBox)
    return _FILTER


def _patch_wheel_event(cls):
    if getattr(cls, '_mbt_no_wheel_patched', False):
        return

    def wheelEvent(self, event):
        _forward_wheel_to_scroll_parent(self, event)
        event.ignore()

    cls.wheelEvent = wheelEvent
    cls._mbt_no_wheel_patched = True


def spinbox_ignores_wheel(spin: QAbstractSpinBox) -> bool:
    """Test helper: True when a synthetic wheel would not change the value."""
    if spin is None:
        return False
    before = spin.value()
    # Simulate filtered path
    from PyQt5.QtGui import QWheelEvent
    from PyQt5.QtCore import QPoint, QPointF

    ev = QWheelEvent(
        QPointF(0, 0), QPointF(0, 0),
        QPoint(0, 0), QPoint(0, 120),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
    )
    # Direct wheelEvent on patched class should ignore
    spin.wheelEvent(ev)
    return abs(float(spin.value()) - float(before)) < 1e-9
