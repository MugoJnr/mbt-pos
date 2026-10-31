"""The open dashboard must be able to see the release the server is serving."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class DashboardReleaseTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "dash.db")
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        ac._db().close()
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        self.client = appmod.app.test_client()
        from web import web_routes
        self.routes = web_routes

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()

    def test_version_endpoint_is_not_cached_and_names_the_script(self):
        response = self.client.get("/api/dashboard-version")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:300])
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        body = response.get_json()
        self.assertTrue(body.get("version"))
        self.assertTrue(str(body.get("entry_script") or "").startswith("/assets/"))
        self.assertTrue(body.get("asset_ready"))

    def test_html_revalidates_and_hashed_assets_can_be_cached(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("no-cache", page.headers.get("Cache-Control", ""))
        route = self.client.get("/pos")
        self.assertEqual(route.status_code, 200)
        self.assertIn("no-cache", route.headers.get("Cache-Control", ""))
        script = self.client.get("/api/dashboard-version").get_json()["entry_script"]
        asset = self.client.get(script)
        self.assertEqual(asset.status_code, 200)
        self.assertIn("immutable", asset.headers.get("Cache-Control", ""))

    def test_missing_script_is_not_reported_as_ready(self):
        with patch.object(self.routes, "_dashboard_entry_script", return_value="/assets/index-missing.js"):
            body = self.routes._dashboard_release()
        self.assertEqual(body["entry_script"], "/assets/index-missing.js")
        self.assertFalse(body["asset_ready"])

    def test_version_route_does_not_claim_a_cached_copy(self):
        response = self.client.get("/api/version")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))


if __name__ == "__main__":
    unittest.main()
