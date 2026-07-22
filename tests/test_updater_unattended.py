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

    def test_missing_helper_blocks_unattended_allows_reason(self):
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
                self.assertEqual(reason, 'helper_not_registered')
                ok, err = uc.install_and_restart(path, unattended=True)
                self.assertFalse(ok)
                self.assertIn('helper', err.lower())

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


if __name__ == '__main__':
    unittest.main()
