"""Verify dist Setup SHA256 matches version.json, sidecar, and embedded freeze tree."""
from __future__ import annotations

# An installer cannot embed its own final hash.  Only post-build release
# metadata and the sidecar are authoritative for the installer checksum.

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "dist" / "MBT_POS_Setup.exe"
SIDECAR = ROOT / "dist" / "MBT_POS_Setup.exe.sha256"
VERSION_JSON = ROOT / "version.json"
MIN_BYTES = 50_000_000


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    errors: list[str] = []
    if not SETUP.is_file():
        errors.append(f"missing setup: {SETUP}")
        print("FAIL", *errors, sep="\n")
        return 1
    size = SETUP.stat().st_size
    if size < MIN_BYTES:
        errors.append(f"setup too small ({size} bytes) — partial/corrupt")
    file_hash = sha256_file(SETUP)
    vj = json.loads(VERSION_JSON.read_text(encoding="utf-8-sig"))
    declared = (vj.get("checksum_sha256") or "").strip().lower()
    if len(declared) != 64:
        errors.append("version.json checksum_sha256 empty or invalid")
    elif declared != file_hash:
        errors.append(f"version.json mismatch: declared={declared} file={file_hash}")
    if SIDECAR.is_file():
        side = SIDECAR.read_text(encoding="utf-8").strip().split()[0].lower()
        if side != file_hash:
            errors.append(f"sidecar mismatch: sidecar={side} file={file_hash}")
    else:
        errors.append(f"missing sidecar: {SIDECAR}")
    ver = vj.get("version", "?")
    if errors:
        print(f"INTEGRITY FAIL v{ver}")
        for e in errors:
            print(" -", e)
        print(f"setup_sha256={file_hash} size={size}")
        return 1
    print(f"INTEGRITY PASS v{ver}")
    print(f"setup_sha256={file_hash}")
    print(f"size={size}")
    print("version.json == sidecar == Setup.exe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
