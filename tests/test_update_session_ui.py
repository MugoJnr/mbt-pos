"""Update session copy, installer keep rule, and the on-screen strip.

No shop database and no network. The strip must change state without a dialog
and without a pause.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_ISOLATION = tempfile.mkdtemp(prefix='mbt-update-session-')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['MBT_TEST_INSTANCE'] = '1'
os.environ['MBT_DATA_ROOT'] = _ISOLATION
os.environ['APPDATA'] = _ISOLATION
os.environ['LOCALAPPDATA'] = _ISOLATION
os.environ['PROGRAMDATA'] = _ISOLATION

from PyQt5.QtWidgets import QApplication, QMessageBox

from backend.update_session import (
    FIRST_CHECK_DELAY,
    MAX_INSTALLER_BYTES,
    RECHECK_INTERVAL,
    cached_installer_action,
    session_view,
)
from desktop.utils.theme import ThemeManager
from desktop.utils.update_session_banner import UpdateSessionBanner


def _app():
    app = QApplication.instance() or QApplication([])
    ThemeManager.apply(False, app)
    return app


class UpdateSessionRulesTests(unittest.TestCase):
    def test_real_installer_over_60mb_is_kept(self):
        blocked = {'2.3.5'}
        self.assertEqual(
            cached_installer_action(62_289_758, '3.1.81', '3.1.80', blocked),
            'keep',
        )
        self.assertEqual(
            cached_installer_action(60_000_001, '3.1.82', '3.1.80', blocked),
            'keep',
        )

    def test_blocked_old_tiny_and_huge_files_are_dropped(self):
        blocked = {'2.3.5'}
        self.assertEqual(
            cached_installer_action(80_000_000, '2.3.5', '3.1.80', blocked),
            'drop_blocked',
        )
        self.assertEqual(
            cached_installer_action(70_000_000, '3.1.80', '3.1.80', blocked),
            'drop_old',
        )
        self.assertEqual(
            cached_installer_action(500, '3.1.82', '3.1.80', blocked),
            'drop_small',
        )
        self.assertEqual(
            cached_installer_action(MAX_INSTALLER_BYTES + 1, '3.1.82', '3.1.80', blocked),
            'drop_huge',
        )

    def test_copy_is_short_and_instant(self):
        ready = session_view('complete', '3.1.82', 100)
        self.assertEqual(ready['primary'], 'Install now')
        self.assertIn('Your sales stay.', ready['detail'])
        self.assertLess(len(ready['detail']), 80)
        self.assertIn('You can keep selling.', session_view('downloading', '3.1.82', 40)['detail'])
        started = time.perf_counter()
        for i in range(1000):
            session_view('downloading', '3.1.82', i % 100)
        self.assertLess(time.perf_counter() - started, 0.2)

    def test_recheck_is_a_few_minutes_not_hours(self):
        self.assertEqual(FIRST_CHECK_DELAY, 60)
        self.assertGreaterEqual(RECHECK_INTERVAL, 120)
        self.assertLessEqual(RECHECK_INTERVAL, 300)
        from backend import updater
        self.assertEqual(updater.RECHECK_INTERVAL, RECHECK_INTERVAL)

    def test_dashboard_banner_uses_the_same_lines(self):
        root = Path(_ROOT)
        source = (root / 'web' / 'dashboard-ui' / 'src' / 'lib' / 'update-session.ts').read_text(encoding='utf-8')
        shell = (root / 'web' / 'dashboard-ui' / 'src' / 'components' / 'app-shell.tsx').read_text(encoding='utf-8')
        self.assertIn('You can keep selling.', source)
        self.assertIn('The till will close and reopen.', source)
        self.assertIn('role="status"', shell)
        self.assertIn('role="progressbar"', shell)
        self.assertIn('<TillUpdateNotice />', shell)
        self.assertNotIn('max-w-[320px]', shell.split('function TillUpdateNotice')[1][:1800])


class UpdateBannerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_states_paint_without_a_dialog_or_a_pause(self):
        banner = UpdateSessionBanner()
        banner.resize(900, 80)
        started = time.perf_counter()
        for percent in range(0, 100, 5):
            banner.show_state('downloading', '3.1.82', percent)
            self.app.processEvents()
        banner.show_state('verifying', '3.1.82')
        banner.show_state('complete', '3.1.82', 100)
        self.app.processEvents()
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.0)
        self.assertTrue(banner.isVisible())
        self.assertEqual(banner._title.text(), 'v3.1.82 is ready')
        self.assertEqual(banner._primary.text(), 'Install now')
        self.assertTrue(banner._primary.isVisible())
        self.assertTrue(banner._later.isVisible())
        self.assertEqual(banner._bar.value(), 100)
        self.assertEqual(banner._bar.format(), '%p%')
        self.assertTrue(banner._bar.isVisible())
        self.assertFalse(any(isinstance(w, QMessageBox) for w in self.app.allWidgets()))
        banner.show_state('failed', '3.1.82', detail='Try again.')
        self.assertEqual(banner._primary.text(), 'Try again')
        self.assertFalse(banner._bar.isVisible())
        banner.show_state('idle')
        self.assertFalse(banner.isVisible())

    def test_checker_start_returns_immediately_when_isolated(self):
        from backend.updater import UpdateChecker
        checker = UpdateChecker('3.1.82')
        started = time.perf_counter()
        checker.start()
        elapsed = time.perf_counter() - started
        checker.stop()
        self.assertLess(elapsed, 0.25)
        self.assertFalse(checker._has_updater_lock)


if __name__ == '__main__':
    unittest.main()
