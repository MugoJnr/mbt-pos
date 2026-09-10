from __future__ import annotations

import hashlib
import http.server
import os
import socketserver
import threading
import time
from unittest import mock


def test_payments_client_uses_bounded_connect_and_read_timeouts():
    from desktop.payments.cloud_client import (
        CONNECT_TIMEOUT,
        READ_TIMEOUT,
        PaymentsCloudClient,
    )

    response = mock.Mock()
    response.content = b'{"ok": true}'
    response.json.return_value = {"ok": True}
    response.status_code = 200
    with (
        mock.patch("backend.cloud.net_gate.network_up", return_value=True),
        mock.patch("requests.request", return_value=response) as request,
    ):
        result = PaymentsCloudClient().health()
    assert result["ok"] is True
    assert request.call_args.kwargs["timeout"] == (CONNECT_TIMEOUT, READ_TIMEOUT)


def test_payments_client_offline_never_resolves_hostname():
    from desktop.payments.cloud_client import PaymentsCloudClient

    with (
        mock.patch("backend.cloud.net_gate.network_up", return_value=False),
        mock.patch("requests.request") as request,
    ):
        result = PaymentsCloudClient().health()
    assert result["error_code"] == "NETWORK"
    request.assert_not_called()


def test_updater_semantic_versions():
    from backend.updater import _version_gt

    assert _version_gt("3.0.90", "3.0.9")
    assert _version_gt("3.10.0", "3.9.99")
    assert not _version_gt("3.0.9", "3.0.90")


def test_updater_stale_cached_b_is_not_offered_as_c(tmp_path):
    from backend.updater import UpdateChecker

    stale = tmp_path / "MBT_POS_Setup_v3.0.90.exe"
    stale.write_bytes(b"B" * 1_000_001)
    checker = UpdateChecker("3.0.89")
    checker._installer_path = str(stale)
    checker._pending_checksum = hashlib.sha256(b"C").hexdigest()
    checker._download = mock.Mock()
    checker._start_download("https://example/C.exe", "3.0.91")

    assert checker._pending_version == "3.0.91"
    assert checker._installer_path != str(stale)
    assert not stale.exists()
    assert checker._pending_checksum == hashlib.sha256(b"C").hexdigest()


def test_updater_queues_latest_without_overlapping_workers():
    from backend.updater import UpdateChecker

    release = threading.Event()
    checker = UpdateChecker("3.0.89")

    def blocked(*_args):
        release.wait(2)

    checker._download = blocked
    checker._pending_checksum = "b" * 64
    checker._start_download("https://example/B.exe", "3.0.90")
    first = checker._dl_thread
    checker._pending_checksum = "c" * 64
    checker._start_download("https://example/C.exe", "3.0.91")

    assert checker._dl_thread is first
    assert checker._pending_version == "3.0.91"
    assert checker._supersede_download[1] == "3.0.91"
    release.set()
    first.join(2)
    if checker._dl_thread:
        checker._dl_thread.join(2)


def test_updater_real_http_a_stale_b_latest_c(tmp_path, monkeypatch):
    """Real downloader path: A installed, B in flight, C supersedes B."""
    from backend import updater

    payload_b = b"B" * 1_100_000
    payload_c = b"C" * 1_200_000

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            payload = payload_b if self.path.startswith("/B") else payload_c
            if self.path.startswith("/B"):
                time.sleep(0.15)
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater, "MIN_INSTALLER_BYTES", 100)
    monkeypatch.setattr(updater, "EXPECTED_INSTALLER_BYTES", len(payload_b))

    ready = []
    checker = updater.UpdateChecker("3.0.89")
    checker.on_download_ready = lambda path, version: ready.append(
        (version, hashlib.sha256(open(path, "rb").read()).hexdigest())
    )
    base = f"http://127.0.0.1:{server.server_port}"
    checker._pending_checksum = hashlib.sha256(payload_b).hexdigest()
    checker._start_download(base + "/B.exe", "3.0.90")
    checker._pending_checksum = hashlib.sha256(payload_c).hexdigest()
    checker._start_download(base + "/C.exe", "3.0.91")

    deadline = time.time() + 10
    while time.time() < deadline and not ready:
        time.sleep(0.05)
    server.shutdown()
    assert ready == [("3.0.91", hashlib.sha256(payload_c).hexdigest())]
    assert checker.get_pending_version() == "3.0.91"


def test_supabase_storage_fails_before_opening_file_offline(tmp_path):
    from backend.cloud_backup.supabase_client import SupabaseClient, SupabaseError

    source = tmp_path / "payload"
    source.write_bytes(b"x")
    client = object.__new__(SupabaseClient)
    client.service = ""
    client.bucket = "backups"
    with (
        mock.patch(
            "backend.cloud_backup.supabase_client._require_network",
            side_effect=SupabaseError("offline", 503),
        ),
        mock.patch("builtins.open", side_effect=AssertionError("file opened")),
    ):
        try:
            client.upload_file("x", str(source))
        except SupabaseError:
            pass
        else:
            raise AssertionError("offline upload did not fail")
