"""Ensure production paths never seed a known default admin password."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest import mock


class BootstrapAdminTests(unittest.TestCase):
    def _run_bootstrap(self, db_path: str, env: dict) -> tuple:
        with mock.patch("desktop.utils.api_client.get_db_path", return_value=db_path):
            with mock.patch.dict(os.environ, env, clear=True):
                from desktop.utils import api_client

                api_client._SCHEMA_READY = False
                conn = api_client._db()
                conn.close()
                check = sqlite3.connect(db_path)
                try:
                    row = check.execute(
                        "SELECT username, role FROM users WHERE username='admin'"
                    ).fetchone()
                    return row
                finally:
                    check.close()

    def test_api_client_skips_admin_without_bootstrap_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "shop.db")
            row = self._run_bootstrap(db_path, {})
            self.assertIsNone(row)

    def test_api_client_seeds_admin_when_bootstrap_env_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "shop.db")
            row = self._run_bootstrap(
                db_path, {"MBT_BOOTSTRAP_ADMIN_PASSWORD": "TestBootstrap!99"}
            )
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "admin")
            self.assertEqual(row[1], "superadmin")


if __name__ == "__main__":
    unittest.main()
