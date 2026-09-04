"""Collapsible + resizable left navigation (v3.0.75).

Covers the shell splitter, the collapse control, QSettings persistence, width
clamping, role gating in both modes, and single-shot signal wiring.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt5.QtCore import QEvent, QSettings, Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QWidget  # noqa: E402

from desktop.utils import sidebar_prefs as prefs  # noqa: E402


# PyQt5 keeps no Python reference to QApplication: drop it and the C++ object is
# destroyed under the still-live widgets (native fastfail on Windows).
_APP = None


def _app():
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication(sys.argv[:1] or ['mbt-tests'])
    return _APP


CASHIER = {
    'user': {
        'username': 'till1',
        'full_name': 'Till One',
        'role': 'cashier',
        'tab_permissions': ['dashboard', 'sales', 'debt', 'notes'],
    }
}

ADMIN = {
    'user': {
        'username': 'admin',
        'full_name': 'Shop Admin',
        'role': 'admin',
        'tab_permissions': [],
    }
}


def _probe_class():
    """Build a shell probe that runs the real sidebar code paths.

    Only the topbar/statusbar factories are stubbed — they pull in updater,
    theme-switch and clock machinery that has nothing to do with the sidebar.
    """
    import desktop.main as main

    class _ShellProbe(QMainWindow):
        _TAB_LABELS = main.MainWindow._TAB_LABELS
        _build_ui = main.MainWindow._build_ui
        _build_sidebar = main.MainWindow._build_sidebar
        _sidebar_screen_width = main.MainWindow._sidebar_screen_width
        _sidebar_window_width = main.MainWindow._sidebar_window_width
        _restore_sidebar_prefs = main.MainWindow._restore_sidebar_prefs
        _connect_sidebar = main.MainWindow._connect_sidebar
        _toggle_sidebar = main.MainWindow._toggle_sidebar
        _repolish = staticmethod(main.MainWindow._repolish)
        _NAV_LABEL_CHROME = main.MainWindow._NAV_LABEL_CHROME
        _elide_nav_label = main.MainWindow._elide_nav_label
        _on_sidebar_resized = main.MainWindow._on_sidebar_resized
        _relabel_nav = main.MainWindow._relabel_nav
        _apply_sidebar_chrome = main.MainWindow._apply_sidebar_chrome
        _apply_sidebar_state = main.MainWindow._apply_sidebar_state
        _on_sidebar_splitter_moved = main.MainWindow._on_sidebar_splitter_moved
        _reclamp_sidebar_for_window = main.MainWindow._reclamp_sidebar_for_window
        _queue_sidebar_save = main.MainWindow._queue_sidebar_save
        _persist_sidebar_prefs = main.MainWindow._persist_sidebar_prefs
        _reset_sidebar_width = main.MainWindow._reset_sidebar_width
        set_pos_focus_mode = main.MainWindow.set_pos_focus_mode

        def __init__(self, user_data, size=(1440, 900)):
            super().__init__()
            self.user_data = user_data
            self._tabs = {}
            self._active_tab_id = None
            self.goto_calls = []
            self.resize(*size)
            self._build_ui()

        # ── stubbed shell chrome ────────────────────────────────────────────
        def _build_topbar(self):
            bar = QWidget()
            bar.setObjectName('topbar')
            bar.setFixedHeight(56)
            self._topbar = bar
            self._page_title = QLabel('Dashboard', bar)
            return bar

        def _build_statusbar(self):
            bar = QWidget()
            bar.setObjectName('statusBar')
            bar.setFixedHeight(36)
            self._status_bar = bar
            return bar

        # MainWindow.eventFilter also drives idle logout; only the sidebar leg
        # is in scope here (its routing is asserted at source level below).
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Resize and obj is getattr(self, '_sidebar', None):
                self._on_sidebar_resized()
            return False

        def _goto(self, tid):
            self.goto_calls.append(tid)
            self._active_tab_id = tid
            for bid, btn in self._nav.items():
                btn.setChecked(bid == tid)

        def _logout(self):
            pass

        def _exit_pos_focus_mode(self):
            self.set_pos_focus_mode(False)

    return _ShellProbe


class SidebarPrefsLogicTests(unittest.TestCase):
    """Pure clamp/default maths — no widgets, no display."""

    def test_collapsed_width_is_a_nav_rail(self):
        self.assertGreaterEqual(prefs.COLLAPSED_WIDTH, 56)
        self.assertLessEqual(prefs.COLLAPSED_WIDTH, 72)

    def test_expanded_band_cannot_eat_the_pos(self):
        self.assertGreaterEqual(prefs.EXPANDED_MIN, 180)
        self.assertGreaterEqual(prefs.EXPANDED_MAX, 280)
        self.assertLessEqual(prefs.EXPANDED_MAX, 360)
        self.assertLess(prefs.EXPANDED_MIN, prefs.EXPANDED_MAX)

    def test_absurd_saved_widths_are_clamped(self):
        self.assertEqual(prefs.clamp_sidebar_width(5000, 1920), prefs.EXPANDED_MAX)
        self.assertEqual(prefs.clamp_sidebar_width(10, 1920), prefs.EXPANDED_MIN)
        self.assertEqual(prefs.clamp_sidebar_width(-999, 1920), prefs.EXPANDED_MIN)

    def test_garbage_saved_width_falls_back_to_default(self):
        self.assertEqual(prefs.clamp_sidebar_width('not-a-number', 1920),
                         prefs.DEFAULT_WIDTH)
        self.assertEqual(prefs.clamp_sidebar_width(None, 1920), prefs.DEFAULT_WIDTH)

    def test_width_never_exceeds_a_fraction_of_the_window(self):
        for window in (1024, 1280, 1366, 1920, 3840):
            allowed = prefs.max_width_for_window(window)
            self.assertLessEqual(allowed, prefs.EXPANDED_MAX)
            self.assertGreaterEqual(allowed, prefs.EXPANDED_MIN)
            self.assertLessEqual(prefs.clamp_sidebar_width(9999, window), allowed)
        # A 4K sidebar width restored onto a 1024 till must shrink, not clip.
        self.assertLess(prefs.clamp_sidebar_width(340, 1024), 340)

    def test_defaults_follow_the_screen(self):
        self.assertEqual(prefs.default_sidebar_state(1024), (True, prefs.COMPACT_WIDTH))
        self.assertEqual(prefs.default_sidebar_state(1366), (False, prefs.COMPACT_WIDTH))
        self.assertEqual(prefs.default_sidebar_state(1920), (False, prefs.DEFAULT_WIDTH))
        self.assertEqual(prefs.default_sidebar_state(0), (False, prefs.DEFAULT_WIDTH))
        self.assertTrue(prefs.is_small_screen(1366))
        self.assertFalse(prefs.is_small_screen(1440))


class SidebarSourceTests(unittest.TestCase):
    """Guard the wiring the widget probe cannot reach."""

    def _main_source(self):
        with open(os.path.join(ROOT, 'desktop', 'main.py'), 'r',
                  encoding='utf-8', errors='replace') as fh:
            return fh.read()

    def test_event_filter_routes_sidebar_resizes(self):
        source = self._main_source()
        start = source.index('def eventFilter')
        block = source[start:start + 900]
        self.assertIn("QEvent.Resize and obj is getattr(self, '_sidebar', None)", block)
        self.assertIn('self._on_sidebar_resized()', block)

    def test_resize_event_reclamps_the_sidebar(self):
        source = self._main_source()
        start = source.index('def resizeEvent')
        block = source[start:start + 900]
        self.assertIn('self._reclamp_sidebar_for_window()', block)

    def test_sidebar_width_is_not_frozen_in_qss(self):
        with open(os.path.join(ROOT, 'desktop', 'utils', 'theme.py'), 'r',
                  encoding='utf-8', errors='replace') as fh:
            theme_source = fh.read()
        start = theme_source.index('#sidebar {{')
        block = theme_source[start:theme_source.index('}}', start)]
        self.assertNotIn('min-width', block)
        self.assertNotIn('max-width', block)
        # Collapsed rail styling must stay keyed to the same object name.
        self.assertIn('#navBtn[navCollapsed="true"]', theme_source)
        self.assertIn('#shellSplitter::handle:horizontal', theme_source)

    def test_sidebar_never_writes_shop_wide_settings(self):
        """Persistence must not route through the permission-gated settings API."""
        with open(os.path.join(ROOT, 'desktop', 'utils', 'sidebar_prefs.py'), 'r',
                  encoding='utf-8', errors='replace') as fh:
            source = fh.read()
        code = '\n'.join(
            line for line in source.splitlines() if not line.lstrip().startswith('#'))
        code = code.split('"""', 2)[-1]  # drop the module docstring
        for forbidden in ('api.update_settings(', 'self.api', 'update_settings('):
            self.assertNotIn(forbidden, code)
        self.assertIn('QSettings(ORG_NAME, APP_NAME)', code)

        main_source = self._main_source()
        start = main_source.index('def _persist_sidebar_prefs')
        block = main_source[start:start + 600]
        self.assertIn('save_sidebar_prefs', block)
        self.assertNotIn('update_settings', block)


