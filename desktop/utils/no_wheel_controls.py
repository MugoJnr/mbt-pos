"""
MBT POS — System-Wide Accidental Scroll/Touchpad Value Change Prevention.
MugoByte Technologies | mugobyte.com

Core POS Safety Rule:
"Scrolling navigates. It does not edit business data."

Wheel events (mouse wheel, trackpad two-finger scroll) over interactive value
widgets (QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit, QSlider)
must NEVER silently mutate values. Instead, the wheel event is forwarded to the
nearest scrollable ancestor (QScrollArea, QTableWidget, QListWidget, QTreeWidget).

Normal, deliberate editing (clicking open a dropdown, typing in a field, clicking
plus/minus buttons, clicking calendar picker, keyboard arrow keys when focused)
remains 100% functional.
"""
from __future__ import annotations

import logging
from PyQt5.QtCore import QEvent, QObject, Qt, QPoint
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDoubleSpinBox,
    QScrollArea,
    QSlider,
    QSpinBox,
    QWidget,
)

log = logging.getLogger('no_wheel_controls')
_GLOBAL_FILTER: NoWheelControlsFilter | None = None


def forward_wheel_to_scroll_parent(widget: QWidget | None, event) -> bool:
    """Send wheel event up the widget tree to the nearest scrollable container.

    Returns True if an ancestor handled/scrolled, False otherwise.
    """
    if widget is None or event is None:
        return False

    w = widget.parentWidget()
    while w is not None:
        # Check QScrollArea viewport
        if isinstance(w, QScrollArea):
            vp = w.viewport()
            if vp is not None and w.verticalScrollBar() and w.verticalScrollBar().maximum() > 0:
                QApplication.sendEvent(vp, event)
                return True

        # Check views / widgets with an active vertical scrollbar
        bar = getattr(w, 'verticalScrollBar', None)
        if callable(bar):
            sb = bar()
            if sb is not None and sb.isVisible() and sb.maximum() > 0:
                delta = event.angleDelta().y()
                if delta:
                    step = sb.singleStep() or 20
                    # Standard wheel notch is 120 units
                    num_steps = int(delta / 120)
                    if num_steps == 0 and delta != 0:
                        num_steps = 1 if delta > 0 else -1
                    sb.setValue(sb.value() - num_steps * step * 3)
                    return True

        w = w.parentWidget()
    return False


class NoWheelControlsFilter(QObject):
    """Universal application event filter that blocks accidental wheel mutation."""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel:
            return False

        # 1. Dropdown Combo Boxes
        if isinstance(obj, QComboBox):
            # If the dropdown popup list view is currently visible, allow scrolling the list!
            view = obj.view()
            if view is not None and view.isVisible():
                return False  # Normal scroll inside open dropdown list
            forward_wheel_to_scroll_parent(obj, event)
            return True  # Consume: closed combobox must NOT cycle selections

        # 2. Spinboxes, DoubleSpinBoxes, DateEdits, DateTimeEdits
        if isinstance(obj, (QAbstractSpinBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit)):
            forward_wheel_to_scroll_parent(obj, event)
            return True  # Consume: never change numeric or date value on wheel

        # 3. Sliders
        if isinstance(obj, QSlider):
            forward_wheel_to_scroll_parent(obj, event)
            return True  # Consume: never adjust slider on wheel

        return False


def _patch_wheel_event(cls):
    """Monkey-patch class wheelEvent as a robust second line of defense."""
    if getattr(cls, '_mbt_no_wheel_patched', False):
        return

    orig_wheel = getattr(cls, 'wheelEvent', None)

    def safe_wheel_event(self, event):
        # If it's a combobox with open popup list, allow normal behavior
        if isinstance(self, QComboBox):
            view = self.view()
            if view is not None and view.isVisible():
                if orig_wheel:
                    orig_wheel(self, event)
                return
        forward_wheel_to_scroll_parent(self, event)
        event.ignore()

    cls.wheelEvent = safe_wheel_event
    cls._mbt_no_wheel_patched = True


def install_systemwide_no_wheel_protection(app=None) -> NoWheelControlsFilter:
    """Install universal accidental scroll protection system-wide on QApplication."""
    global _GLOBAL_FILTER
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError('QApplication must be initialized before installing no-wheel protection')

    if _GLOBAL_FILTER is not None:
        return _GLOBAL_FILTER

    _GLOBAL_FILTER = NoWheelControlsFilter(app)
    app.installEventFilter(_GLOBAL_FILTER)

    # Class-level patches
    for cls in (QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit, QAbstractSpinBox, QSlider):
        _patch_wheel_event(cls)

    log.info('System-wide accidental scroll protection installed successfully.')
    return _GLOBAL_FILTER


# Backward compatibility helpers
def install_no_wheel_spinboxes(app=None):
    return install_systemwide_no_wheel_protection(app)
