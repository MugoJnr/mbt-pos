"""Download percentage comes from bytes received, and only hits 100 when finished."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.update_progress import percent_for_bytes, read_update_progress, write_update_progress


class UpdateProgressTests(unittest.TestCase):
    def test_percentage_follows_bytes_and_waits_for_completion(self):
        self.assertIsNone(percent_for_bytes(500, 0))
        self.assertEqual(percent_for_bytes(0, 1000), 0)
        self.assertEqual(percent_for_bytes(450, 1000), 45)
        self.assertEqual(percent_for_bytes(1000, 1000), 99)
        self.assertEqual(percent_for_bytes(1000, 1000, complete=True), 100)

    def test_failure_clears_the_percentage(self):
        folder = tempfile.mkdtemp()
        with patch("backend.update_progress.get_data_dir", return_value=folder):
            write_update_progress(
                state="downloading", version="9.9.9", percent=45,
                written=450, expected=1000, message="Downloading update... 45%",
            )
            self.assertEqual(read_update_progress()["percent"], 45)
            failed = write_update_progress(state="failed", version="9.9.9", percent=45, message="Download failed")
            self.assertIsNone(failed["percent"])
            self.assertIsNone(read_update_progress()["percent"])
            self.assertEqual(read_update_progress()["state"], "failed")

    def test_checker_reports_the_byte_percentage(self):
        from backend.updater import UpdateChecker
        seen = []
        checker = UpdateChecker("3.1.76")
        checker._pending_version = "9.9.9"
        checker._expected_bytes = 1000
        checker.on_download_progress = lambda version, percent, message: seen.append((version, percent, message))
        folder = tempfile.mkdtemp()
        with patch("backend.update_progress.get_data_dir", return_value=folder):
            checker._report_download_progress(450)
            checker._report_download_progress(1000, complete=True, state="complete")
            checker._report_download_progress(0, state="failed", message="Download failed")
        self.assertEqual(seen[0][1], 45)
        self.assertIn("45%", seen[0][2])
        self.assertEqual(seen[1][1], 100)
        self.assertEqual(seen[1][2], "Download complete")
        self.assertIsNone(seen[2][1])


if __name__ == "__main__":
    unittest.main()