class _IsolatedSettings(unittest.TestCase):
    """Redirect QSettings at an INI file so no developer preference is touched."""

    def setUp(self):
        _app()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._ini = os.path.join(self._tmpdir.name, 'ui-prefs.ini')
        self._patch = patch.object(
            prefs, 'sidebar_settings',
            lambda: QSettings(self._ini, QSettings.IniFormat))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmpdir.cleanup()

    def _seed(self, collapsed, width):
        prefs.save_sidebar_prefs(collapsed, width)


class SidebarPersistenceTests(_IsolatedSettings):
    def test_roundtrip_survives_a_simulated_restart(self):
        self.assertTrue(prefs.save_sidebar_prefs(True, 312))
        # A brand-new QSettings object reading the same file == next launch.
        loaded = prefs.load_sidebar_prefs(available_width=1920, window_width=1920)
        self.assertTrue(loaded['collapsed'])
        self.assertEqual(loaded['width'], 312)

        prefs.save_sidebar_prefs(False, 208)
        loaded = prefs.load_sidebar_prefs(available_width=1920, window_width=1920)
        self.assertFalse(loaded['collapsed'])
        self.assertEqual(loaded['width'], 208)

    def test_missing_preference_uses_screen_default(self):
        loaded = prefs.load_sidebar_prefs(available_width=1920, window_width=1920)
        self.assertFalse(loaded['collapsed'])
        self.assertEqual(loaded['width'], prefs.DEFAULT_WIDTH)

        loaded = prefs.load_sidebar_prefs(available_width=1024, window_width=1024)
        self.assertTrue(loaded['collapsed'])

    def test_invalid_saved_width_is_clamped_on_load(self):
        settings = QSettings(self._ini, QSettings.IniFormat)
        settings.beginGroup(prefs.SETTINGS_GROUP)
        settings.setValue(prefs.KEY_WIDTH, 5000)
        settings.setValue(prefs.KEY_COLLAPSED, 'false')
        settings.endGroup()
        settings.sync()

        loaded = prefs.load_sidebar_prefs(available_width=1024, window_width=1024)
        self.assertLessEqual(loaded['width'], prefs.max_width_for_window(1024))
        self.assertGreaterEqual(loaded['width'], prefs.EXPANDED_MIN)

        settings.beginGroup(prefs.SETTINGS_GROUP)
        settings.setValue(prefs.KEY_WIDTH, 10)
        settings.endGroup()
        settings.sync()
        loaded = prefs.load_sidebar_prefs(available_width=1920, window_width=1920)
        self.assertEqual(loaded['width'], prefs.EXPANDED_MIN)


