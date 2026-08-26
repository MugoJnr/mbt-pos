"""Release metadata must not rely on an impossible self-referential hash."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class ReleaseIntegrityTests(unittest.TestCase):
    def test_spec_generates_sanitized_runtime_manifest(self):
        source = (ROOT / "mbt_pos.spec").read_text(encoding="utf-8")
        self.assertIn("def _runtime_version_manifest", source)
        self.assertIn("payload['checksum_sha256'] = ''", source)
        self.assertNotIn("'deploy.local.json',", source)

    def test_installer_and_updater_share_helper_layout(self):
        installer = (ROOT / "installer.nsi").read_text(encoding="utf-8")
        updater = (ROOT / "backend" / "updater.py").read_text(
            encoding="utf-8")
        self.assertIn('SetOutPath "$INSTDIR\\deploy"', installer)
        self.assertIn(
            '-File "$INSTDIR\\deploy\\register_update_helper.ps1"',
            installer,
        )
        self.assertIn(
            "os.path.join(exe_dir, 'deploy', 'MBT_UpdateHelper.ps1')",
            updater,
        )

    def test_stamp_updates_external_metadata_only(self):
        from scripts import publish_release_3 as publish

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            setup = root / "dist" / "MBT_POS_Setup.exe"
            sidecar = root / "dist" / "MBT_POS_Setup.exe.sha256"
            manifest = root / "version.json"
            internal = root / "dist" / "MBT_POS" / "_internal" / "version.json"
            setup.parent.mkdir(parents=True)
            internal.parent.mkdir(parents=True)
            setup.write_bytes(b"certified installer bytes")
            payload = {
                "version": "9.9.9",
                "checksum_sha256": "",
                "download_url": "https://example.invalid/setup.exe",
            }
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            internal.write_text(json.dumps(payload), encoding="utf-8")

            with patch.object(publish, "SETUP", setup), \
                 patch.object(publish, "SIDECAR", sidecar), \
                 patch.object(publish, "VERSION_JSON", manifest):
                stamped = publish.stamp_checksum()

            expected = hashlib.sha256(setup.read_bytes()).hexdigest()
            self.assertEqual(stamped["checksum_sha256"], expected)
            self.assertTrue(sidecar.read_text(encoding="utf-8").startswith(expected))
            embedded = json.loads(internal.read_text(encoding="utf-8"))
            self.assertEqual(embedded["checksum_sha256"], "")


if __name__ == "__main__":
    unittest.main()
