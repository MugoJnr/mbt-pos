"""Regression tests for installer release checksum handling."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseIntegrityTests(unittest.TestCase):
    def test_checksum_is_post_build_metadata_not_embedded_self_hash(self):
        publisher = load_script("publish_release_3")
        verifier = load_script("verify_installer_integrity")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dist = root / "dist"
            dist.mkdir()
            setup = dist / "MBT_POS_Setup.exe"
            setup.write_bytes(b"installer fixture bytes")
            version_json = root / "version.json"
            version_json.write_text(
                json.dumps({"version": "9.9.9", "checksum_sha256": "a" * 64}),
                encoding="utf-8",
            )

            publisher.ROOT = root
            publisher.SETUP = setup
            publisher.VERSION_JSON = version_json
            publisher.SIDECAR = dist / "MBT_POS_Setup.exe.sha256"
            publisher.prepare_build_metadata()
            self.assertEqual(
                json.loads(version_json.read_text(encoding="utf-8"))["checksum_sha256"],
                "",
            )

            publisher.stamp_checksum()
            digest = publisher.sha256_file(setup)
            self.assertEqual(
                json.loads(version_json.read_text(encoding="utf-8"))["checksum_sha256"],
                digest,
            )
            self.assertEqual(publisher.SIDECAR.read_text().split()[0], digest)

            verifier.ROOT = root
            verifier.SETUP = setup
            verifier.VERSION_JSON = version_json
            verifier.SIDECAR = publisher.SIDECAR
            verifier.MIN_BYTES = 1
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verifier.main(), 0)

            verifier.SIDECAR.write_text("b" * 64 + "  MBT_POS_Setup.exe\n")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verifier.main(), 1)


if __name__ == "__main__":
    unittest.main()
