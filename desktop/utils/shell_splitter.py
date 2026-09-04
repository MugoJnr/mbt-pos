"""The draggable gutter between the navigation sidebar and the workspace.

A stylesheet-only handle is not a discoverable control.  The shipped
``#shellSplitter::handle`` rule painted a 4px strip in ``border`` — the exact
colour the sidebar already uses for its own ``border-right`` — so the drag
affordance read as a decorative divider and users reported the sidebar as "not
resizable" even though the splitter worked.

This mirrors ``desktop.pos.layouts.splitters.PosSplitterHandle``, which solved
the same problem for the checkout gutters: a wider hit target, a painted grip
pill that contrasts with both neighbouring panes, gold hover/press feedback, a
split cursor, and a double-click reset.  Colours are read from the live ``C``
palette on every repaint, so a light/dark switch retints the grip without any
extra bookkeeping.
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QSplitter, QSplitterHandle, QWidget

# Wide enough to hit with a trackpad on a 150% display while still reading as a
# gutter rather than a third pane. The POS gutters use 16px; the shell edge is
# narrower because every pixel here comes out of the workspace.
HANDLE_W = 10

TOOLTIP = 'Drag to resize navigation — double-click to reset'

# Grip pill geometry (logical px). "Hot" = hovered or being dragged.
_GRIP_LEN = 88.0
_GRIP_LEN_HOT = 132.0
_GRIP_THICK = 4.0
_GRIP_THICK_HOT = 5.0


class ShellSplitterHandle(QSplitterHandle):
    """Painted grip for the sidebar edge.

    Dragging is driven explicitly through ``moveSplitter`` + ``grabMouse`` for
    the same reason the POS handles do it: the app-wide ``QSplitter::handle``
    stylesheet rule and sibling paint effects can otherwise leave the handle
    looking live while the panes never move.
    """

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._hover = False
        self._dragging = False
        self._press_offset = 0
        self.setToolTip(TOOLTIP)
        self.setAttribute(Qt.WA_Hover, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.SplitHCursor)

    # ── hover / drag ────────────────────────────────────────────────────────
    def setEnabled(self, enabled):  # noqa: N802 - Qt naming
        # Collapsed rail: the handle is inert, so drop any latched hover state
        # and stop advertising a drag the user cannot perform.
        if not enabled:
            self._hover = False
            self._dragging = False
        self.setCursor(Qt.SplitHCursor if enabled else Qt.ArrowCursor)
        self.setToolTip(TOOLTIP if enabled else '')
        super().setEnabled(enabled)
        self.update()

    def enterEvent(self, event):
        if self.isEnabled():
            self._hover = True
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._dragging:
            self._hover = False
            self.update()
        super().leaveEvent(event)

    def _splitter_pos_from_global(self, global_pos) -> int:
        sp = self.splitter()
        return int(sp.mapFromGlobal(global_pos).x()) - int(self._press_offset)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            # Offset inside the handle so the grip does not jump under the cursor.
            self._press_offset = int(event.pos().x())
            self._dragging = True
            self.grabMouse()
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.LeftButton):
            try:
                self.moveSplitter(self._splitter_pos_from_global(event.globalPos()))
            except Exception:
                pass
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _release_grab(self):
        try:
            if QWidget.mouseGrabber() is self:
                self.releaseMouse()
        except Exception:
            try:
                self.releaseMouse()
            except Exception:
                pass

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self._release_grab()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._dragging = False
        self._release_grab()
        sp = self.splitter()
        reset = getattr(sp, 'reset_to_defaults', None) if sp is not None else None
        if self.isEnabled() and callable(reset):
            reset()
            self.update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ── paint ───────────────────────────────────────────────────────────────
    def _is_hot(self) -> bool:
        if not self.isEnabled():
            return False
        return bool(self._hover or self._dragging or self.underMouse())

    def paintEvent(self, event):
        from desktop.utils.theme import C

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)

        hot = self._is_hot()
        # Opaque track: the full-height band is what makes the gutter findable
        # at a glance. ``border`` contrasts with the sidebar fill on both themes.
        track = QColor(C.get('border', '#2A4060'))
        if hot:
            # Only a faint warm wash on the track: a heavier tint turns the
            # gutter khaki on both palettes. The gold pill carries the feedback.
            gold = QColor(C.get('gold', '#FBBF24'))
            gold.setAlpha(30)
            painter.setBrush(track)
            painter.drawRect(self.rect())
            painter.setBrush(gold)
            painter.drawRect(self.rect())
        elif self.isEnabled():
            painter.setBrush(track)
            painter.drawRect(self.rect())
        else:
            # Collapsed rail: an inert gutter should read as a divider, not as
            # a control. Paint an opaque base first — QSS leaves the handle
            # transparent, so an alpha fill alone composites unpredictably.
            painter.setBrush(QColor(C.get('sidebar', '#0A101C')))
            painter.drawRect(self.rect())
            track.setAlpha(150)
            painter.setBrush(track)
            painter.drawRect(self.rect())
            painter.end()
            return

        grip = QColor(C.get('gold', '#FBBF24') if hot else C.get('border2', '#587AA6'))
        painter.setBrush(grip)
        thick = _GRIP_THICK_HOT if hot else _GRIP_THICK
        length = min(float(self.height()), _GRIP_LEN_HOT if hot else _GRIP_LEN)
        x = (self.width() - thick) / 2.0
        y = (self.height() - length) / 2.0
        painter.drawRoundedRect(
            QRectF(x, y, thick, length), thick / 2.0, thick / 2.0)
        painter.end()


class ShellSplitter(QSplitter):
    """Horizontal splitter that owns the sidebar ↔ workspace gutter."""

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._reset_cb = None
        self.setObjectName('shellSplitter')
        self.setChildrenCollapsible(False)
        self.setOpaqueResize(True)
        self.setHandleWidth(HANDLE_W)

    def createHandle(self):  # noqa: N802 - Qt naming
        return ShellSplitterHandle(self.orientation(), self)

    def set_reset_callback(self, fn) -> None:
        """Register what a double-click on the gutter should restore."""
        self._reset_cb = fn

    def reset_to_defaults(self) -> None:
        if callable(self._reset_cb):
            self._reset_cb()

    def changeEvent(self, event):
        # A light/dark switch re-applies the application stylesheet, which Qt
        # delivers as StyleChange. Custom-painted handles are not covered by
        # that repolish, so retint them explicitly.
        if event.type() in (QEvent.StyleChange, QEvent.PaletteChange):
            self.restyle()
        super().changeEvent(event)

    def restyle(self) -> None:
        for index in range(self.count()):
            handle = self.handle(index)
            if handle is not None:
                handle.update()
        self.update()
