"""Widget lifetime helpers for deferred work and teardown.

``QTimer.singleShot`` keeps firing after the object its closure touches has been
destroyed, which surfaces as ``RuntimeError: wrapped C/C++ object ... has been
deleted``. Everything here binds the timer to an owner so Qt cancels it during
teardown, and double-checks liveness before invoking the callback.
"""
from __future__ import annotations

import logging

from PyQt5.QtCore import QObject, QTimer

log = logging.getLogger('mbt.lifecycle')


def is_alive(obj) -> bool:
    """True when ``obj`` still has a live underlying C++ object."""
    if obj is None:
        return False
    try:
        import sip
        if isinstance(obj, QObject):
            return not sip.isdeleted(obj)
    except Exception:
        pass
    try:
        obj.objectName()
        return True
    except (RuntimeError, AttributeError):
        return False


def defer(owner, msec, fn):
    """Run ``fn`` after ``msec`` ms, but only while ``owner`` still exists.

    The timer is parented to ``owner`` so destroying the owner cancels it. The
    liveness check runs again at fire time to cover the window between the C++
    delete and the Python wrapper going away.
    """
    if not is_alive(owner):
        return None
    timer = QTimer(owner)
    timer.setSingleShot(True)

    def _fire():
        if not is_alive(owner):
            return
        try:
            fn()
        except RuntimeError:
            log.debug('Deferred callback skipped: owner destroyed', exc_info=True)

    timer.timeout.connect(_fire)
    timer.start(max(0, int(msec)))
    return timer


def stop_timers(owner) -> int:
    """Stop every ``QTimer`` owned by ``owner`` (recursively); returns the count.

    Used when a window is retired but Python references may keep it alive for a
    while: an inactive window must not keep polling the database or the network.
    """
    if not is_alive(owner):
        return 0
    stopped = 0
    try:
        timers = owner.findChildren(QTimer)
    except RuntimeError:
        return 0
    for timer in timers:
        try:
            if timer.isActive():
                timer.stop()
                stopped += 1
        except RuntimeError:
            continue
    return stopped
