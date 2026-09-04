"""Regression: "Open Exports Folder" must not raise when the shell refuses.

`_open_folder` called `os.startfile` unguarded, so a missing folder, a denied
path, or no shell association turned a button click into an unhandled exception.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class OpenExportsFolderGuardTests(unittest.TestCase):
    def setUp(self):
        from PyQt5.QtWidgets import QApplication, QMessageBox
        self.app = QApplication.instance() or QApplication([])
        import desktop.tabs.reports_tab as reports_tab
        self.reports_tab = reports_tab

        self.shown = []
        self._real_warning = QMessageBox.warning
        QMessageBox.warning = staticmethod(
            lambda parent, title, text='', *a, **k: self.shown.append((title, text)))

        class Stub(reports_tab.ReportsTab):
            def __init__(self):
                pass  # only _open_folder is under test

        self.tab = Stub()
        self._real_startfile = getattr(os, 'startfile', None)

    def tearDown(self):
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning = self._real_warning
        if self._real_startfile is not None:
            os.startfile = self._real_startfile

    def _run_with_startfile_raising(self, exc):
        def boom(_path):
            raise exc
        os.startfile = boom
        self.tab._open_folder()

    def test_missing_folder_warns_instead_of_raising(self):
        self._run_with_startfile_raising(
            FileNotFoundError(2, 'The system cannot find the file specified'))
        self.assertEqual(len(self.shown), 1)
        self.assertIn('Could not open the exports folder', self.shown[0][1])

    def test_permission_denied_warns_instead_of_raising(self):
        self._run_with_startfile_raising(PermissionError(13, 'Access is denied'))
        self.assertEqual(len(self.shown), 1)

    def test_no_shell_association_warns_instead_of_raising(self):
        self._run_with_startfile_raising(
            OSError(1155, 'No application is associated with the specified file'))
        self.assertEqual(len(self.shown), 1)

    def test_warning_names_the_folder_for_manual_browsing(self):
        self._run_with_startfile_raising(PermissionError(13, 'Access is denied'))
        self.assertIn('browse to it manually', self.shown[0][1])

    def test_success_opens_folder_without_warning(self):
        called = []
        os.startfile = lambda path: called.append(path)
        self.tab._open_folder()
        self.assertEqual(len(called), 1)
        self.assertTrue(os.path.isdir(called[0]))
        self.assertEqual(self.shown, [])


if __name__ == '__main__':
    unittest.main()