class SidebarShellTests(_IsolatedSettings):
    """Live widget behaviour on the real splitter shell."""

    def setUp(self):
        super().setUp()
        self._probes = []
        # Pin the starting state: the screen-size default would otherwise differ
        # between a developer's 1080p run and an offscreen CI/full-suite run.
        self._seed(False, prefs.DEFAULT_WIDTH)

    def tearDown(self):
        for probe in self._probes:
            probe.close()
            probe.deleteLater()
        _app().processEvents()
        super().tearDown()

    def _build(self, user_data=ADMIN, size=(1440, 900)):
        probe = _probe_class()(user_data, size=size)
        # Real layout maths without a window flashing on the QA machine.
        probe.setAttribute(Qt.WA_DontShowOnScreen, True)
        probe.show()
        _app().processEvents()
        self._probes.append(probe)
        return probe

    # ── structure ───────────────────────────────────────────────────────────
    def test_shell_uses_a_splitter_with_content_stretch(self):
        probe = self._build()
        split = probe._shell_splitter
        self.assertEqual(split.orientation(), Qt.Horizontal)
        self.assertFalse(split.childrenCollapsible())
        self.assertEqual(split.indexOf(probe._sidebar), 0)
        self.assertEqual(split.count(), 2)
        # Sidebar keeps its width, every extra pixel goes to the workspace.
        self.assertEqual(split.widget(0).objectName(), 'sidebar')
        self.assertEqual(split.widget(1).objectName(), 'content')

    def test_workspace_fills_the_window_with_no_blank_stripe(self):
        probe = self._build(size=(1600, 900))
        split = probe._shell_splitter
        sizes = split.sizes()
        self.assertEqual(len(sizes), 2)
        self.assertEqual(sum(sizes) + split.handleWidth(), split.width())
        self.assertGreater(sizes[1], sizes[0] * 3)

        content_before = split.sizes()[1]
        probe._toggle_sidebar()
        _app().processEvents()
        # Collapsing hands the reclaimed pixels to the POS pane.
        self.assertGreater(split.sizes()[1], content_before)

    # ── collapse / expand ───────────────────────────────────────────────────
    def test_collapse_expand_toggles_width_tooltips_and_labels(self):
        probe = self._build()
        probe._goto('sales')
        probe.goto_calls.clear()

        self.assertFalse(probe._sidebar_collapsed)
        self.assertEqual(probe._sidebar_toggle.toolTip(), 'Collapse navigation')
        self.assertGreaterEqual(probe._sidebar.width(), prefs.EXPANDED_MIN)
        self.assertTrue(probe._nav['sales'].text().strip())

        probe._toggle_sidebar()
        _app().processEvents()
        self.assertTrue(probe._sidebar_collapsed)
        self.assertEqual(probe._sidebar_toggle.toolTip(), 'Expand navigation')
        self.assertEqual(probe._sidebar.width(), prefs.COLLAPSED_WIDTH)
        self.assertEqual(probe._sidebar.maximumWidth(), prefs.COLLAPSED_WIDTH)

        probe._toggle_sidebar()
        _app().processEvents()
        self.assertFalse(probe._sidebar_collapsed)
        self.assertEqual(probe._sidebar_toggle.toolTip(), 'Collapse navigation')
        self.assertGreaterEqual(probe._sidebar.width(), prefs.EXPANDED_MIN)

        # Chrome only: no navigation, no tab rebuild, selection preserved.
        self.assertEqual(probe.goto_calls, [])
        self.assertEqual(probe._active_tab_id, 'sales')
        self.assertTrue(probe._nav['sales'].isChecked())

    def test_collapsed_rail_keeps_icons_tooltips_and_highlight(self):
        probe = self._build()
        probe._goto('inventory')
        probe._toggle_sidebar()
        _app().processEvents()

        for tid, btn in probe._nav.items():
            self.assertEqual(btn.text(), '', tid)
            self.assertFalse(btn.icon().isNull(), tid)
            self.assertTrue(btn.toolTip(), tid)
            self.assertNotIn('&&', btn.toolTip())
            self.assertEqual(btn.objectName(), 'navBtn', tid)
            self.assertTrue(btn.property('navCollapsed'), tid)
            self.assertTrue(btn.isVisibleTo(probe._sidebar), tid)
        self.assertTrue(probe._nav['inventory'].isChecked())
        self.assertTrue(probe._sidebar_toggle.isVisibleTo(probe))

        probe._toggle_sidebar()
        _app().processEvents()
        for tid, btn in probe._nav.items():
            self.assertTrue(btn.text().strip(), tid)
            self.assertFalse(btn.property('navCollapsed'), tid)
        self.assertTrue(probe._nav['inventory'].isChecked())

    def test_labels_elide_instead_of_clipping_when_dragged_narrow(self):
        from PyQt5.QtGui import QFontMetrics

        probe = self._build()
        button = probe._nav['consumption']

        def _apply(width):
            probe._sidebar_width = width
            probe._apply_sidebar_state(persist=False)
            _app().processEvents()
            return button.text().strip()

        wide = _apply(prefs.EXPANDED_MAX)
        narrow = _apply(prefs.EXPANDED_MIN)

        self.assertTrue(narrow)
        self.assertGreaterEqual(len(wide), len(narrow))
        # Full section name is never lost, whatever the label shows.
        self.assertEqual(button.toolTip(), 'Internal Consumption')
        self.assertEqual(button.accessibleName(), 'Internal Consumption')
        budget = max(36, probe._sidebar.width() - probe._NAV_LABEL_CHROME)
        self.assertLessEqual(
            QFontMetrics(button.font()).horizontalAdvance(narrow), budget)

    def test_labels_track_the_width_qt_actually_granted(self):
        """The POS pane can push back: measure the real width, not the request."""
        probe = self._build()
        probe._nav_label_width = -1
        probe._sidebar.setMinimumWidth(prefs.EXPANDED_MIN)
        probe._sidebar.setMaximumWidth(prefs.EXPANDED_MIN)
        _app().processEvents()
        probe._on_sidebar_resized()
        self.assertEqual(probe._nav_label_width, probe._sidebar.width())
        # Guarded: a second call with the same width is a no-op.
        probe._nav['consumption'].setText('sentinel')
        probe._on_sidebar_resized()
        self.assertEqual(probe._nav['consumption'].text(), 'sentinel')

    # ── persistence through the shell ───────────────────────────────────────
    def test_shell_persists_and_restores_state_across_restart(self):
        probe = self._build()
        probe._sidebar_width = 300
        probe._sidebar_collapsed = True
        probe._apply_sidebar_state(persist=True)
        probe._persist_sidebar_prefs()

        reborn = self._build()
        self.assertTrue(reborn._sidebar_collapsed)
        self.assertEqual(reborn._sidebar_width, 300)
        self.assertEqual(reborn._sidebar.width(), prefs.COLLAPSED_WIDTH)

        reborn._toggle_sidebar()
        reborn._persist_sidebar_prefs()
        _app().processEvents()
        third = self._build()
        self.assertFalse(third._sidebar_collapsed)
        self.assertEqual(third._sidebar_width, 300)

    def test_saved_width_is_clamped_to_the_current_window(self):
        self._seed(False, prefs.EXPANDED_MAX)
        probe = self._build(size=(1024, 768))
        allowed = prefs.max_width_for_window(1024)
        self.assertLessEqual(probe._sidebar_width, allowed)
        self.assertLessEqual(probe._sidebar.width(), allowed)
        self.assertGreaterEqual(probe._sidebar.width(), prefs.EXPANDED_MIN)

    def test_saving_never_needs_settings_edit_permission(self):
        """Cashier tills must be able to store their own sidebar preference."""
        probe = self._build(user_data=CASHIER)
        self.assertFalse(hasattr(probe, 'api'))
        probe._sidebar_collapsed = True
        probe._persist_sidebar_prefs()
        self.assertTrue(
            prefs.load_sidebar_prefs(available_width=1920, window_width=1920)['collapsed'])

    # ── small screens ───────────────────────────────────────────────────────
    def test_small_screens_keep_the_control_and_nav_on_screen(self):
        for width, height in ((1024, 768), (1280, 720), (1366, 768)):
            with self.subTest(size=(width, height)):
                probe = self._build(size=(width, height))
                for collapsed in (False, True):
                    probe._sidebar_collapsed = collapsed
                    probe._apply_sidebar_state(persist=False)
                    _app().processEvents()
                    toggle = probe._sidebar_toggle
                    top_left = toggle.mapTo(probe, toggle.rect().topLeft())
                    bottom_right = toggle.mapTo(probe, toggle.rect().bottomRight())
                    self.assertGreaterEqual(top_left.x(), 0)
                    self.assertGreaterEqual(top_left.y(), 0)
                    self.assertLessEqual(bottom_right.x(), width)
                    self.assertLessEqual(bottom_right.y(), height)
                    self.assertGreater(toggle.width(), 0)
                    # POS pane still gets the majority of a cramped screen.
                    self.assertGreater(probe._shell_splitter.sizes()[1], width // 2)

    def test_window_shrink_reclamps_without_a_resize_loop(self):
        probe = self._build(size=(1920, 1080))
        probe._sidebar_width = prefs.EXPANDED_MAX
        probe._apply_sidebar_state(persist=False)
        _app().processEvents()
        self.assertEqual(probe._sidebar.width(), prefs.EXPANDED_MAX)

        probe.resize(1024, 768)
        _app().processEvents()
        probe._reclamp_sidebar_for_window()
        _app().processEvents()
        allowed = prefs.max_width_for_window(1024)
        self.assertLessEqual(probe._sidebar.width(), allowed)
        self.assertFalse(probe._sidebar_applying)
        # Preference is remembered, not overwritten by the temporary clamp.
        self.assertEqual(probe._sidebar_width, prefs.EXPANDED_MAX)

    def test_pos_focus_mode_restores_the_chosen_sidebar_width(self):
        """Hiding a splitter child loses its size — restore, don't even-split."""
        probe = self._build(size=(1600, 900))
        probe._sidebar_width = 300
        probe._apply_sidebar_state(persist=False)
        _app().processEvents()

        probe.set_pos_focus_mode(True)
        _app().processEvents()
        self.assertFalse(probe._sidebar.isVisibleTo(probe))

        probe.set_pos_focus_mode(False)
        _app().processEvents()
        self.assertTrue(probe._sidebar.isVisibleTo(probe))
        self.assertEqual(probe._sidebar.width(), 300)

        probe._sidebar_collapsed = True
        probe._apply_sidebar_state(persist=False)
        probe.set_pos_focus_mode(True)
        probe.set_pos_focus_mode(False)
        _app().processEvents()
        self.assertEqual(probe._sidebar.width(), prefs.COLLAPSED_WIDTH)

    # ── permissions ─────────────────────────────────────────────────────────
    def test_cashier_nav_is_identical_in_both_modes(self):
        probe = self._build(user_data=CASHIER)
        expected = set(CASHIER['user']['tab_permissions'])
        self.assertEqual(set(probe._nav), expected)
        for hidden in ('admin', 'settings', 'security', 'license',
                       'diagnostics', 'ai_ops', 'accounting'):
            self.assertNotIn(hidden, probe._nav)

        probe._toggle_sidebar()
        _app().processEvents()
        self.assertEqual(set(probe._nav), expected)
        self.assertEqual(
            {tid for tid, btn in probe._nav.items() if btn.isVisibleTo(probe._sidebar)},
            expected)

    # ── signal hygiene ──────────────────────────────────────────────────────
    def test_connect_sidebar_is_idempotent(self):
        probe = self._build()
        split = probe._shell_splitter
        toggle = probe._sidebar_toggle
        before_split = split.receivers(split.splitterMoved)
        before_toggle = toggle.receivers(toggle.clicked)
        self.assertEqual(before_split, 1)
        self.assertEqual(before_toggle, 1)

        probe._connect_sidebar()
        probe._connect_sidebar()
        self.assertEqual(split.receivers(split.splitterMoved), before_split)
        self.assertEqual(toggle.receivers(toggle.clicked), before_toggle)

    def test_debounce_timer_is_parented_and_single_shot(self):
        probe = self._build()
        timer = probe._sidebar_save_timer
        self.assertIs(timer.parent(), probe)
        self.assertTrue(timer.isSingleShot())
        self.assertGreaterEqual(timer.interval(), 300)
        self.assertLessEqual(timer.interval(), 700)

    def test_splitter_drag_does_not_feed_back_into_setsizes(self):
        probe = self._build()
        applied = []
        original = probe._shell_splitter.setSizes

        def _record(sizes):
            applied.append(list(sizes))
            original(sizes)

        probe._shell_splitter.setSizes = _record
        probe._on_sidebar_splitter_moved(240, 1)
        _app().processEvents()
        self.assertEqual(applied, [])


class ShellSplitterHandleTests(_IsolatedSettings):
    """The gutter must look grabbable, not like a decorative divider.

    v3.0.75 shipped a 4px handle painted in ``border`` — the same colour the
    sidebar already uses for its own right border — so users reported the
    sidebar as "not resizable". These guard the painted grip that replaced it.
    """

    def setUp(self):
        super().setUp()
        self._probes = []
        self._seed(False, prefs.DEFAULT_WIDTH)
        from desktop.utils.theme import ThemeManager
        self._was_light = ThemeManager.is_light()

    def tearDown(self):
        from desktop.utils.theme import ThemeManager
        ThemeManager.apply(self._was_light, force=True)
        for probe in self._probes:
            probe.close()
            probe.deleteLater()
        _app().processEvents()
        super().tearDown()

    def _build(self, size=(1440, 900)):
        probe = _probe_class()(ADMIN, size=size)
        probe.setAttribute(Qt.WA_DontShowOnScreen, True)
        probe.show()
        _app().processEvents()
        self._probes.append(probe)
        return probe

    @staticmethod
    def _column_colours(handle):
        """(track colour away from the grip, colour through the grip centre)."""
        image = handle.grab().toImage()
        x = handle.width() // 2
        track = image.pixelColor(x, 6)
        grip = image.pixelColor(x, handle.height() // 2)
        return track, grip

    @staticmethod
    def _delta(a, b) -> int:
        return (abs(a.red() - b.red()) + abs(a.green() - b.green())
                + abs(a.blue() - b.blue()))

    # ── structure ───────────────────────────────────────────────────────────
    def test_handle_is_wide_enough_to_grab(self):
        from desktop.utils import shell_splitter

        probe = self._build()
        split = probe._shell_splitter
        self.assertTrue(split.inherits('QSplitter'))
        self.assertEqual(split.handleWidth(), shell_splitter.HANDLE_W)
        # A 4px gutter is what made this feel like a border, not a control.
        self.assertGreaterEqual(split.handleWidth(), 8)
        handle = split.handle(1)
        self.assertIsInstance(handle, shell_splitter.ShellSplitterHandle)
        self.assertEqual(handle.width(), shell_splitter.HANDLE_W)
        self.assertGreater(handle.height(), 0)

    def test_handle_advertises_drag_and_reset(self):
        probe = self._build()
        handle = probe._shell_splitter.handle(1)
        self.assertEqual(handle.cursor().shape(), Qt.SplitHCursor)
        tip = handle.toolTip().lower()
        self.assertIn('drag', tip)
        self.assertIn('resize', tip)
        self.assertIn('double-click', tip)
        # A drag can never delete the sidebar.
        self.assertFalse(probe._shell_splitter.childrenCollapsible())

    def test_collapsed_rail_makes_the_gutter_inert(self):
        probe = self._build()
        probe._toggle_sidebar()
        _app().processEvents()
        handle = probe._shell_splitter.handle(1)
        self.assertFalse(handle.isEnabled())
        self.assertEqual(handle.cursor().shape(), Qt.ArrowCursor)
        self.assertEqual(handle.toolTip(), '')

        probe._toggle_sidebar()
        _app().processEvents()
        self.assertTrue(handle.isEnabled())
        self.assertEqual(handle.cursor().shape(), Qt.SplitHCursor)
        self.assertTrue(handle.toolTip())

    # ── painting ────────────────────────────────────────────────────────────
    def test_handle_paints_a_grip_that_contrasts_on_both_themes(self):
        from desktop.utils.theme import C, ThemeManager

        for light in (False, True):
            with self.subTest(theme='light' if light else 'dark'):
                ThemeManager.apply(light, force=True)
                probe = self._build()
                handle = probe._shell_splitter.handle(1)
                track, grip = self._column_colours(handle)

                # The grip must be a distinct shape inside the gutter, not a
                # flat fill that reads as one more border line.
                self.assertGreater(self._delta(track, grip), 45)
                # ...and the gutter itself must separate from both neighbours.
                from PyQt5.QtGui import QColor
                for token in ('sidebar', 'surface'):
                    neighbour = QColor(C[token])
                    self.assertGreater(
                        self._delta(track, neighbour), 30,
                        f'gutter is invisible against {token}')
                self.assertGreater(self._delta(grip, QColor(C['sidebar'])), 45)

    def test_hover_lights_the_grip_gold(self):
        from PyQt5.QtGui import QColor
        from desktop.utils.theme import C

        probe = self._build()
        handle = probe._shell_splitter.handle(1)
        _track, resting = self._column_colours(handle)

        handle._hover = True
        _track, hovered = self._column_colours(handle)
        handle._hover = False

        self.assertGreater(self._delta(resting, hovered), 45)
        self.assertLess(self._delta(hovered, QColor(C['gold'])), 40)

    def test_handle_paint_is_not_overpainted_by_qss(self):
        """QSS may reserve the width, but must not fill the gutter."""
        from desktop.utils import shell_splitter
        from desktop.utils.theme import MBT_STYLESHEET

        start = MBT_STYLESHEET.index('#shellSplitter::handle')
        block = MBT_STYLESHEET[start:MBT_STYLESHEET.index('}', start)]
        self.assertIn('background: transparent', block)
        self.assertIn(f'width: {shell_splitter.HANDLE_W}px', block)

    # ── double-click reset ──────────────────────────────────────────────────
    def test_double_click_resets_the_sidebar_to_its_default_width(self):
        probe = self._build()
        probe._sidebar_width = prefs.EXPANDED_MAX
        probe._apply_sidebar_state(persist=False)
        _app().processEvents()
        self.assertEqual(probe._sidebar.width(), prefs.EXPANDED_MAX)

        handle = probe._shell_splitter.handle(1)
        handle.mouseDoubleClickEvent(
            _double_click_event(handle.rect().center()))
        _app().processEvents()

        expected = prefs.default_sidebar_state(probe._sidebar_screen_width())[1]
        self.assertEqual(probe._sidebar_width, expected)
        self.assertEqual(probe._sidebar.width(), expected)
        # Reset is a width gesture only — it must not collapse the rail.
        self.assertFalse(probe._sidebar_collapsed)

    def test_reset_is_ignored_while_the_rail_is_collapsed(self):
        probe = self._build()
        probe._toggle_sidebar()
        _app().processEvents()
        handle = probe._shell_splitter.handle(1)
        handle.mouseDoubleClickEvent(
            _double_click_event(handle.rect().center()))
        _app().processEvents()
        self.assertTrue(probe._sidebar_collapsed)
        self.assertEqual(probe._sidebar.width(), prefs.COLLAPSED_WIDTH)

    def test_reset_callback_is_wired_once(self):
        probe = self._build()
        split = probe._shell_splitter
        self.assertTrue(callable(split._reset_cb))
        probe._connect_sidebar()
        probe._connect_sidebar()
        self.assertEqual(split.receivers(split.splitterMoved), 1)
        self.assertEqual(
            probe._sidebar_toggle.receivers(probe._sidebar_toggle.clicked), 1)

    def test_reset_persists_through_the_debounce_not_per_pixel(self):
        probe = self._build()
        writes = []
        probe._persist_sidebar_prefs = lambda: writes.append(1)
        probe._sidebar_width = prefs.EXPANDED_MAX
        probe._apply_sidebar_state(persist=False)
        probe._reset_sidebar_width()
        _app().processEvents()
        # Queued on the shared single-shot timer, never written inline.
        self.assertEqual(writes, [])
        self.assertTrue(probe._sidebar_save_timer.isActive())


def _double_click_event(pos):
    from PyQt5.QtCore import QEvent as _QEvent
    from PyQt5.QtGui import QMouseEvent

    return QMouseEvent(_QEvent.MouseButtonDblClick, pos,
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


if __name__ == '__main__':
    unittest.main()
