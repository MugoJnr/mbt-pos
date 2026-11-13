"""Rebuild installer.nsi as clean UTF-8 from git HEAD, stamped 3.0.12."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "installer.nsi"
VER = "3.0.12"

raw = subprocess.check_output(["git", "show", "HEAD:installer.nsi"], cwd=str(ROOT))
if raw.startswith(b"\xef\xbb\xbf"):
    raw = raw[3:]
raw = (
    raw.replace(b"\x97", b"-")
    .replace(b"\x96", b"-")
    .replace(b"\x91", b"'")
    .replace(b"\x92", b"'")
    .replace(b"\x93", b'"')
    .replace(b"\x94", b'"')
    .replace(b"\xa9", b"(c)")
)
text = raw.decode("latin-1").replace("\r\n", "\n").replace("\r", "\n")
for a, b in (
    ("\u2014", "-"),
    ("\u2013", "-"),
    ("\u2026", "..."),
    ("\u00a9", "(c)"),
    ("\ufffd", "-"),
):
    text = text.replace(a, b)

# Replace version numbers like 3.0.N or 3.0.N.0 — never substring-chomp 3.0.12
text = re.sub(r"\b3\.0\.\d+\.0\b", f"{VER}.0", text)
text = re.sub(r"\b3\.0\.\d+\b", VER, text)

if "MugoByte Workspace.lnk" not in text:
    needle = (
        'CreateShortcut  "$SMPROGRAMS\\MugoByte\\MBT POS\\Uninstall MBT POS.lnk" \\\n'
        '                    "$INSTDIR\\Uninstall.exe"'
    )
    insert = (
        needle
        + "\n"
        + '    CreateShortcut  "$SMPROGRAMS\\MugoByte\\MBT POS\\MugoByte Workspace.lnk" \\\n'
        + '                    "https://portal.mugobyte.com" "" "$INSTDIR\\MBT_POS.exe" 0 \\\n'
        + '                    SW_SHOWNORMAL "" "MugoByte Workspace - downloads, licenses, devices"'
    )
    if needle not in text:
        raise SystemExit("Could not find Uninstall shortcut block")
    text = text.replace(needle, insert, 1)

text = text.replace("MugoByte Portal.lnk", "MugoByte Workspace.lnk")
if 'Delete "$SMPROGRAMS\\MugoByte\\MBT POS\\MugoByte Workspace.lnk"' not in text:
    text = text.replace(
        'Delete "$SMPROGRAMS\\MugoByte\\MBT POS\\Uninstall MBT POS.lnk"',
        'Delete "$SMPROGRAMS\\MugoByte\\MBT POS\\Uninstall MBT POS.lnk"\n'
        '    Delete "$SMPROGRAMS\\MugoByte\\MBT POS\\MugoByte Workspace.lnk"',
    )

# Normalize LegalCopyright / FileDescription to ASCII-safe quoted values
text = re.sub(
    r'VIAddVersionKey "LegalCopyright"\s+".*"',
    'VIAddVersionKey "LegalCopyright"  "(c) 2026 MugoByte Technologies"',
    text,
)
text = re.sub(
    r'VIAddVersionKey "FileDescription"\s+".*"',
    'VIAddVersionKey "FileDescription" "MBT POS Installer - auto new/upgrade"',
    text,
)
text = re.sub(
    r'DetailPrint "Upgrade detected.*"',
    'DetailPrint "Upgrade detected - backing up database..."',
    text,
)
# Workspace shortcut comment must be ASCII (no smart dashes)
text = re.sub(
    r'SW_SHOWNORMAL "" "MugoByte Workspace[^"]*"',
    'SW_SHOWNORMAL "" "MugoByte Workspace - downloads, licenses, devices"',
    text,
)

out.write_bytes(text.encode("utf-8"))
print("wrote", out, "lines", text.count("\n") + 1)
print("sample versions:", [L.strip() for L in text.splitlines() if VER in L][:8])
assert "3.0.122" not in text
assert "MugoByte Workspace.lnk" in text
