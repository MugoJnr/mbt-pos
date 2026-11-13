"""Normalize installer.nsi to UTF-8 without Windows-1252 smart punctuation."""
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "installer.nsi"
raw = p.read_bytes()
fixed = (
    raw.replace(bytes([0x97]), b"-")
    .replace(bytes([0x96]), b"-")
    .replace(bytes([0x91]), b"'")
    .replace(bytes([0x92]), b"'")
    .replace(bytes([0x93]), b'"')
    .replace(bytes([0x94]), b'"')
)
text = fixed.decode("latin-1")
for a, b in (
    ("\u2014", "-"),
    ("\u2013", "-"),
    ("\u2026", "..."),
    ("\u2018", "'"),
    ("\u2019", "'"),
    ("\u201c", '"'),
    ("\u201d", '"'),
):
    text = text.replace(a, b)
p.write_text(text, encoding="utf-8", newline="\r\n")
out = p.read_bytes()
print("ok", len(raw), "->", len(out), "has_0x97", 0x97 in out, "bom", out[:3] == b"\xef\xbb\xbf")
