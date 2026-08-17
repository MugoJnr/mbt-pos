"""Deterministic regression tests for superseded updater downloads."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch


class UpdaterSupersessionTests(unittest.TestCase):
    def test_late_old_download_is_not_offered_for_install(self):
        from backend.updater import UpdateChecker, UpdateManifest

        checker = UpdateChecker('3.0.62')
        old = UpdateManifest('3.0.63', 'https://example.test/3.0.63', 'a' * 64, 2, 'old')
        newer = UpdateManifest('3.0.64', 'https://example.test/3.0.64', 'b' * 64, 2, 'new')
        checker._active_manifest = old
        checker._queued_manifest = newer
        offered = []
        checker.on_download_ready = lambda path, version: offered.append((path, version))

        with tempfile.TemporaryDirectory() as td:
            def write_download(_url, dest, _headers):
                with open(dest, 'wb') as handle:
                    handle.write(b'ok')
                return 2

            # Timer is deliberately inert: this test proves the stale callback
            # is ignored, not the later network operation.
            with patch('backend.updater.tempfile.gettempdir', return_value=td), \
                 patch.object(checker, '_http_download_file', side_effect=write_download), \
                 patch.object(checker, '_download_complete_enough', return_value=True), \
                 patch('backend.updater.verify_installer_checksum', return_value=(True, 'ok')), \
                 patch('backend.updater._unblock_windows_file'), \
                 patch('backend.updater._ensure_ssl_certs'), \
                 patch('backend.updater.threading.Timer') as timer:
                checker._download(old.asset_url, old.version, old)

            self.assertEqual(offered, [])
            self.assertFalse(os.path.exists(os.path.join(td, 'MBT_POS_Setup_v3.0.63.exe')))
            timer.assert_called_once()


if __name__ == '__main__':
    unittest.main()
