"""Public releases repo is tried first; the source repo is the fallback."""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PUBLIC = "MugoJnr/mbt-pos-releases"
LEGACY = "MugoJnr/mbt-pos"
CHECKSUM = "ab" * 32


def _http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url, code, "missing", hdrs={}, fp=io.BytesIO(b"")
    )


def _payload(version: str, repo: str, with_asset: bool = True) -> dict:
    assets = []
    if with_asset:
        assets.append({
            "name": "MBT_POS_Setup.exe",
            "browser_download_url": (
                f"https://github.com/{repo}/releases/download/v{version}/MBT_POS_Setup.exe"
            ),
            "size": 50_000_000,
        })
    return {
        "tag_name": f"v{version}",
        "body": f"[checksum_sha256: {CHECKSUM}]",
        "assets": assets,
    }


class ReleaseRepoHelpersTests(unittest.TestCase):
    def test_public_url_and_asset_allowlist(self):
        from backend.release_repos import (
            is_mirror_asset,
            public_installer_url,
            release_api_url,
        )
        self.assertEqual(
            public_installer_url("3.1.84"),
            "https://github.com/MugoJnr/mbt-pos-releases/releases/download/"
            "v3.1.84/MBT_POS_Setup.exe",
        )
        self.assertTrue(release_api_url(PUBLIC).startswith(
            "https://api.github.com/repos/MugoJnr/mbt-pos-releases/"))
        self.assertTrue(is_mirror_asset("MBT_POS_Setup.exe"))
        self.assertTrue(is_mirror_asset("MBT_POS_Setup.exe.sha256"))
        self.assertFalse(is_mirror_asset("mbt-pos-source.zip"))
        self.assertFalse(is_mirror_asset("backend/updater.py"))

    def test_pick_best_prefers_higher_version_with_an_installer(self):
        from backend.release_repos import pick_best_release
        best = pick_best_release([
            {"version": "3.1.90", "asset_url": "", "repo": PUBLIC},
            {"version": "3.1.84", "asset_url": "https://example/setup.exe", "repo": LEGACY},
        ])
        self.assertEqual(best["version"], "3.1.84")
        tied = pick_best_release([
            {"version": "3.1.84", "asset_url": "https://public/setup.exe", "repo": PUBLIC},
            {"version": "3.1.84", "asset_url": "https://legacy/setup.exe", "repo": LEGACY},
        ])
        self.assertEqual(tied["asset_url"], "https://public/setup.exe")


