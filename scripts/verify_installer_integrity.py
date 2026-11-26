"""Verify installer hash metadata and packaged runtime version are consistent."""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "dist" / "MBT_POS_Setup.exe"
SIDECAR = ROOT / "dist" / "MBT_POS_Setup.exe.sha256"
VERSION_JSON = ROOT / "version.json"
INTERNAL = ROOT / "dist" / "MBT_POS" / "_internal" / "version.json"
MIN_BYTES = 50_000_000


_FH_SIG = 0xDEADBEEF
_FH_INT1 = 0x6C6C754E  # "Null"
_FH_INT2 = 0x74666F73  # "soft"
_FH_INT3 = 0x74736E49  # "Inst"
_FH_FLAGS_MASK = 0xF


def nsis_crc_status(path: Path) -> tuple[bool, str]:
    """Replay the NSIS 3.10 stub CRC walk (exehead/fileform.c loadHeaders).

    A file can have the right size and a SHA-256 we recorded ourselves and
    still show "Installer integrity check has failed" if the trailer CRC does
    not match the bytes the stub reads. That is what shops hit on 3.1.96.
    """
    data = path.read_bytes()
    length = len(data)
    left = length
    pos = 0
    crc = 0
    header_at = 0
    stored_at = -1
    while left > 0:
        chunk_len = min(left, 32768 if header_at else 512)
        chunk = data[pos:pos + chunk_len]
        if len(chunk) < chunk_len:
            return False, "installer ended before the CRC walk finished"
        if not header_at and chunk_len >= 28:
            flags, sig, a, b, c, _hdrlen, datalen = struct.unpack_from("<7I", chunk)
            if (
                (flags & ~_FH_FLAGS_MASK) == 0
                and sig == _FH_SIG
                and a == _FH_INT1
                and b == _FH_INT2
                and c == _FH_INT3
            ):
                header_at = pos
                if datalen > left:
                    return False, "NSIS header length runs past the end of the file"
                left = datalen - 4
                if chunk_len > left:
                    chunk_len = left
                    chunk = chunk[:chunk_len]
                stored_at = pos + datalen - 4
        if left < length:
            crc = binascii.crc32(chunk, crc) & 0xFFFFFFFF
        pos += chunk_len
        left -= chunk_len
    if not header_at or stored_at < 0 or stored_at + 4 > length:
        return False, "NSIS header or trailer CRC is missing"
    stored = struct.unpack_from("<I", data, stored_at)[0]
    if crc != stored:
        return False, f"NSIS CRC mismatch stored={stored:#010x} calculated={crc:#010x}"
    return True, f"NSIS CRC {stored:#010x}"


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
    crc_ok, crc_detail = nsis_crc_status(SETUP)
    if not crc_ok:
        errors.append(crc_detail)
    file_hash = sha256_file(SETUP)
    vj = json.loads(VERSION_JSON.read_text(encoding="utf-8-sig"))
    declared = (vj.get("checksum_sha256") or "").strip().lower()
    if len(declared) != 64:
        errors.append("version.json checksum_sha256 empty or invalid")
    elif declared != file_hash:
        errors.append(f"version.json mismatch: declared={declared} file={file_hash}")
    if INTERNAL.is_file():
        internal = json.loads(INTERNAL.read_text(encoding="utf-8-sig"))
        if internal.get("version") != vj.get("version"):
            errors.append(
                "embedded version mismatch: "
                f"embedded={internal.get('version')} release={vj.get('version')}")
        embedded_hash = (internal.get("checksum_sha256") or "").strip()
        if embedded_hash:
            errors.append(
                "embedded manifest must not carry its enclosing installer hash")
    else:
        errors.append(f"missing embedded tree: {INTERNAL}")
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
    print("version.json == sidecar == Setup.exe; embedded version matches")
    print(crc_detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
