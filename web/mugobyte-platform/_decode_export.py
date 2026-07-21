"""Decode corrupted Lovable export (space-separated char codes) back to UTF-8 text."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def decode_content(raw: str) -> str | None:
    raw = raw.strip().lstrip("\ufeff")
    if not raw:
        return None
    sample = raw[:300].replace("\n", " ").replace("\r", " ")
    if not re.match(r"^[\d\s]+$", sample):
        return None
    parts = re.split(r"\s+", raw.strip())
    try:
        chars = [chr(int(p)) for p in parts if p.isdigit()]
    except ValueError:
        return None
    text = "".join(chars)
    if len(text) < 10:
        return None
    return text


def main() -> None:
    fixed = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix in {".py", ".lock", ".ico", ".png", ".jpg"}:
            continue
        if path.name.startswith("_"):
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        decoded = decode_content(raw)
        if decoded:
            path.write_text(decoded, encoding="utf-8", newline="\n")
            fixed += 1
            print("fixed", path.relative_to(ROOT))
    print(f"Done — {fixed} files decoded")


if __name__ == "__main__":
    main()
