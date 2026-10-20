"""Guards for the crash families behind the 0xC0000005 origin outage.

3.0.75 died on the main thread inside ``sip.cp311-win_amd64.pyd`` while the
process was leaving ``desktop.main.main()``: CPython finalization ran PyQt5's
exit hook over sip's wrapper map with the web dashboard, cloud and AI daemon
threads still live. These tests pin the three source-side rules that keep that
window shut — leave the process without finalization, never create or touch Qt
objects off the GUI thread, and never let a process-wide singleton keep calling
back into a destroyed widget.
"""
from __future__ import annotations

import inspect
import logging
import os
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QLabel

APP = QApplication.instance() or QApplication([])


class DeterministicShutdownTests(unittest.TestCase):
    """``main()`` must not hand the exit path to CPython finalization."""

    def test_shutdown_stops_services_and_leaves_without_finalization(self):
        from desktop import main as desktop_main

        order: list[str] = []
        with patch.object(desktop_main, '_stop_web_dashboard',
                          side_effect=lambda: order.append('web')), \
                patch.object(logging, 'shutdown',
                             side_effect=lambda *a: order.append('logging')), \
                patch.object(desktop_main.os, '_exit',
                             side_effect=lambda code: order.append(f'exit:{code}')):
            desktop_main._shutdown_and_exit(7)

        self.assertEqual(order, ['web', 'logging', 'exit:7'])

    def test_shutdown_survives_a_non_integer_exit_code(self):
        from desktop import main as desktop_main

        codes: list[int] = []
        with patch.object(desktop_main, '_stop_web_dashboard'), \
                patch.object(desktop_main.os, '_exit', side_effect=codes.append):
            desktop_main._shutdown_and_exit(None)

        self.assertEqual(codes, [0])

    def test_shutdown_ignores_a_failing_web_dashboard_stop(self):
        from desktop import main as desktop_main

        codes: list[int] = []
        with patch.object(desktop_main, '_stop_web_dashboard',
                          side_effect=RuntimeError('waitress wedged')), \
                patch.object(desktop_main.os, '_exit', side_effect=codes.append):
            desktop_main._shutdown_and_exit(0)

        self.assertEqual(codes, [0])

    def test_main_never_returns_through_the_interpreter_finalizer(self):
        from desktop import main as desktop_main

        source = inspect.getsource(desktop_main.main)
        self.assertIn('_shutdown_and_exit(app.exec_())', source)
        self.assertNotIn('sys.exit(app.exec_())', source)


class _Subscriber:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def on_conn(self, online: bool) -> None:
        self.calls.append(online)


class ConnectivitySubscriberTests(unittest.TestCase):
    """The AI watch singleton must not outlive-and-poke its subscribers."""

    def _conn(self):
        from desktop.utils.ai.connectivity import AiConnectivity
        return AiConnectivity()

    def test_bound_method_subscriber_is_released_with_its_owner(self):
        conn = self._conn()
        sub = _Subscriber()
        conn.subscribe(sub.on_conn)
        conn._emit(True)
        self.assertEqual(sub.calls, [True])

        del sub
        conn._emit(False)
        self.assertEqual(conn._listeners, [])

    def test_plain_callables_are_still_held(self):
        conn = self._conn()
        seen: list[bool] = []
        conn.subscribe(seen.append)
        conn._emit(True)
        self.assertEqual(seen, [True])

    def test_unsubscribe_removes_the_listener(self):
        conn = self._conn()
        sub = _Subscriber()
        conn.subscribe(sub.on_conn)
        conn.unsubscribe(sub.on_conn)
        conn._emit(True)
        self.assertEqual(sub.calls, [])

    def test_a_raising_listener_does_not_stop_the_others(self):
        conn = self._conn()
        seen: list[bool] = []

        def boom(online: bool) -> None:
            raise RuntimeError('wrapped C/C++ object has been deleted')

        conn.subscribe(boom)
        conn.subscribe(seen.append)
        conn._emit(True)
        self.assertEqual(seen, [True])

    def test_destroyed_panel_skips_its_queued_banner_refresh(self):
        import sip

        from desktop.utils.lifecycle import defer, is_alive

        label = QLabel('banner')
        fired: list[int] = []
        sip.delete(label)

        self.assertFalse(is_alive(label))
        self.assertIsNone(defer(label, 0, lambda: fired.append(1)))
        APP.processEvents()
        self.assertEqual(fired, [])


class UiDispatchTests(unittest.TestCase):
    def test_dispatch_reports_failure_instead_of_dropping_silently(self):
        from desktop.utils import qt_dispatch

        results: list[bool] = []

        def worker() -> None:
            results.append(qt_dispatch.run_on_ui_thread(lambda: None))

        with patch.object(qt_dispatch, '_dispatcher', None):
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(5)

        self.assertEqual(results, [False])

    def test_dispatch_runs_inline_on_the_gui_thread(self):
        from desktop.utils.qt_dispatch import run_on_ui_thread

        ran: list[int] = []
        self.assertTrue(run_on_ui_thread(lambda: ran.append(1)))
        self.assertEqual(ran, [1])


class AudioThreadAffinityTests(unittest.TestCase):
    """Audio is played from POS worker threads; Qt objects stay on the GUI thread."""

    def _manager(self):
        from desktop.utils.audio_manager import AudioManager
        return AudioManager()

    def test_no_timer_owner_off_the_gui_thread(self):
        manager = self._manager()
        owners: list[object] = []
        thread = threading.Thread(target=lambda: owners.append(manager._qt_timer_owner()))
        thread.start()
        thread.join(5)
        self.assertEqual(owners, [None])

    def test_timer_owner_on_the_gui_thread_is_a_parent(self):
        manager = self._manager()
        self.assertIsNotNone(manager._qt_timer_owner())

    def test_group_debounce_off_the_gui_thread_creates_no_qtimer(self):
        manager = self._manager()
        manager._group_pending.clear()
        manager._group_timers.clear()
        played: list[str] = []

        with patch.object(type(manager), 'play',
                          side_effect=lambda ev, **kw: played.append(ev)):
            thread = threading.Thread(
                target=lambda: manager._schedule_group('sale', 'sale_item', 60, 1))
            thread.start()
            thread.join(5)
            self.assertEqual(manager._group_timers, {})
            for _ in range(40):
                if played:
                    break
                threading.Event().wait(0.05)

        self.assertEqual(played, ['sale_item'])

    def test_group_debounce_on_the_gui_thread_parents_its_timer(self):
        manager = self._manager()
        manager._group_pending.clear()
        manager._group_timers.clear()

        manager._schedule_group('sale', 'sale_item', 5_000, 1)
        timer = manager._group_timers.get('sale')
        self.assertIsInstance(timer, QTimer)
        self.assertIsNotNone(timer.parent())
        timer.stop()
        manager._group_timers.clear()
        manager._group_pending.clear()


if __name__ == '__main__':
    unittest.main()
