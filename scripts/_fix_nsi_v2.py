"""Fix installer.nsi: collapse doubled newlines, ASCII-only, stamp 3.0.12."""
from __future__ import annotations

from pathlib import Path

p = Path(__file__).resolve().parents[1] / "installer.nsi"
raw = p.read_bytes()
# Collapse CRCRLF / doubled blank lines from prior encoding write
text = raw.decode("utf-8", errors="replace")
text = text.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
while "\n\n\n" in text:
    text = text.replace("\n\n\n", "\n\n")
# ASCII substitutes for smart punctuation
for a, b in (
    ("\u2014", "-"),
    ("\u2013", "-"),
    ("\u2026", "..."),
    ("\u2018", "'"),
    ("\u2019", "'"),
    ("\u201c", '"'),
    ("\u201d", '"'),
    ("\u00a9", "(c)"),
    ("\ufffd", "-"),  # replacement char from bad decode
    ("?", "-") if False else ("", ""),
):
    if a:
        text = text.replace(a, b)

# Fix remaining mojibake arrows in comments (question marks from cp1252)
text = text.replace("exe ? install", "exe -> install")
text = text.replace("files ? first", "files -> first")
text = text.replace("found ? backup", "found -> backup")
text = text.replace("files ? preserve", "files -> preserve")
text = text.replace("(AppData) ? launch", "(AppData) -> launch")
text = text.replace("backing up database...", "backing up database...")

# Stamp 3.0.12
for old, new in (
    ('VIProductVersion "3.0.11.0"', 'VIProductVersion "3.0.12.0"'),
    ('VIAddVersionKey "FileVersion"     "3.0.11"', 'VIAddVersionKey "FileVersion"     "3.0.12"'),
    ('VIAddVersionKey "ProductVersion"  "3.0.11"', 'VIAddVersionKey "ProductVersion"  "3.0.12"'),
    ("pre_upgrade\\3.0.11", "pre_upgrade\\3.0.12"),
    ("version=3.0.11", "version=3.0.12"),
    ('"Version"    "3.0.11"', '"Version"    "3.0.12"'),
    ('"DisplayVersion"       "3.0.11"', '"DisplayVersion"       "3.0.12"'),
):
    text = text.replace(old, new)

# Ensure CreateShortcut continuations are single-line-break form
lines = text.split("\n")
out = []
i = 0
while i < len(lines):
    line = lines[i]
    # Skip accidental empty lines that sit between a trailing \ and its continuation
    if line.rstrip().endswith("\\") and i + 1 < len(lines) and lines[i + 1].strip() == "":
        out.append(line.rstrip())
        i += 1
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        continue
    out.append(line.rstrip())
    i += 1
text = "\n".join(out).strip() + "\n"
p.write_text(text, encoding="utf-8", newline="\n")
print("lines", len(text.splitlines()), "has_0x97", 0x97 in p.read_bytes())
# Quick sanity: CreateShortcut lines
for n, L in enumerate(text.splitlines(), 1):
    if "CreateShortcut" in L or (L.strip().startswith("$INSTDIR") and n > 140):
        if "CreateShortcut" in L or L.rstrip().endswith("\\") or "SW_SHOWNORMAL" in L:
            print(f"{n}: {L[:100]}")
