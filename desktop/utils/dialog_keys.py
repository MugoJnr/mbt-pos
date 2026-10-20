"""Consistent Enter/Escape behaviour for MBT POS dialogs.

Qt makes every ``QPushButton`` in a dialog auto-default, so Enter fires whichever
button happens to sit first in the focus chain — often Cancel or a secondary
lookup action. These helpers pin Enter to the primary, *validated* action and
make sure Cancel can never be triggered implicitly.
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import (
    QAbstractButton, QApplication, QDialogButtonBox, QPlainTextEdit,
    QPushButton, QTextEdit,
)

_MODIFIER_MASK = Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier


class _ReturnRouter(QObject):
    """Routes bare Enter/Return in a dialog to one validated action."""

    def __init__(self, dialog, primary, exempt=()):
        super().__init__(dialog)
        self._dialog = dialog
        self._primary = primary
        self._exempt = list(exempt or ())
        dialog.installEventFilter(self)

    def set_primary(self, primary, exempt=()):
        self._primary = primary
        if exempt:
            self._exempt = list(exempt)

    def _focused_child(self):
        """Focused widget inside this dialog.

        ``QApplication.focusWidget()`` is empty when the dialog is not the
        active window (offscreen rendering, or a background window), which
        would make every field look unfocused and submit anyway.
        """
        try:
            local = self._dialog.focusWidget()
        except RuntimeError:
            return None
        if local is not None:
            return local
        focus = QApplication.focusWidget()
        try:
            if focus is not None and self._dialog.isAncestorOf(focus):
                return focus
        except RuntimeError:
            return None
        return None

    def eventFilter(self, obj, event):
        if obj is not self._dialog or event.type() != QEvent.KeyPress:
            return False
        if event.key() not in (Qt.Key_Return, Qt.Key_Enter):
            return False
        if event.modifiers() & _MODIFIER_MASK:
            return False
        focus = self._focused_child()
        # Multi-line editors own Enter (new line), never submit.
        if isinstance(focus, (QTextEdit, QPlainTextEdit)):
            return False
        # A deliberately focused button keeps its own behaviour.
        if isinstance(focus, QAbstractButton) and focus is not self._primary:
            return False
        # Fields that already act on Return (search / lookup) must not also
        # submit the dialog — the field handled it, so stop here.
        for widget in self._exempt:
            try:
                if widget is focus:
                    return True
            except RuntimeError:
                continue
        primary = self._primary
        if primary is None:
            # No validated action available — swallow Enter rather than let Qt
            # fall through to Cancel or an arbitrary secondary button.
            return True
        try:
            usable = primary.isEnabled() and primary.isVisible()
        except RuntimeError:
            return True
        if usable:
            primary.click()
        return True


def wire_dialog_keys(dialog, primary=None, cancel=None, submit_exempt=()):
    """Pin Enter to ``primary`` and stop any other button auto-defaulting.

    ``primary`` must be the control whose slot performs validation; Enter then
    goes through exactly the same path as a mouse click, so an invalid or
    destructive submission is impossible to trigger by keyboard alone.
    """
    if dialog is None:
        return None
    for btn in dialog.findChildren(QPushButton):
        try:
            btn.setAutoDefault(False)
            btn.setDefault(False)
        except RuntimeError:
            continue
    for box in dialog.findChildren(QDialogButtonBox):
        for btn in box.buttons():
            try:
                btn.setAutoDefault(False)
                btn.setDefault(False)
            except RuntimeError:
                continue
    if cancel is not None:
        try:
            cancel.setAutoDefault(False)
            cancel.setDefault(False)
        except RuntimeError:
            pass
    if primary is not None:
        try:
            primary.setAutoDefault(True)
            primary.setDefault(True)
        except RuntimeError:
            pass
    router = getattr(dialog, '_mbt_return_router', None)
    if router is None:
        router = _ReturnRouter(dialog, primary, submit_exempt)
        dialog._mbt_return_router = router
    else:
        router.set_primary(primary, submit_exempt)
    return router


def default_button_of(dialog):
    """Return the button currently acting as the dialog default (or None)."""
    for btn in dialog.findChildren(QPushButton):
        try:
            if btn.isDefault():
                return btn
        except RuntimeError:
            continue
    return None
