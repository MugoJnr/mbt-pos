"""S03: MainWindow idle-session logout helpers."""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SessionIdleTests(unittest.TestCase):
    def test_should_idle_logout_after_timeout(self):
        from desktop.main import MainWindow

        stub = MagicMock()
        stub._idle_timeout_sec = 60.0
        stub._idle_logged_out = False
        stub._last_activity_ts = time.time() - 120.0
        stub._idle_elapsed_sec = lambda: MainWindow._idle_elapsed_sec(stub)
        self.assertTrue(MainWindow._should_idle_logout(stub))

        MainWindow._note_user_activity(stub)
        self.assertFalse(MainWindow._should_idle_logout(stub))

    def test_idle_disabled_when_timeout_zero(self):
        from desktop.main import MainWindow

        stub = MagicMock()
        stub._idle_timeout_sec = 0.0
        stub._idle_logged_out = False
        stub._last_activity_ts = time.time() - 10_000
        stub._idle_elapsed_sec = lambda: MainWindow._idle_elapsed_sec(stub)
        self.assertFalse(MainWindow._should_idle_logout(stub))

    def test_check_idle_timeout_calls_logout(self):
        from desktop.main import MainWindow

        stub = MagicMock()
        stub._idle_timeout_sec = 30.0
        stub._idle_logged_out = False
        stub._last_activity_ts = time.time() - 90.0
        stub._idle_elapsed_sec = lambda: MainWindow._idle_elapsed_sec(stub)
        stub._should_idle_logout = lambda: MainWindow._should_idle_logout(stub)
        stub._idle_session_logout = MagicMock()

        MainWindow._check_idle_timeout(stub)
        stub._idle_session_logout.assert_called_once()

    def test_install_idle_watchdog_respects_env_disable(self):
        from desktop.main import MainWindow

        stub = MagicMock()
        stub._idle_timer = None
        with patch.dict(os.environ, {'MBT_SESSION_IDLE_SEC': '0'}, clear=False):
            MainWindow._install_idle_watchdog(stub)
        self.assertEqual(stub._idle_timeout_sec, 0.0)
        self.assertIsNone(stub._idle_timer)


if __name__ == '__main__':
    unittest.main()
