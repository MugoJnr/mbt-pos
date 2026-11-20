"""Daraja secrets stay on this Windows machine, encrypted with DPAPI.

The API never returns them. They are not written into the shop database.
"""
from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes

from mbt_paths import get_data_dir


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def secret_file(path: str | None = None) -> str:
    return path or os.path.join(get_data_dir(), "daraja_credentials.bin")


def _incoming(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def protect(data: bytes) -> bytes:
    incoming, _buffer = _incoming(data)
    outgoing = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(outgoing),
    ):
        raise OSError("Windows could not protect the Daraja secrets.")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)


def unprotect(data: bytes) -> bytes:
    incoming, _buffer = _incoming(data)
    outgoing = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(outgoing),
    ):
        raise OSError("Windows could not read the Daraja secrets.")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)


def _read(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    with open(path, "rb") as handle:
        raw = handle.read()
    if not raw:
        return {}
    loaded = json.loads(unprotect(raw).decode("utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _write(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    protected = protect(json.dumps(payload).encode("utf-8"))
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(protected)
    os.replace(temporary, path)


def store_profile_secrets(profile_id: str, consumer_key: str, consumer_secret: str, passkey: str, path: str | None = None) -> None:
    target = secret_file(path)
    payload = _read(target) if os.path.isfile(target) else {}
    payload[profile_id] = {
        "consumer_key": consumer_key,
        "consumer_secret": consumer_secret,
        "passkey": passkey,
    }
    _write(target, payload)


def load_profile_secrets(profile_id: str, path: str | None = None) -> dict | None:
    payload = _read(secret_file(path))
    row = payload.get(profile_id)
    if not isinstance(row, dict):
        return None
    if not row.get("consumer_key") or not row.get("consumer_secret") or not row.get("passkey"):
        return None
    return row
