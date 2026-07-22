"""U02: theme preference persists via system_settings."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ThemePersistTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'test.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self._db_path),
        ]
        for p in self._patches:
            p.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._user_id = 1
        self.api._username = 'admin'

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_update_settings_theme_roundtrip(self):
        self.assertEqual(self.api.update_settings({
            'theme': 'light',
            'ui_theme': 'light',
        }).get('success'), True)
        cfg = self.api.get_settings()
        self.assertEqual(cfg.get('theme'), 'light')
        self.assertEqual(cfg.get('ui_theme'), 'light')

        self.api.update_settings({'theme': 'dark', 'ui_theme': 'dark'})
        cfg = self.api.get_settings()
        self.assertEqual(cfg.get('theme'), 'dark')

    def test_mainwindow_read_save_theme_pref(self):
        """Exercise MainWindow helpers without building the full UI."""
        self.api.update_settings({'theme': 'light', 'ui_theme': 'light'})

        class _Stub:
            pass

        stub = _Stub()
        stub.api = self.api
        stub._cfg = lambda: self.api.get_settings()

        from desktop.main import MainWindow
        self.assertTrue(MainWindow._read_theme_pref(stub))

        MainWindow._save_theme_pref(stub, False)
        cfg = self.api.get_settings()
        self.assertEqual(cfg.get('theme'), 'dark')
        self.assertEqual(cfg.get('ui_theme'), 'dark')
        self.assertFalse(MainWindow._read_theme_pref(stub))


if __name__ == '__main__':
    unittest.main()
