"""
Disable mouse-wheel value changes on numeric spin controls (app-wide).
Backward compatibility wrapper for desktop.utils.no_wheel_controls.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QAbstractSpinBox
from desktop.utils.no_wheel_controls import (
    NoWheelControlsFilter,
    install_systemwide_no_wheel_protection as install_no_wheel_spinboxes,
)


def spinbox_ignores_wheel(spin: QAbstractSpinBox) -> bool:
    """Test helper: True when a synthetic wheel would not change the value."""
    if spin is None:
        return False
    before = spin.value()
    from PyQt5.QtGui import QWheelEvent
    from PyQt5.QtCore import QPoint, QPointF, Qt

    ev = QWheelEvent(
        QPointF(0, 0), QPointF(0, 0),
        QPoint(0, 0), QPoint(0, 120),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
    )
    spin.wheelEvent(ev)
    return abs(float(spin.value()) - float(before)) < 1e-9


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