class UpdaterFeedTests(unittest.TestCase):
    def _checker(self):
        from backend.updater import UpdateChecker
        return UpdateChecker("3.1.80")

    def _run(self, payloads):
        seen = []

        def fake_get(url, headers):
            seen.append(url)
            if url not in payloads:
                raise AssertionError(url)
            item = payloads[url]
            if isinstance(item, Exception):
                raise item
            return item

        checker = self._checker()
        with patch.object(checker, "_http_get_json", side_effect=fake_get), \
                patch("backend.updater.time.sleep") as sleep, \
                patch("backend.updater.fetch_release_via_github_redirect", return_value={}), \
                patch(
                    "backend.cloud.update_center.get_update_center",
                    side_effect=RuntimeError("offline"),
                ):
            info = checker._fetch_release_info()
        return checker, info, seen, sleep

    def test_public_404_falls_back_to_legacy_without_retry(self):
        from backend.release_repos import release_api_url
        public = release_api_url(PUBLIC)
        legacy = release_api_url(LEGACY)
        _, info, seen, sleep = self._run({
            public: _http_error(public, 404),
            legacy: _payload("3.1.84", LEGACY),
        })
        self.assertEqual(seen, [public, legacy])
        self.assertEqual(info["version"], "3.1.84")
        self.assertIn("/MugoJnr/mbt-pos/", info["asset_url"])
        self.assertNotIn("mbt-pos-releases", info["asset_url"])
        self.assertEqual(info["repo"], LEGACY)
        sleep.assert_not_called()

    def test_private_legacy_404_keeps_the_public_installer(self):
        from backend.release_repos import release_api_url
        public = release_api_url(PUBLIC)
        legacy = release_api_url(LEGACY)
        _, info, seen, _sleep = self._run({
            public: _payload("3.1.85", PUBLIC),
            legacy: _http_error(legacy, 404),
        })
        self.assertEqual(seen[0], public)
        self.assertEqual(info["version"], "3.1.85")
        self.assertIn("mbt-pos-releases", info["asset_url"])
        self.assertEqual(info["checksum_sha256"], CHECKSUM)

    def test_newer_legacy_release_wins_until_it_is_mirrored(self):
        from backend.release_repos import release_api_url
        public = release_api_url(PUBLIC)
        legacy = release_api_url(LEGACY)
        checker, info, _seen, _sleep = self._run({
            public: _payload("3.1.84", PUBLIC),
            legacy: _payload("3.1.85", LEGACY),
        })
        self.assertEqual(info["version"], "3.1.85")
        self.assertEqual(info["repo"], LEGACY)
        self.assertEqual(checker._expected_bytes, 50_000_000)

    def test_redirect_fallback_tries_public_repo_first(self):
        from backend.release_repos import release_api_url
        from backend.updater import UpdateChecker
        public = release_api_url(PUBLIC)
        legacy = release_api_url(LEGACY)
        calls = []

        def fake_redirect(headers=None, repo=None):
            calls.append(repo)
            if repo == PUBLIC:
                return {}
            return {
                "version": "3.1.84",
                "asset_url": (
                    "https://github.com/MugoJnr/mbt-pos/releases/download/"
                    "v3.1.84/MBT_POS_Setup.exe"
                ),
                "checksum_sha256": CHECKSUM,
                "notes": "",
                "repo": repo,
            }

        checker = UpdateChecker("3.1.80")

        def fake_get(url, headers):
            raise _http_error(url, 404)

        with patch.object(checker, "_http_get_json", side_effect=fake_get), \
                patch("backend.updater.time.sleep"), \
                patch("backend.updater.fetch_release_via_github_redirect", side_effect=fake_redirect), \
                patch(
                    "backend.cloud.update_center.get_update_center",
                    side_effect=RuntimeError("offline"),
                ):
            info = checker._fetch_release_info()
        self.assertEqual(calls, [PUBLIC, LEGACY])
        self.assertEqual(info["version"], "3.1.84")
        self.assertEqual(info["repo"], LEGACY)
        self.assertTrue(public.endswith("/releases/latest"))
        self.assertTrue(legacy.endswith("/releases/latest"))


class DashboardFeedTests(unittest.TestCase):
    def test_dashboard_uses_public_feed_then_legacy(self):
        from backend.shop_update import load_release_feed
        calls = []

        class Response:
            def __init__(self, payload):
                self._raw = json.dumps(payload).encode()

            def read(self):
                return self._raw

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=0):
            calls.append(request.full_url)
            if PUBLIC in request.full_url:
                raise _http_error(request.full_url, 404)
            return Response({
                "tag_name": "v3.1.84",
                "body": "notes",
                "published_at": "2026-11-12T15:02:06Z",
                "assets": [{
                    "name": "MBT_POS_Setup.exe",
                    "browser_download_url": (
                        "https://github.com/MugoJnr/mbt-pos/releases/download/"
                        "v3.1.84/MBT_POS_Setup.exe"
                    ),
                }],
            })

        with patch.dict(os.environ, {"MBT_UPDATE_FEED_JSON": ""}), \
                patch("urllib.request.urlopen", fake_urlopen):
            release, reachable = load_release_feed()
        self.assertTrue(reachable)
        self.assertEqual(release["version"], "3.1.84")
        self.assertIn(PUBLIC, calls[0])
        self.assertIn(f"/{LEGACY}/", calls[1])


