"""Contract: Telegram runtime dependencies must remain zero.

Fails if production modules reintroduce Telegram bots, API hosts, or env vars.
Historical QA scripts under _*.py and docs that only mention removal are ignored.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN = [
    re.compile(r"api\.telegram\.org", re.I),
    re.compile(r"\btelebot\b", re.I),
    re.compile(r"python-telegram-bot", re.I),
    re.compile(r"TELEGRAM_BOT_TOKEN"),
    re.compile(r"telegram_bot_token\s*="),
    re.compile(r"from\s+telegram\b"),
    re.compile(r"import\s+telegram\b"),
]

SCAN_GLOBS = [
    "backend/**/*.py",
    "desktop/**/*.py",
    "licensing/**/*.py",
    "web/**/*.py",
    "web/**/*.{ts,tsx}",
    "config/*.py",
    "diagnostics/**/*.py",
    "printing/**/*.py",
    "BUILD.bat",
    "installer.nsi",
    "requirements*.txt",
    "deploy/**/*",
]


def _iter_files():
    seen = set()
    for pattern in SCAN_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            if path.name.startswith("_"):
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            yield path


def test_no_telegram_runtime_dependencies():
    violations = []
    for path in _iter_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Allow explicit "Telegram has been permanently removed" messaging.
        cleaned = re.sub(
            r"Telegram has been permanently removed[^\n]*",
            "",
            text,
            flags=re.I,
        )
        cleaned = re.sub(
            r"replaces?\s+Telegram[^\n]*",
            "",
            cleaned,
            flags=re.I,
        )
        for pattern in FORBIDDEN:
            if pattern.search(cleaned):
                violations.append(f"{path.relative_to(ROOT)} :: {pattern.pattern}")
    assert not violations, "Telegram runtime dependencies found:\n" + "\n".join(violations)
