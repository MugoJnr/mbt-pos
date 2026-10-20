"""Thread-safe dispatch of callbacks to the Qt application thread."""
from __future__ import annotations

import logging
import threading
from typing import Callable

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import QApplication

log = logging.getLogger("mbt.qt_dispatch")


class _UiDispatcher(QObject):
    requested = pyqtSignal(object)

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.requested.connect(self._execute, Qt.QueuedConnection)

    def _execute(self, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:
            log.exception("Queued UI callback failed")


_dispatcher: _UiDispatcher | None = None


def install_ui_dispatcher(app: QApplication | None = None) -> _UiDispatcher:
    """Create the dispatcher on the UI thread during application startup."""
    global _dispatcher
    if _dispatcher is not None:
        return _dispatcher
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication must exist before installing UI dispatcher")
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("UI dispatcher must be installed from the main thread")
    _dispatcher = _UiDispatcher(app)
    return _dispatcher


def run_on_ui_thread(callback: Callable[[], None]) -> bool:
    """Run now on the GUI thread, otherwise queue safely to that thread.

    Returns ``False`` when the callback could not be delivered, so callers with
    a non-Qt fallback can take it instead of silently losing the work.
    """
    app = QApplication.instance()
    if app is None:
        return False
    dispatcher = _dispatcher
    if dispatcher is None:
        if threading.current_thread() is threading.main_thread():
            dispatcher = install_ui_dispatcher(app)
        else:
            log.error("UI callback dropped before dispatcher installation")
            return False
    if threading.current_thread() is threading.main_thread():
        callback()
    else:
        dispatcher.requested.emit(callback)
    return True
