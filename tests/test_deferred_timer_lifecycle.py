"""Regression: deferred POS splitter restores must die with their tab.

`QTimer.singleShot` closures kept firing after the Sales tab was destroyed and
then touched deleted C++ objects, raising
`RuntimeError: wrapped C/C++ object of type SalesTab has been deleted`.
"""
import os
import sys
import traceback
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class DeferredTimerLifecycleTests(unittest.TestCase):
    def setUp(self):
        from PyQt5.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def _pump(self, msec):
        from PyQt5.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        QTimer.singleShot(msec, loop.quit)
        loop.exec_()

    def test_splitters_module_has_no_bare_single_shot(self):
        """Bare singleShot outlives the tab; splitters must use `_defer`."""
        import ast
        path = os.path.join(ROOT, 'desktop', 'pos', 'layouts', 'splitters.py')
        with open(path, 'r', encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'singleShot'
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == 'QTimer'
        ]
        self.assertEqual(
            offenders, [],
            f'bare QTimer.singleShot at lines {offenders}; use _defer(tab, ms, fn)')

    def test_deferred_callback_runs_while_owner_alive(self):
        from PyQt5.QtWidgets import QWidget
        from desktop.pos.layouts.splitters import _defer
        owner = QWidget()
        fired = []
        _defer(owner, 10, lambda: fired.append(True))
        self._pump(250)
        self.assertEqual(fired, [True])
        owner.deleteLater()

    def test_deferred_callback_cancelled_when_owner_destroyed(self):
        from PyQt5.QtWidgets import QLabel, QWidget
        from desktop.pos.layouts.splitters import _defer

        errors = []

        def hook(exc_type, exc, tb):
            errors.append(''.join(traceback.format_exception(exc_type, exc, tb)))

        owner = QWidget()
        child = QLabel('x', owner)
        fired = []

        def touch_deleted():
            fired.append(True)
            child.setText('boom')

        _defer(owner, 120, touch_deleted)
        _defer(owner, 280, touch_deleted)
        owner.deleteLater()
        owner.setParent(None)
        del owner

        previous_hook = sys.excepthook
        sys.excepthook = hook
        try:
            self._pump(600)
        finally:
            sys.excepthook = previous_hook

        self.assertEqual(fired, [])
        self.assertEqual(errors, [])

    def test_defer_ignores_already_deleted_owner(self):
        from PyQt5.QtWidgets import QWidget
        from desktop.pos.layouts.splitters import _defer
        import sip
        owner = QWidget()
        sip.delete(owner)
        fired = []
        _defer(owner, 10, lambda: fired.append(True))
        self._pump(200)
        self.assertEqual(fired, [])


if __name__ == '__main__':
    unittest.main()
