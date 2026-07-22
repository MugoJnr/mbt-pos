"""Installer gate #4 — TEMP-only upgrade simulation (L4 PARTIAL evidence)."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "qa_upgrade_sim.py"


def _load_sim():
    spec = importlib.util.spec_from_file_location("qa_upgrade_sim", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["qa_upgrade_sim"] = mod
    spec.loader.exec_module(mod)
    return mod


class UpgradeSimGateTests(unittest.TestCase):
    def test_temp_upgrade_preserves_db_config_license(self):
        self.assertTrue(SCRIPT.is_file(), f"missing {SCRIPT}")
        sim = _load_sim()
        result = sim.run_simulation(keep=False, peek_live=False)
        self.assertTrue(
            result.get("ok"),
            f"upgrade sim failed: {result.get('errors')}",
        )
        self.assertIn("fabricate_fixtures", result.get("steps") or [])
        self.assertIn("dry_run_binary_replace", " ".join(result.get("steps") or []))
        self.assertTrue(result.get("exe_new_sha256"))
        # Must not claim clean-PC UAT; this is TEMP-only evidence
        self.assertNotIn("clean_pc", (result.get("steps") or []))


if __name__ == "__main__":
    unittest.main()
