"""Regression guard for the v3.0.99 UI freeze.

Every path helper used to call ``get_project_root()``, which in a frozen build
re-ran legacy migration: open ``mbt_pos.db``, set ``PRAGMA journal_mode=WAL``
and run three ``COUNT(*)`` scans, plus five ``mkdir`` calls and a marker
rewrite. ``SyncManager.status()`` reaches those helpers dozens of times and is
called from the Cloud Backup panel on the Qt main thread, so the window stopped
responding — offline and online alike, and worse the larger the sales table.
"""
from __future__ import annotations

import mbt_paths
import runtime_security
from backend.cloud_backup import paths as cloud_paths


def _use_temp_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MBT_DATA_ROOT", str(tmp_path))
    mbt_paths.reset_path_cache()
    runtime_security.reset_secret_cache()
    cloud_paths._CIPHER_CACHE.clear()


def test_project_root_runs_legacy_migration_probe_once(tmp_path, monkeypatch):
    _use_temp_root(tmp_path, monkeypatch)
    probes = []
    monkeypatch.setattr(
        mbt_paths, "_db_has_shop_data", lambda path: probes.append(path) or False
    )

    # First resolution legitimately probes the canonical root and each legacy
    # candidate; every later lookup must add nothing.
    first = mbt_paths.get_project_root()
    after_first = len(probes)

    roots = {mbt_paths.get_project_root() for _ in range(50)}

    assert roots == {first}
    assert len(probes) == after_first, (
        f"legacy migration re-probed the database {len(probes) - after_first}x "
        "after the root was already known"
    )


def test_ensure_data_dirs_writes_marker_once(tmp_path, monkeypatch):
    _use_temp_root(tmp_path, monkeypatch)
    writes = []
    monkeypatch.setattr(mbt_paths, "_write_path_marker", writes.append)

    for _ in range(50):
        mbt_paths.ensure_data_dirs(str(tmp_path))

    assert len(writes) == 1


def test_ensure_data_dirs_recreates_removed_tree(tmp_path, monkeypatch):
    _use_temp_root(tmp_path, monkeypatch)
    root = mbt_paths.ensure_data_dirs(str(tmp_path))
    assert (tmp_path / "data").is_dir()

    import shutil

    shutil.rmtree(tmp_path / "data")
    mbt_paths.ensure_data_dirs(root)

    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "data" / "DATA_LOCATION.txt").exists()


def test_jwt_secret_reads_disk_once(tmp_path, monkeypatch):
    _use_temp_root(tmp_path, monkeypatch)
    monkeypatch.delenv("MBT_JWT_SECRET", raising=False)

    first = runtime_security.get_jwt_secret()
    secret_file = tmp_path / "config" / ".jwt_secret"
    assert secret_file.exists()

    # A deleted file must not change the in-process secret, otherwise sealed
    # cloud tokens would silently stop decrypting mid-session.
    secret_file.unlink()
    assert runtime_security.get_jwt_secret() == first


def test_identity_cipher_is_reused_per_secret(tmp_path, monkeypatch):
    _use_temp_root(tmp_path, monkeypatch)
    monkeypatch.setenv("MBT_JWT_SECRET", "x" * 40)

    assert cloud_paths._identity_cipher() is cloud_paths._identity_cipher()

    monkeypatch.setenv("MBT_JWT_SECRET", "y" * 40)
    assert cloud_paths._identity_cipher() is not None


def test_protected_roundtrip_still_works(tmp_path, monkeypatch):
    _use_temp_root(tmp_path, monkeypatch)
    monkeypatch.setenv("MBT_JWT_SECRET", "z" * 40)

    sealed = cloud_paths._protect("token-value")
    assert cloud_paths._unprotect_checked(sealed) == ("token-value", True)


class _FakeBtn:
    """Stand-in for the QPushButton the orphan-flash guard inspects."""

    def objectName(self):
        return "primaryBtn"

    def windowTitle(self):
        return ""

    def x(self):
        return 448

    def y(self):
        return 192

    def width(self):
        return 102

    def height(self):
        return 52

    def parent(self):
        return None


def test_repeated_flash_logs_warn_once_and_buffer_stays_bounded(caplog):
    """Flash logging runs on the Qt main thread: one disk write per Show."""
    import logging

    from desktop.utils import quiet_ui

    quiet_ui.clear_flash_events()
    widget = _FakeBtn()

    with caplog.at_level(logging.DEBUG, logger="mbt.quiet_ui"):
        for _ in range(500):
            quiet_ui._record_flash("Show", widget, False)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, f"{len(warnings)} warnings for one repeated widget"
    assert quiet_ui.flash_event_count() == 500
    assert len(quiet_ui.FLASH_EVENTS) <= quiet_ui._FLASH_MAX_ROWS

    quiet_ui.clear_flash_events()
    assert quiet_ui.flash_event_count() == 0


def test_sync_status_does_not_reopen_database(tmp_path, monkeypatch):
    """The real freeze: one status() poll hammering the shop database."""
    _use_temp_root(tmp_path, monkeypatch)
    from backend.cloud_backup.sync_manager import SyncManager

    manager = SyncManager()
    manager.status()  # warm caches the way a running app already would

    probes = []
    writes = []
    monkeypatch.setattr(
        mbt_paths, "_db_has_shop_data", lambda path: probes.append(path) or False
    )
    monkeypatch.setattr(mbt_paths, "_write_path_marker", writes.append)

    for _ in range(10):
        manager.status()

    assert probes == [], f"status() reopened the database {len(probes)}x"
    assert writes == [], f"status() rewrote the path marker {len(writes)}x"
