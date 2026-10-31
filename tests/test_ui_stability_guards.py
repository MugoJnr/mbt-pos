import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication, QDialog, QFrame, QMainWindow, QMessageBox, QPushButton,
    QWidget,
)


APP = QApplication.instance() or QApplication([])


class UIStabilityGuardTests(unittest.TestCase):
    def tearDown(self):
        APP.processEvents()

    def test_normal_widget_is_not_misclassified_as_qt_tooltip(self):
        from desktop.utils.quiet_ui import _is_intentional_toplevel

        frame = QFrame()
        self.assertFalse(_is_intentional_toplevel(frame))
        self.assertTrue(_is_intentional_toplevel(QDialog()))

    def test_fifth_press_in_a_hardware_speed_burst_is_blocked(self):
        from desktop.utils.input_guard import install_input_burst_guard

        button = QPushButton('Adjust Stock')
        button.show()
        clicks = []
        button.clicked.connect(lambda: clicks.append(True))
        install_input_burst_guard()
        for _ in range(5):
            QTest.mouseClick(button, Qt.LeftButton)
        self.assertLessEqual(len(clicks), 4)
        button.close()

    def test_rapid_taps_across_different_product_controls_are_preserved(self):
        from desktop.utils.input_guard import install_input_burst_guard

        install_input_burst_guard()
        clicks = []
        buttons = [QPushButton(f'Product {i}') for i in range(6)]
        for button in buttons:
            button.clicked.connect(lambda: clicks.append(True))
            button.show()
            QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(len(clicks), len(buttons))
        for button in buttons:
            button.close()

    def test_repeated_question_is_not_silently_answered_no(self):
        from desktop.utils import quiet_ui

        quiet_ui._ACTIVE_MESSAGEBOX_KEYS.clear()
        quiet_ui._LAST_MESSAGEBOX_DISMISSAL.clear()
        parent = QMainWindow()
        parent.show()
        with patch.object(
            QMessageBox, 'exec_', return_value=QMessageBox.No
        ) as execute:
            for _ in range(2):
                quiet_ui._exec_styled(
                    parent, QMessageBox.Question, 'Confirm', 'Continue?',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
        self.assertEqual(execute.call_count, 2)
        parent.close()

    def test_style_polish_does_not_freeze_or_hide_sale_widgets(self):
        import logging
        from desktop.utils import quiet_ui

        quiet_ui.install_orphan_flash_guard()
        quiet_ui.FLASH_EVENTS.clear()
        quiet_ui._FLASH_LOG_AT.clear()
        warnings = []
        handler = logging.Handler()
        handler.emit = lambda record: warnings.append(record.getMessage())
        logger = logging.getLogger('mbt.quiet_ui')
        logger.addHandler(handler)
        try:
            built = [QWidget() for _ in range(30)]
            APP.processEvents()
            self.assertFalse(any(item.startswith('FLASH Polish') for item in warnings))
            self.assertFalse(any(item.startswith('FLASH WinId') for item in warnings))
            for item in built:
                self.assertFalse(item.testAttribute(Qt.WA_DontShowOnScreen))

            flash = QFrame()
            flash.show()
            APP.processEvents()
            self.assertFalse(flash.isVisible())
            self.assertTrue(flash.testAttribute(Qt.WA_DontShowOnScreen))

            host = QWidget()
            flash.setParent(host)
            APP.processEvents()
            self.assertFalse(flash.testAttribute(Qt.WA_DontShowOnScreen))

            class _Widget:
                def objectName(self):
                    return 'amount'
                def windowTitle(self):
                    return ''
                def x(self):
                    return 0
                def y(self):
                    return 0
                def width(self):
                    return 10
                def height(self):
                    return 10
                def parent(self):
                    return None

            before = len(warnings)
            for _ in range(60):
                quiet_ui._record_flash('Show', _Widget(), True)
            self.assertLessEqual(len(quiet_ui.FLASH_EVENTS), 40)
            self.assertLessEqual(len(warnings) - before, 2)
        finally:
            logger.removeHandler(handler)

    def test_production_does_not_install_sixty_hz_toplevel_logger(self):
        from desktop.utils import quiet_ui

        old = os.environ.pop('MBT_QA_TOPLEVEL_DEBUG', None)
        try:
            quiet_ui._DEBUG_TL_TIMER = None
            quiet_ui.install_toplevel_debug_logger()
            self.assertIsNone(quiet_ui._DEBUG_TL_TIMER)
        finally:
            if old is not None:
                os.environ['MBT_QA_TOPLEVEL_DEBUG'] = old

    def test_duplicate_toasts_are_reused_and_visible_toasts_are_capped(self):
        from desktop.utils.ui_polish import ToastNotification

        host = QMainWindow()
        host.resize(700, 500)
        host.show()
        ToastNotification._active = []
        first = ToastNotification.show_toast(host, 'Same warning', tone='warn')
        duplicate = ToastNotification.show_toast(host, ' Same   warning ', tone='warn')
        self.assertIs(first, duplicate)
        for i in range(5):
            ToastNotification.show_toast(host, f'Unique {i}', tone='info')
        self.assertLessEqual(
            len([t for t in ToastNotification._active if t.isVisible()]), 3)
        host.close()

    def test_remote_license_callback_only_fires_for_a_real_transition(self):
        from licensing.license_service import LicenseService

        class Engine:
            state = 'active'

            def revalidate(self):
                return None

            def get_status_dict(self):
                return {'state': self.state}

        calls = []
        svc = LicenseService.__new__(LicenseService)
        svc.engine = Engine()
        svc._last_state = 'active'
        svc._tamper_alerted = False
        svc.on_state_change = lambda state, data: calls.append((state, data))
        svc._on_remote_state_change()
        self.assertEqual(calls, [])

        svc.engine.state = 'expired'
        svc._on_remote_state_change()
        self.assertEqual([row[0] for row in calls], ['expired'])

    def test_deferred_expiry_alert_replays_when_sale_becomes_idle(self):
        from desktop.main import MainWindow

        class Service:
            state = 'expired'

        class Window:
            _pending_license_alert = ('expired', 'Renew now')
            _svc_lic = Service()
            _license_alert_timer_scheduled = True

            @staticmethod
            def is_safe_to_auto_update():
                return True

        window = Window()
        with patch.object(QMessageBox, 'critical') as critical:
            MainWindow._replay_deferred_license_alert(window)
        critical.assert_called_once_with(window, 'MBT POS - License', 'Renew now')
        self.assertIsNone(window._pending_license_alert)

    def test_opening_receipts_reloads_sales_made_after_login(self):
        from desktop.tabs.receipts_tab import ReceiptsTab

        calls = []
        tab = ReceiptsTab.__new__(ReceiptsTab)
        tab.reload = lambda: calls.append("reload")
        ReceiptsTab.on_show(tab)
        self.assertEqual(calls, ["reload"])

    def test_receipt_open_column_stays_inside_the_table(self):
        from PyQt5.QtWidgets import QHeaderView, QTableWidget
        from desktop.tabs.receipts_tab import _fit_receipt_columns

        from desktop.tabs.receipts_tab import _receipt_column_widths
        for viewport in (900, 1100, 1400):
            widths = _receipt_column_widths(viewport)
            self.assertEqual(len(widths), 8)
            self.assertEqual(sum(widths), viewport)
            self.assertGreaterEqual(widths[6], 96)
            self.assertGreaterEqual(widths[7], 84)
        table = QTableWidget(1, 8)
        table.resize(1200, 480)
        _fit_receipt_columns(table)
        header = table.horizontalHeader()
        self.assertFalse(header.stretchLastSection())
        self.assertEqual(header.sectionResizeMode(7), QHeaderView.Fixed)
        self.assertGreaterEqual(table.columnWidth(6), 96)
        self.assertGreaterEqual(table.columnWidth(7), 84)
        used = sum(table.columnWidth(col) for col in range(8))
        self.assertLessEqual(used, max(table.viewport().width(), 1100))
        src_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "desktop", "tabs", "receipts_tab.py")
        with open(src_path, encoding="utf-8") as handle:
            src = handle.read()
        self.assertNotIn("setCellWidget", src)

    def test_window_type_mask_uses_exact_type_not_overlapping_bits(self):
        flags = int(QFrame().windowFlags())
        actual = flags & int(Qt.WindowType_Mask)
        self.assertNotEqual(actual, int(Qt.ToolTip))
        self.assertNotEqual(actual, int(Qt.Popup))


if __name__ == '__main__':
    unittest.main()
