"""Shop settings: one save path, versions, and a history that hides secrets."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.settings_service import apply_changes, read_history, read_meta


class SettingsServiceTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.db = sqlite3.connect(os.path.join(self._dir.name, "settings.db"))
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
        )

    def tearDown(self):
        self.db.close()
        self._dir.cleanup()

    def test_save_is_versioned_and_a_stale_save_does_not_overwrite(self):
        first = apply_changes(
            self.db, {"shop_name": "QA Shop", "config_version": 0, "source": "desktop"},
            role="admin", username="qa-admin",
        )
        self.assertTrue(first["success"], first)
        self.assertEqual(first["config_version"], 1)
        stale = apply_changes(
            self.db, {"shop_name": "Older edit", "config_version": 0},
            role="admin", username="other",
        )
        self.assertFalse(stale["success"])
        self.assertTrue(stale.get("conflict"))
        row = self.db.execute("SELECT value FROM system_settings WHERE key='shop_name'").fetchone()
        self.assertEqual(row["value"], "QA Shop")
        history = read_history(self.db)
        self.assertEqual(history[0]["result"], "conflict")
        self.assertIn("shop_name", [item["setting_key"] for item in history])

    def test_finance_currency_replaces_the_shop_currency(self):
        saved = apply_changes(
            self.db,
            {"shop_name": "QA Shop", "currency_symbol": "KES", "currency_code": "USD", "tax_rate": "16"},
            role="superadmin", username="owner",
        )
        self.assertTrue(saved["success"], saved)
        rows = {
            row["key"]: row["value"]
            for row in self.db.execute("SELECT key, value FROM system_settings")
        }
        self.assertEqual(rows["currency_symbol"], "USD")
        self.assertEqual(rows["currency_code"], "USD")
        self.assertEqual(rows["tax_rate"], "16.0")

    def test_invalid_tax_does_not_save_the_shop_name(self):
        failed = apply_changes(
            self.db, {"shop_name": "Should not stick", "tax_rate": "150"},
            role="admin", username="qa-admin",
        )
        self.assertFalse(failed["success"])
        count = self.db.execute("SELECT COUNT(*) AS c FROM system_settings").fetchone()["c"]
        self.assertEqual(count, 0)
        self.assertEqual(read_meta(self.db)["config_version"], 0)

    def test_cashier_cannot_save_and_production_mpesa_is_rejected(self):
        denied = apply_changes(self.db, {"shop_name": "Nope"}, role="cashier", username="till")
        self.assertFalse(denied["success"])
        blocked = apply_changes(
            self.db, {"daraja_environment": "production", "shop_name": "QA Shop"},
            role="admin", username="qa-admin",
        )
        self.assertFalse(blocked["success"])
        secret = apply_changes(
            self.db, {"daraja_passkey": "not-a-real-secret"},
            role="superadmin", username="owner",
        )
        self.assertFalse(secret["success"])

    def test_pin_change_is_hidden_in_history(self):
        saved = apply_changes(
            self.db, {"superadmin_pin_hash": "unit-test-hash"},
            role="superadmin", username="owner",
        )
        self.assertTrue(saved["success"], saved)
        shown = str(read_history(self.db))
        self.assertNotIn("unit-test-hash", shown)
        self.assertIn("[hidden]", shown)

    def test_unchanged_save_does_not_bump_the_version(self):
        apply_changes(self.db, {"shop_name": "QA Shop", "config_version": 0}, role="admin", username="qa-admin")
        again = apply_changes(
            self.db, {"shop_name": "QA Shop", "config_version": 1},
            role="admin", username="qa-admin",
        )
        self.assertTrue(again["success"], again)
        self.assertEqual(again["changed"], [])
        self.assertEqual(again["config_version"], 1)


if __name__ == "__main__":
    unittest.main()
