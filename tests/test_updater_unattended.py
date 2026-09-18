"""
Focused tests for unattended desktop updater:
  checksum valid/invalid/missing, idle gating, retry helpers,
  install-state / loop guard, path allowlist, fallback gates.

Run:
  python -m pytest tests/test_updater_unattended.py -v
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ChecksumTests(unittest.TestCase):
    def test_normalize_and_parse(self):
        from backend.cloud.update_center import (
            normalize_checksum, parse_checksum_from_text,
        )
        hex64 = 'a' * 64
        self.assertEqual(normalize_checksum(hex64), hex64)
        self.assertEqual(normalize_checksum('SHA256:' + hex64.upper()), hex64)
        self.assertEqual(normalize_checksum('not-a-hash'), '')
        self.assertEqual(normalize_checksum(None), '')
        self.assertEqual(
            parse_checksum_from_text(f'[checksum_sha256: {hex64}]'), hex64)
        self.assertEqual(
            parse_checksum_from_text(f'sha256: {hex64}\n'), hex64)
        self.assertEqual(
            parse_checksum_from_text(f'{hex64}  MBT_POS_Setup.exe\n'), hex64)

    def test_verify_valid_invalid_missing(self):
        from backend.updater import verify_installer_checksum
        from backend.cloud.update_center import UpdateCenter, sha256_file

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'MBT_POS_Setup_v9.9.9.exe')
            payload = b'MBT installer fixture ' + os.urandom(64)
            with open(path, 'wb') as f:
                f.write(payload)
            good = sha256_file(path)
            ok, detail = verify_installer_checksum(path, good)
            self.assertTrue(ok)
            self.assertEqual(detail, good)

            ok, detail = verify_installer_checksum(path, 'b' * 64)
            self.assertFalse(ok)
            self.assertIn('checksum_mismatch', detail)

            ok, detail = verify_installer_checksum(path, '')
            self.assertFalse(ok)
            self.assertEqual(detail, 'missing_checksum')

            ok, detail = verify_installer_checksum(path, None)
            self.assertFalse(ok)
            self.assertEqual(detail, 'missing_checksum')

            center = UpdateCenter()
            self.assertTrue(center.verify_checksum(path, good))
            self.assertFalse(center.verify_checksum(path, 'c' * 64))
            self.assertFalse(center.verify_checksum(path, ''))


class IdleGatingTests(unittest.TestCase):
    def test_idle_and_busy_reasons(self):
        from backend.updater import evaluate_idle_window

        ok, reason = evaluate_idle_window()
        self.assertTrue(ok)
        self.assertEqual(reason, '')

        ok, reason = evaluate_idle_window(cart_items=2)
        self.assertFalse(ok)
        self.assertEqual(reason, 'active_cart')

        ok, reason = evaluate_idle_window(has_modal=True)
        self.assertFalse(ok)
        self.assertEqual(reason, 'modal_dialog')

        ok, reason = evaluate_idle_window(has_popup=True)
        self.assertFalse(ok)
        self.assertEqual(reason, 'popup')

        ok, reason = evaluate_idle_window(critical_operation=True)
        self.assertFalse(ok)
        self.assertEqual(reason, 'critical_operation')

        ok, reason = evaluate_idle_window(backup_busy=True)
        self.assertFalse(ok)
        self.assertEqual(reason, 'backup_busy')


class InstallStateLoopGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state = os.path.join(self._tmpdir.name, 'update_install_state.json')
        self._patch = patch(
            'backend.updater.install_state_path', return_value=self._state)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmpdir.cleanup()

    def test_fail_cooldown_and_in_progress(self):
        from backend.updater import (
            can_attempt_auto_install, mark_install_started,
            mark_install_finished, MAX_AUTO_FAILS, INSTALL_FAIL_COOLDOWN_SEC,
        )
        ok, reason = can_attempt_auto_install('3.1.0', now=1_000_000)
        self.assertTrue(ok)

        with patch('backend.updater.time.time', return_value=1_000_050):
            mark_install_started('3.1.0')
        ok, reason = can_attempt_auto_install('3.1.0', now=1_000_100)
        self.assertFalse(ok)
        self.assertEqual(reason, 'install_in_progress')

        with patch('backend.updater.time.time', return_value=1_000_150):
            mark_install_finished('3.1.0', False, 'boom')
            for _ in range(MAX_AUTO_FAILS - 1):
                mark_install_finished('3.1.0', False, 'boom')

        ok, reason = can_attempt_auto_install('3.1.0', now=1_000_200)
        self.assertFalse(ok)
        self.assertEqual(reason, 'fail_cooldown')

        # After cooldown window, allow again
        ok, reason = can_attempt_auto_install(
            '3.1.0', now=1_000_200 + INSTALL_FAIL_COOLDOWN_SEC + 1)
        self.assertTrue(ok)

        with patch('backend.updater.time.time', return_value=2_000_000):
            mark_install_finished('3.1.0', True)
        ok, reason = can_attempt_auto_install('3.1.0', now=2_000_000)
        self.assertFalse(ok)
        self.assertEqual(reason, 'already_installed')

    def test_blocked_version(self):
        from backend.updater import can_attempt_auto_install
        ok, reason = can_attempt_auto_install('2.3.5')
        self.assertFalse(ok)
        self.assertEqual(reason, 'blocked_version')

    def test_startup_recovers_stale_in_progress_when_version_already_running(self):
        from backend.updater import (
            UpdateChecker, load_install_state, mark_install_started,
        )
        with patch('backend.updater.time.time', return_value=3_000_000):
            mark_install_started('3.0.77')
        before = load_install_state()
        self.assertTrue(before.get('in_progress'))

        checker = UpdateChecker('3.0.77')
        with patch('backend.updater.read_last_install_result', return_value='OK'):
            checker._check_previous_install()

        after = load_install_state()
        self.assertFalse(after.get('in_progress'))
        self.assertEqual(after.get('last_success_version'), '3.0.77')
        self.assertEqual(after.get('last_result'), 'ok')


class PathAndJobTests(unittest.TestCase):
    def test_safe_path_and_job_requires_checksum(self):
        from backend.updater import (
            is_safe_installer_path, write_update_job, update_job_path,
            allowed_installer_roots,
        )
        self.assertFalse(is_safe_installer_path(r'C:\Windows\cmd.exe'))
        self.assertFalse(is_safe_installer_path(r'C:\Temp\evil&calc.exe'))

        with tempfile.TemporaryDirectory() as td:
            # Patch allowlist to temp dir for unit test
            dest_dir = os.path.join(td, 'updates')
            os.makedirs(dest_dir)
            installer = os.path.join(dest_dir, 'MBT_POS_Setup_v3.1.0.exe')
            with open(installer, 'wb') as f:
                f.write(b'x' * 100)

            with patch('backend.updater.allowed_installer_roots',
                       return_value=[os.path.abspath(td)]), \
                 patch('backend.updater._brand_data_root', return_value=td):
                self.assertTrue(is_safe_installer_path(installer))
                with self.assertRaises(ValueError):
                    write_update_job(installer, '', '3.1.0')
                rid = write_update_job(installer, 'a' * 64, '3.1.0')
                self.assertTrue(rid)
                with open(update_job_path(), encoding='utf-8') as f:
                    job = json.load(f)
                self.assertEqual(job['sha256'], 'a' * 64)
                self.assertNotIn('command', job)
                self.assertNotIn('args', job)

    def test_frozen_helper_is_found_in_deploy_directory(self):
        from backend.updater import find_update_helper_script

        with tempfile.TemporaryDirectory() as td:
            exe = os.path.join(td, 'MBT_POS.exe')
            helper = os.path.join(td, 'deploy', 'MBT_UpdateHelper.ps1')
            os.makedirs(os.path.dirname(helper))
            with open(helper, 'w', encoding='utf-8') as f:
                f.write('# helper')
            with patch('backend.updater.sys.frozen', True, create=True), \
                 patch('backend.updater.sys.executable', exe):
                self.assertEqual(
                    os.path.normcase(find_update_helper_script()),
                    os.path.normcase(helper),
                )


class UnattendedFallbackTests(unittest.TestCase):
    def test_missing_checksum_blocks_unattended(self):
        from backend.updater import UpdateChecker

        uc = UpdateChecker('3.0.0')
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'MBT_POS_Setup_v3.1.0.exe')
            with open(path, 'wb') as f:
                f.write(b'z' * 2_000_000)
            uc._installer_path = path
            uc._pending_version = '3.1.0'
            uc._pending_checksum = ''
            with patch('backend.updater.is_update_helper_registered',
                       return_value=True), \
                 patch('backend.updater.can_attempt_auto_install',
                       return_value=(True, '')), \
                 patch('backend.updater.is_safe_installer_path',
                       return_value=True), \
                 patch('backend.updater.preflight_install',
                       return_value={'ok': True, 'path': path}):
                ok, err = uc.install_and_restart(path, unattended=True)
                self.assertFalse(ok)
                self.assertIn('checksum', err.lower())

    def test_missing_checksum_blocks_manual_install(self):
        from backend.updater import UpdateChecker

        uc = UpdateChecker('3.0.0')
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'MBT_POS_Setup_v3.1.0.exe')
            with open(path, 'wb') as f:
                f.write(b'z' * 2_000_000)
            uc._pending_version = '3.1.0'
            uc._pending_checksum = ''
            with patch('backend.updater.is_safe_installer_path',
                       return_value=True), \
                 patch('backend.updater.preflight_install',
                       return_value={'ok': True, 'path': path}):
                ok, err = uc.install_and_restart(path, unattended=False)
                self.assertFalse(ok)
                self.assertIn('checksum', err.lower())

    def test_unsigned_installer_requires_uac_for_install(self):
        from backend.updater import UpdateChecker

        uc = UpdateChecker('3.0.0')
        digest = hashlib.sha256(b'z' * 2_000_000).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'MBT_POS_Setup_v3.1.0.exe')
            with open(path, 'wb') as f:
                f.write(b'z' * 2_000_000)
            uc._installer_path = path
            uc._pending_version = '3.1.0'
            uc._pending_checksum = digest
            with patch('backend.updater.is_update_helper_registered',
                       return_value=False), \
                 patch('backend.updater.can_attempt_auto_install',
                       return_value=(True, '')), \
                 patch('backend.updater.is_safe_installer_path',
                       return_value=True), \
                 patch('backend.updater.verify_installer_checksum',
                       return_value=(True, digest)), \
                 patch('backend.updater.preflight_install',
                       return_value={'ok': True, 'path': path}):
                can, reason = uc.can_unattended_install()
                self.assertFalse(can)
                self.assertEqual(reason, 'requires_uac')
                ok, err = uc.install_and_restart(path, unattended=True)
                self.assertFalse(ok)
                self.assertIn('administrator authorization', err.lower())

    def test_download_retry_schedules_on_incomplete(self):
        from backend.updater import UpdateChecker, DOWNLOAD_RETRY_INTERVAL

        uc = UpdateChecker('3.0.0')
        scheduled = []

        def fake_schedule(url, version):
            scheduled.append((url, version))

        uc._schedule_download_retry = fake_schedule
        uc._pending_checksum = ''
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, 'MBT_POS_Setup_v3.1.0.exe')
            # Force incomplete path by patching download helpers
            with patch.object(uc, '_http_download_file', return_value=100), \
                 patch.object(uc, '_download_complete_enough', return_value=False), \
                 patch('backend.updater.tempfile.gettempdir', return_value=td), \
                 patch('backend.updater.time.sleep'), \
                 patch.object(uc, '_notify_download_issue'), \
                 patch('backend.updater._ensure_ssl_certs'), \
                 patch('backend.updater.MAX_DOWNLOAD_ATTEMPTS', 2):
                uc._download('https://example.test/MBT_POS_Setup.exe', '3.1.0')
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0][1], '3.1.0')
        self.assertGreater(DOWNLOAD_RETRY_INTERVAL, 0)


class PublishChecksumGateTests(unittest.TestCase):
    def test_publish_refuses_empty_checksum(self):
        from backend.cloud.update_center import UpdateCenter
        center = UpdateCenter()
        with patch('backend.cloud_backup.supabase_client.SupabaseClient') as _:
            # Even if client exists, missing checksum must refuse before insert
            result = center.publish_update(
                '3.1.0', 'https://example.test/setup.exe', '')
            self.assertIsNone(result)

    def test_publish_falls_back_when_version_unique_constraint_is_missing(self):
        from backend.cloud.update_center import UpdateCenter

        class Response:
            def __init__(self, status, payload, text=''):
                self.status_code = status
                self._payload = payload
                self.text = text
                self.content = b'x' if payload is not None else b''

            def json(self):
                return self._payload

        class Session:
            def __init__(self):
                self.posts = 0

            def post(self, *_args, **_kwargs):
                self.posts += 1
                if self.posts == 1:
                    return Response(
                        400, {'code': '42P10'},
                        '{"code":"42P10","message":"no unique constraint"}',
                    )
                return Response(201, [{'id': 'update-1', 'version': '3.1.2'}])

            def get(self, *_args, **_kwargs):
                return Response(200, [])

        class Client:
            def __init__(self):
                self._session = Session()
                self.service = 'service-role-key'

            def _url(self, path):
                return 'https://example.test' + path

            def _headers(self, **_kwargs):
                return {}

        center = UpdateCenter()
        with patch(
            'backend.cloud_backup.supabase_client.SupabaseClient',
            Client,
        ):
            result = center.publish_update(
                '3.1.2', 'https://example.test/setup.exe', 'a' * 64,
            )
        self.assertEqual(result['version'], '3.1.2')

    def test_publish_refuses_without_a_service_role_key(self):
        """Anon-key inserts are always rejected by app_updates RLS."""
        from backend.cloud.update_center import UpdateCenter

        class Session:
            def post(self, *_args, **_kwargs):
                raise AssertionError('publish must not call PostgREST without a service key')

        class Client:
            def __init__(self):
                self._session = Session()
                self.service = ''

        with patch(
            'backend.cloud_backup.supabase_client.SupabaseClient',
            Client,
        ):
            self.assertIsNone(
                UpdateCenter().publish_update(
                    '3.1.2', 'https://example.test/setup.exe', 'a' * 64,
                )
            )


class SingleInstanceTests(unittest.TestCase):
    def test_acquire_single_instance_mutex(self):
        """I08: second acquire of the same named mutex returns False on Windows."""
        from backend.updater import acquire_single_instance

        if sys.platform != 'win32':
            self.assertTrue(acquire_single_instance())
            return

        name = f'Global\\MBT_POS_UT_{os.getpid()}_{id(self)}'
        first = acquire_single_instance(name)
        second = acquire_single_instance(name)
        self.assertTrue(first)
        self.assertFalse(second)

    def test_visible_titled_window_is_raised_over_helper_windows(self):
        from backend.updater import choose_existing_window

        self.assertEqual(
            choose_existing_window([
                {'hwnd': 11, 'title': 'Default IME', 'cls': 'IME', 'visible': True},
                {'hwnd': 12, 'title': 'MSCTFIME UI', 'cls': 'MSCTFIME UI',
                 'visible': True},
                {'hwnd': 13, 'title': 'MBT POS', 'cls': 'Qt5152QWindowIcon',
                 'visible': False},
                {'hwnd': 14, 'title': 'MBT POS', 'cls': 'Qt5152QWindowIcon',
                 'visible': True},
            ]),
            14,
        )

    def test_windowless_instance_reports_no_window_to_raise(self):
        """The offscreen/stuck copy must not be reported as focusable."""
        from backend.updater import choose_existing_window

        for windows in (
            [],
            None,
            [{'hwnd': 21, 'title': 'Default IME', 'cls': 'IME', 'visible': True}],
            [{'hwnd': 22, 'title': '', 'cls': 'Qt5152QWindowIcon', 'visible': True}],
            [{'hwnd': 23, 'title': 'MBT POS', 'cls': 'Qt5152QWindowIcon',
              'visible': False}],
        ):
            self.assertIsNone(choose_existing_window(windows), windows)

    def test_second_launch_guides_the_user_when_no_window_can_be_raised(self):
        """Clicking the icon must never fail in silence (v3.1.5 regression)."""
        main_src = os.path.join(ROOT, 'desktop', 'main.py')
        with open(main_src, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('resolve_second_launch(', src)
        self.assertIn('warn_stuck_instance()', src)
        self.assertIn("record_launch_stage('starting')", src)
        self.assertIn("record_launch_stage('ready')", src)
        # sys.exit must still end this process, never be swallowed as an error.
        self.assertIn('except SystemExit:\n        raise', src)

        from backend.updater import STUCK_INSTANCE_MESSAGE

        self.assertIn('already running', STUCK_INSTANCE_MESSAGE)
        self.assertIn('Task Manager', STUCK_INSTANCE_MESSAGE)
        for jargon in ('mutex', 'hwnd', 'traceback', 'qt_qpa'):
            self.assertNotIn(jargon, STUCK_INSTANCE_MESSAGE.lower())

    def test_running_window_is_raised_for_the_second_click(self):
        from backend.updater import resolve_second_launch

        self.assertEqual('focused', resolve_second_launch(
            focus_result='focused',
            launch_state={'stage': 'ready', 'started_at': 0},
            now_ts=9_999_999,
        ))

    def test_impatient_click_during_startup_shows_no_scary_message(self):
        """A shop double-clicking while the POS boots must not be alarmed."""
        from backend.updater import resolve_second_launch

        now = 1_000_000.0
        for elapsed in (0.0, 2.5, 30.0, 119.0):
            self.assertEqual('quiet', resolve_second_launch(
                focus_result='no-window',
                launch_state={'stage': 'starting', 'started_at': now - elapsed},
                now_ts=now,
            ), f'{elapsed}s into startup must stay silent')

    def test_windowless_ready_instance_earns_the_warning(self):
        from backend.updater import resolve_second_launch

        now = 1_000_000.0
        self.assertEqual('warn', resolve_second_launch(
            focus_result='no-window',
            launch_state={'stage': 'ready', 'started_at': now - 600},
            now_ts=now,
        ))
        # A start that never reached a window is stuck, not merely slow.
        self.assertEqual('warn', resolve_second_launch(
            focus_result='no-window',
            launch_state={'stage': 'starting', 'started_at': now - 4000},
            now_ts=now,
        ))

    def test_unknown_or_other_user_instance_exits_quietly(self):
        """Never guess about an instance we cannot see; behave like old builds."""
        from backend.updater import resolve_second_launch

        for state in (None, {}, {'stage': ''}, 'garbage',
                      {'stage': 'starting', 'started_at': 'not-a-number'}):
            self.assertEqual('quiet', resolve_second_launch(
                focus_result='no-window',
                launch_state=state,
                now_ts=1_000_000.0,
            ), f'state {state!r} must not trigger a message')

    def test_launch_stage_round_trips_and_keeps_start_time(self):
        import time
        from backend import updater

        with tempfile.TemporaryDirectory() as tmp:
            marker = os.path.join(tmp, 'data', 'launch_state.json')
            with patch.object(updater, 'launch_state_path',
                                   return_value=marker):
                updater.record_launch_stage('starting')
                started = updater.read_launch_state()
                self.assertEqual('starting', started['stage'])
                self.assertEqual(os.getpid(), started['pid'])

                time.sleep(0.01)
                updater.record_launch_stage('ready')
                ready = updater.read_launch_state()
                self.assertEqual('ready', ready['stage'])
                self.assertEqual(started['started_at'], ready['started_at'])

    def test_unwritable_launch_marker_never_blocks_startup(self):
        """Licensing rule: a marker problem must not stop a shop trading."""
        from backend import updater

        with patch.object(updater, 'launch_state_path',
                               side_effect=OSError('read-only volume')):
            updater.record_launch_stage('starting')  # must not raise
            self.assertIsNone(updater.read_launch_state())


if __name__ == '__main__':
    unittest.main()
