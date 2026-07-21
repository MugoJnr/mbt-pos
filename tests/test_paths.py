"""Regression tests for canonical runtime path bootstrap."""
from __future__ import annotations

from pathlib import Path

from mbt_paths import ensure_data_dirs


def test_ensure_data_dirs_writes_marker_without_recursion(tmp_path: Path):
    root = Path(ensure_data_dirs(str(tmp_path)))

    for name in ("logs", "data", "config", "exports", "backups"):
        assert (root / name).is_dir()

    marker = (root / "data" / "DATA_LOCATION.txt").read_text(encoding="utf-8")
    assert f"Database: {root / 'data' / 'mbt_pos.db'}" in marker
    assert f"Root: {root}" in marker
