"""Application-wide protection from faulty touchscreens and queued click-through.

Normal single clicks and double-clicks are preserved. Only an implausible burst
of presses, or the short click-through window after a modal closes, is blocked.
"""

from __future__ import annotations

from collections import deque
import logging
import time
import weakref

log = logging.getLogger(__name__)

_FILTER = None


def install_input_burst_guard() -> None:
    """Install the guard once on the current QApplication."""
    global _FILTER
    if _FILTER is not None:
        return
    try:
        from PyQt5.QtCore import QEvent, QObject
        from PyQt5.QtWidgets import QApplication, QDialog, QWidget
    except Exception:
        return

    app = QApplication.instance()
    if app is None:
        return

    class _InputBurstFilter(QObject):
        def __init__(self):
            super().__init__(app)
            self._presses_by_object = weakref.WeakKeyDictionary()
            self._blocked_until_by_object = weakref.WeakKeyDictionary()
            self._clickthrough_until = 0.0

        @staticmethod
        def _target(obj) -> str:
            try:
                return f"{type(obj).__name__}:{obj.objectName() or '-'}"
            except Exception:
                return type(obj).__name__

        def eventFilter(self, obj, event):  # noqa: N802
            try:
                now = time.monotonic()
                et = event.type()

                if isinstance(obj, QDialog) and et in (QEvent.Hide, QEvent.Close):
                    # Prevent a release/queued press intended for the dialog from
                    # activating the newly exposed control underneath it.
                    if obj.isModal() or obj.windowModality():
                        self._clickthrough_until = max(
                            self._clickthrough_until, now + 0.22)
                    return False

                if et not in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
                    return False
                if not isinstance(obj, QWidget):
                    return False

                if now < self._clickthrough_until:
                    log.warning("Blocked click-through on %s", self._target(obj))
                    event.accept()
                    return True

                target = self._target(obj)
                if now < self._blocked_until_by_object.get(obj, 0.0):
                    log.warning("Blocked repeated hardware input on %s", target)
                    event.accept()
                    return True
                presses = self._presses_by_object.setdefault(obj, deque())
                while presses and now - presses[0] > 0.30:
                    presses.popleft()
                presses.append(now)

                # Scope the fault signature to one physical control. Rapid taps
                # across different product cards are normal cashier input.
                # Four presses on the exact same widget within 300 ms are not.
                if len(presses) >= 4:
                    self._blocked_until_by_object[obj] = now + 0.7
                    presses.clear()
                    log.error("Blocked same-control input burst on %s", target)
                    event.accept()
                    return True
            except RuntimeError:
                return False
            except Exception:
                log.exception("Input burst guard failure")
            return False

    _FILTER = _InputBurstFilter()
    app.installEventFilter(_FILTER)

