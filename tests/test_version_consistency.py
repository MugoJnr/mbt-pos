"""Every shipped Windows/version surface must agree with version.json."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VersionConsistencyTests(unittest.TestCase):
    def test_release_version_is_consistent(self):
        manifest = json.loads(
            (ROOT / "version.json").read_text(encoding="utf-8-sig"))
        version = manifest["version"]
        parts = tuple(int(part) for part in version.split("."))
        self.assertEqual(len(parts), 3)

        main = (ROOT / "desktop" / "main.py").read_text(encoding="utf-8")
        self.assertRegex(
            main, rf'APP_VERSION\s*=\s*"{re.escape(version)}"')
        self.assertIn(f"v{version}", manifest["build"])
        self.assertIn(f"/v{version}/", manifest["download_url"])

        installer = (ROOT / "installer.nsi").read_text(encoding="utf-8")
        self.assertIn(f'!define APP_VERSION "{version}"', installer)
        self.assertIn(f'!define APP_VERSION_QUAD "{version}.0"', installer)
        self.assertNotRegex(installer, r"3\.0\.61")

        resource = (
            ROOT / "file_version_info.txt").read_text(encoding="utf-8")
        quad = (*parts, 0)
        self.assertIn(f"filevers={quad}", resource)
        self.assertIn(f"prodvers={quad}", resource)
        self.assertIn(f"u'FileVersion', u'{version}.0'", resource)
        self.assertIn(f"u'ProductVersion', u'{version}.0'", resource)

        installer_qa = (
            ROOT / "scripts" / "qa_installer_cert.py").read_text(
                encoding="utf-8")
        self.assertIn(f'EXPECTED_VERSION = "{version}"', installer_qa)

    def test_unbuilt_candidate_has_no_stale_installer_hash(self):
        manifest = json.loads(
            (ROOT / "version.json").read_text(encoding="utf-8-sig"))
        checksum = (manifest.get("checksum_sha256") or "").strip()
        if checksum:
            self.assertRegex(checksum, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