class PublishMirrorTests(unittest.TestCase):
    def test_manifest_rewrites_only_the_legacy_github_url(self):
        from scripts.publish_release_3 import ensure_public_download_url
        legacy = ensure_public_download_url({
            "version": "3.1.84",
            "download_url": "https://github.com/MugoJnr/mbt-pos/releases/download/v3.1.84/MBT_POS_Setup.exe",
        })
        self.assertIn("mbt-pos-releases", legacy["download_url"])
        self.assertIn("/v3.1.84/", legacy["download_url"])
        other = ensure_public_download_url({
            "version": "9.9.9",
            "download_url": "https://example.invalid/setup.exe",
        })
        self.assertEqual(other["download_url"], "https://example.invalid/setup.exe")

    def test_public_publish_has_no_source_target(self):
        import tempfile
        from scripts import publish_release_3 as publish
        calls = []

        def fake_call(cmd, cwd=None, env=None):
            calls.append((list(cmd), env))
            return 0

        with tempfile.TemporaryDirectory() as td:
            setup = Path(td) / "MBT_POS_Setup.exe"
            sidecar = Path(td) / "MBT_POS_Setup.exe.sha256"
            setup.write_bytes(b"installer")
            sidecar.write_text(CHECKSUM + "  MBT_POS_Setup.exe\n")
            with patch.object(publish, "SETUP", setup), \
                    patch.object(publish, "SIDECAR", sidecar), \
                    patch.object(publish, "_release_exists", return_value=False), \
                    patch.object(publish.subprocess, "check_call", side_effect=fake_call):
                publish.publish_public_release(
                    {"version": "9.9.9", "checksum_sha256": CHECKSUM, "release_notes": "n"},
                    "test-token",
                )
        cmd, env = calls[0]
        self.assertIn("MugoJnr/mbt-pos-releases", cmd)
        self.assertNotIn("--target", cmd)
        self.assertNotIn("--archive", cmd)
        self.assertEqual(env["GH_TOKEN"], "test-token")

    def test_mirror_rejects_source_archives_and_missing_token(self):
        import tempfile
        from scripts.mirror_release_to_public import main, select_mirror_files
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = root / "MBT_POS_Setup.exe"
            exe.write_bytes(b"x")
            (root / "MBT_POS_Setup.exe.sha256").write_text("aa\n")
            chosen = select_mirror_files([exe, root / "MBT_POS_Setup.exe.sha256"])
            self.assertEqual(len(chosen), 2)
            rogue = root / "mbt-pos-3.1.84.zip"
            rogue.write_bytes(b"zip")
            with self.assertRaises(SystemExit):
                select_mirror_files([exe, rogue])
        env = os.environ.copy()
        env["RELEASES_REPO_TOKEN"] = ""
        env["RELEASE_TAG"] = "v3.1.84"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertIn("RELEASES_REPO_TOKEN", str(raised.exception))

    def test_workflow_uses_the_secret_and_not_a_committed_token(self):
        text = (ROOT / ".github/workflows/mirror-public-release.yml").read_text(encoding="utf-8")
        self.assertIn("secrets.RELEASES_REPO_TOKEN", text)
        self.assertIn("scripts/mirror_release_to_public.py", text)
        self.assertNotIn("github_pat_", text)
        self.assertNotIn("ghp_", text)

    def test_portal_and_manifest_name_the_public_repo(self):
        version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
        self.assertIn("mbt-pos-releases/releases/download/v", version["download_url"])
        routes = (ROOT / "web/web_routes.py").read_text(encoding="utf-8")
        self.assertIn("_public_installer_url()", routes)
        self.assertNotIn(
            "https://github.com/MugoJnr/mbt-pos/releases/latest/download/MBT_POS_Setup.exe",
            routes,
        )
        page = (ROOT / "web/mugobyte-platform/src/routes/_app.downloads.tsx").read_text(encoding="utf-8")
        self.assertLess(
            page.index('const PUBLIC_RELEASE_REPO = "MugoJnr/mbt-pos-releases"'),
            page.index('const LEGACY_RELEASE_REPO = "MugoJnr/mbt-pos"'),
        )
        self.assertIn("mbt-pos-releases", page)
        self.assertIn("api.github.com/repos/${repo}/releases/latest", page)


if __name__ == "__main__":
    unittest.main()
