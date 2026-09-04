import os
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication


APP = QApplication.instance() or QApplication([])


class WindowsRuntimeReadinessTests(unittest.TestCase):
    def test_worker_callback_is_delivered_on_qt_thread(self):
        from desktop.utils import qt_dispatch

        qt_dispatch._dispatcher = None
        dispatcher = qt_dispatch.install_ui_dispatcher(APP)
        called = []

        def callback():
            called.append(dispatcher.thread() is APP.thread())

        worker = threading.Thread(
            target=lambda: qt_dispatch.run_on_ui_thread(callback), daemon=True
        )
        worker.start()
        worker.join(timeout=2)
        deadline = time.monotonic() + 2
        while not called and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.01)
        self.assertEqual(called, [True])

    def test_production_manifest_declares_per_monitor_v2(self):
        root = os.path.dirname(os.path.dirname(__file__))
        manifest = open(
            os.path.join(root, "mbt_pos.manifest"), encoding="utf-8"
        ).read()
        self.assertIn("PerMonitorV2,PerMonitor", manifest)
        self.assertIn('requestedExecutionLevel level="asInvoker"', manifest)

    def test_frozen_gui_build_has_no_console(self):
        root = os.path.dirname(os.path.dirname(__file__))
        spec = open(os.path.join(root, "mbt_pos.spec"), encoding="utf-8").read()
        self.assertIn("console=False", spec)
        self.assertIn("mbt_pos.manifest", spec)

    def test_windows_power_and_session_messages_are_classified(self):
        from desktop.utils import windows_session as ws

        self.assertEqual(
            ws.classify_message(ws.WM_POWERBROADCAST, ws.PBT_APMSUSPEND),
            "suspend",
        )
        for event in (
            ws.PBT_APMRESUMECRITICAL,
            ws.PBT_APMRESUMESUSPEND,
            ws.PBT_APMRESUMEAUTOMATIC,
        ):
            self.assertEqual(
                ws.classify_message(ws.WM_POWERBROADCAST, event), "resume"
            )
        self.assertEqual(
            ws.classify_message(ws.WM_WTSSESSION_CHANGE, ws.WTS_SESSION_LOCK),
            "session-pause",
        )
        self.assertEqual(
            ws.classify_message(ws.WM_WTSSESSION_CHANGE, ws.WTS_SESSION_UNLOCK),
            "session-resume",
        )
        self.assertEqual(
            ws.classify_message(ws.WM_WTSSESSION_CHANGE, ws.WTS_CONSOLE_DISCONNECT),
            "session-pause",
        )
        self.assertEqual(
            ws.classify_message(ws.WM_WTSSESSION_CHANGE, ws.WTS_CONSOLE_CONNECT),
            "session-resume",
        )
        self.assertIsNone(ws.classify_message(0x1234, 0x5678))

    def test_license_key_derivation_is_cached_by_secret(self):
        from licensing import license_engine as le

        le._derive_key_cached.cache_clear()
        secret = b"runtime-profile-regression-secret"
        with mock.patch.object(
            le.hashlib, "pbkdf2_hmac", wraps=le.hashlib.pbkdf2_hmac
        ) as derive:
            first = le._derive_key("device-a", secret)
            second = le._derive_key("device-a", secret)
            other = le._derive_key("device-a", b"rotated-secret")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(derive.call_count, 2)

    def test_command_poller_resolves_license_alias_once(self):
        from backend.cloud.command_center import CommandPoller

        center = mock.Mock()
        poller = CommandPoller(center, lambda: "cloud-device")
        fake_engine = mock.Mock(device_id="license-device")
        with mock.patch(
            "licensing.license_engine.LicenseEngine", return_value=fake_engine
        ) as engine:
            self.assertEqual(poller._get_license_device_id(), "license-device")
            self.assertEqual(poller._get_license_device_id(), "license-device")
        engine.assert_called_once_with()

    def test_platform_service_reuses_http_session(self):
        from backend.cloud import platform_service as service

        cfg = {
            "supabase_url": "https://example.invalid",
            "anon_key": "anon",
            "service_key": "",
            "bucket": "backups",
        }
        service._SVC_CLIENT = None
        service._SVC_CONFIG_KEY = ()
        with mock.patch.object(service, "load_cloud_config", return_value=cfg), mock.patch.object(
            service, "SupabaseClient"
        ) as client:
            first = service._svc()
            second = service._svc()
        self.assertIs(first, second)
        client.assert_called_once_with(config=cfg)

    def test_command_poll_skips_bare_anon_session(self):
        from backend.cloud.command_center import CommandCenter

        center = CommandCenter(":memory:")
        with mock.patch(
            "backend.cloud.net_gate.network_up", return_value=True
        ), mock.patch(
            "backend.cloud_backup.paths.load_identity", return_value={}
        ), mock.patch(
            "backend.cloud.platform_service.has_service_role", return_value=False
        ), mock.patch(
            "backend.cloud.platform_service.service_select"
        ) as select:
            self.assertEqual(center.poll_pending("device"), [])
        select.assert_not_called()

    def test_command_poll_skips_when_offline(self):
        from backend.cloud.command_center import CommandCenter

        center = CommandCenter(":memory:")
        with mock.patch(
            "backend.cloud.net_gate.network_up", return_value=False
        ), mock.patch(
            "backend.cloud.platform_service.service_select"
        ) as select:
            self.assertEqual(center.poll_pending("device"), [])
        select.assert_not_called()

    def test_high_dpi_rounding_is_passthrough(self):
        root = os.path.dirname(os.path.dirname(__file__))
        main = open(os.path.join(root, "desktop", "main.py"), encoding="utf-8").read()
        self.assertIn("HighDpiScaleFactorRoundingPolicy.PassThrough", main)
        self.assertIn("def _read_boot_theme_is_light", main)
        self.assertIn("ThemeManager.apply(False, force=True)", main)

    def test_splash_stops_fade_in_before_fade_out(self):
        from desktop.utils.splash import SplashScreen

        splash = SplashScreen()
        splash._fade.stop = mock.Mock(wraps=splash._fade.stop)
        splash.finish_and_close(0)
        splash._fade.stop.assert_called()
        splash.close()

    def test_inventory_refresh_does_not_use_cell_widgets(self):
        root = os.path.dirname(os.path.dirname(__file__))
        src = open(
            os.path.join(root, "desktop", "tabs", "inventory_tab.py"),
            encoding="utf-8",
        ).read()
        self.assertNotIn("setCellWidget", src)
        self.assertNotIn("def _stock_pill", src)
        self.assertIn("def _stock_item", src)
        self.assertIn("def _on_cell_clicked", src)


class PlainLogRotationTests(unittest.TestCase):
    def test_rotate_plain_log_renames_oversized_file(self):
        import tempfile
        from desktop.utils.log_config import rotate_plain_log

        td = tempfile.mkdtemp()
        path = os.path.join(td, "cloudflared.log")
        with open(path, "wb") as fh:
            fh.write(b"x" * 64)
        rotate_plain_log(path, max_bytes=32, backup_count=2)
        self.assertFalse(os.path.isfile(path))
        self.assertTrue(os.path.isfile(path + ".1"))
        with open(path, "wb") as fh:
            fh.write(b"y" * 64)
        rotate_plain_log(path, max_bytes=32, backup_count=2)
        self.assertTrue(os.path.isfile(path + ".1"))
        self.assertTrue(os.path.isfile(path + ".2"))


if __name__ == "__main__":
    unittest.main()
