"""Application-wide protection from faulty touchscreens and queued click-through.

Normal single clicks and double-clicks are preserved. Only an implausible burst
of presses, or the short click-through window after a modal closes, is blocked.
"""

from __future__ import annotations

from collections import deque
import logging
import time

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
            self._presses = deque()
            self._blocked_until = 0.0

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
                        self._blocked_until = max(self._blocked_until, now + 0.22)
                    return False

                if et not in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
                    return False
                if not isinstance(obj, QWidget):
                    return False

                if now < self._blocked_until:
                    log.warning("Blocked click-through on %s", self._target(obj))
                    event.accept()
                    return True

                while self._presses and now - self._presses[0][0] > 0.65:
                    self._presses.popleft()
                target = self._target(obj)
                self._presses.append((now, target))

                # Four presses in 650 ms can be a fast legitimate workflow.
                # A fifth is not plausible for deliberate cashier input and is
                # the signature seen from failing touch panels.
                if len(self._presses) >= 5:
                    self._blocked_until = now + 1.0
                    self._presses.clear()
                    log.error("Blocked rapid input burst ending on %s", target)
                    event.accept()
                    return True
            except RuntimeError:
                return False
            except Exception:
                log.exception("Input burst guard failure")
            return False

    _FILTER = _InputBurstFilter()
    app.installEventFilter(_FILTER)

