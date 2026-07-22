"""
AES-256-GCM encryption for Cloud Backup payloads.

Uses cryptography if installed; otherwise Windows CNG (bcrypt.dll) via ctypes.
Keys are derived with PBKDF2-HMAC-SHA256 from a business secret + salt.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import struct
from typing import Optional

logger = logging.getLogger('cloud_backup.encryption')

MAGIC = b'MBTB1'  # versioned envelope
PBKDF2_ITERS = 200_000
SALT_LEN = 16
NONCE_LEN = 12
KEY_LEN = 32
TAG_LEN = 16


class EncryptionError(Exception):
    pass


def generate_salt() -> str:
    return secrets.token_hex(SALT_LEN)


def derive_key(passphrase: str, salt_hex: str) -> bytes:
    if not passphrase:
        raise EncryptionError('Empty encryption passphrase')
    salt = bytes.fromhex(salt_hex) if len(salt_hex) == SALT_LEN * 2 else salt_hex.encode('utf-8')
    return hashlib.pbkdf2_hmac('sha256', passphrase.encode('utf-8'), salt, PBKDF2_ITERS, dklen=KEY_LEN)


def _business_passphrase(business_id: str, user_id: str = '', extra: str = '') -> str:
    """Deterministic passphrase material from business identity (not transmitted)."""
    material = f'mbt-cloud|{business_id}|{user_id}|{extra}'
    return hashlib.sha256(material.encode('utf-8')).hexdigest()


def _deterministic_salt(business_id: str, user_id: str = '') -> str:
    """
    Portable salt derived from the cloud account identity.

    The default (password-less) backup key MUST be reproducible on any device
    that signs into the same MugoByte account, otherwise a fresh install can
    never decrypt existing cloud backups. business_id + user_id both come back
    from the cloud on login, so deriving the salt from them makes the key
    fully recoverable without ever transmitting the salt.
    """
    material = f'mbt-cloud-salt|{business_id}|{user_id}'
    return hashlib.sha256(material.encode('utf-8')).hexdigest()[:SALT_LEN * 2]


def ensure_identity_key_material(identity: dict, password: str = '') -> tuple[bytes, dict]:
    """
    Return (aes_key, updated_identity) for encrypting/decrypting cloud backups.

    Default (no password): use a DETERMINISTIC salt + passphrase derived from the
    business/user identity so the key can be reproduced on any device that logs
    into the same account (device migration / disaster recovery).

    With a user password: keep a per-identity random salt (stored locally). Note
    that password-protected backups are only portable if that salt is preserved.
    """
    biz = identity.get('business_id') or 'local'
    uid = identity.get('user_id') or ''

    if password:
        salt = identity.get('encryption_salt') or ''
        if not salt:
            salt = generate_salt()
            identity = dict(identity)
            identity['encryption_salt'] = salt
        key = derive_key(password.strip(), salt)
        return key, identity

    # Password-less path → fully account-derived, portable across devices.
    salt = _deterministic_salt(biz, uid)
    key = derive_key(_business_passphrase(biz, uid), salt)
    return key, identity


def derive_candidate_keys(identity: dict, password: str = '') -> list[bytes]:
    """
    Ordered list of keys to try when decrypting a backup.

    Covers backups created by the current portable scheme as well as legacy
    backups made with a locally-stored random salt, so restores keep working
    across the migration.
    """
    biz = identity.get('business_id') or 'local'
    uid = identity.get('user_id') or ''
    stored = identity.get('encryption_salt') or ''

    candidates: list[bytes] = []

    def _add(passphrase: str, salt: str) -> None:
        if not salt:
            return
        try:
            key = derive_key(passphrase, salt)
        except EncryptionError:
            return
        if key not in candidates:
            candidates.append(key)

    if password:
        # Password backups: password + (stored | deterministic) salt.
        _add(password.strip(), stored)
        _add(password.strip(), _deterministic_salt(biz, uid))

    # Portable, account-derived key (current default scheme).
    _add(_business_passphrase(biz, uid), _deterministic_salt(biz, uid))
    # Legacy: business passphrase + locally-stored random salt.
    _add(_business_passphrase(biz, uid), stored)

    return candidates


def encrypt_bytes(plaintext: bytes, key: bytes) -> bytes:
    if len(key) != KEY_LEN:
        raise EncryptionError('Key must be 32 bytes')
    nonce = secrets.token_bytes(NONCE_LEN)
    ciphertext, tag = _aes_gcm_encrypt(key, nonce, plaintext)
    # envelope: MAGIC | salt_unused(0) | nonce | tag | ciphertext
    return MAGIC + nonce + tag + ciphertext


def decrypt_bytes(blob: bytes, key: bytes) -> bytes:
    if len(key) != KEY_LEN:
        raise EncryptionError('Key must be 32 bytes')
    if not blob.startswith(MAGIC):
        raise EncryptionError('Not an MBT backup envelope (bad magic)')
    off = len(MAGIC)
    nonce = blob[off:off + NONCE_LEN]
    off += NONCE_LEN
    tag = blob[off:off + TAG_LEN]
    off += TAG_LEN
    ciphertext = blob[off:]
    return _aes_gcm_decrypt(key, nonce, ciphertext, tag)


def encrypt_file(src_path: str, dst_path: str, key: bytes) -> int:
    with open(src_path, 'rb') as f:
        data = f.read()
    blob = encrypt_bytes(data, key)
    with open(dst_path, 'wb') as f:
        f.write(blob)
    return len(blob)


def decrypt_file(src_path: str, dst_path: str, key: bytes) -> int:
    with open(src_path, 'rb') as f:
        blob = f.read()
    plain = decrypt_bytes(blob, key)
    with open(dst_path, 'wb') as f:
        f.write(plain)
    return len(plain)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _aes_gcm_encrypt(key: bytes, nonce: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aes = AESGCM(key)
        out = aes.encrypt(nonce, plaintext, None)
        return out[:-TAG_LEN], out[-TAG_LEN:]
    except ImportError:
        return _win_aes_gcm_encrypt(key, nonce, plaintext)


def _aes_gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aes = AESGCM(key)
        return aes.decrypt(nonce, ciphertext + tag, None)
    except ImportError:
        return _win_aes_gcm_decrypt(key, nonce, ciphertext, tag)


# ── Windows CNG (bcrypt.dll) fallback ─────────────────────────────────────────

def _win_aes_gcm_encrypt(key: bytes, nonce: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    try:
        return _bcrypt_aes_gcm(key, nonce, plaintext, encrypt=True)
    except Exception as e:
        raise EncryptionError(
            f'AES-GCM unavailable ({e}). Install cryptography: pip install cryptography'
        ) from e


def _win_aes_gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
    try:
        out, _ = _bcrypt_aes_gcm(key, nonce, ciphertext, encrypt=False, tag=tag)
        return out
    except EncryptionError:
        raise
    except Exception as e:
        raise EncryptionError(f'Decrypt failed: {e}') from e


def _bcrypt_aes_gcm(
    key: bytes,
    nonce: bytes,
    data: bytes,
    encrypt: bool = True,
    tag: Optional[bytes] = None,
) -> tuple[bytes, bytes]:
    """AES-256-GCM via Windows bcrypt.dll."""
    import ctypes
    from ctypes import wintypes

    bcrypt = ctypes.windll.bcrypt
    BCRYPT_ALG_HANDLE = wintypes.HANDLE
    BCRYPT_KEY_HANDLE = wintypes.HANDLE
    STATUS_SUCCESS = 0

    class BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.ULONG),
            ('dwInfoVersion', wintypes.ULONG),
            ('pbNonce', ctypes.POINTER(ctypes.c_ubyte)),
            ('cbNonce', wintypes.ULONG),
            ('pbAuthData', ctypes.POINTER(ctypes.c_ubyte)),
            ('cbAuthData', wintypes.ULONG),
            ('pbTag', ctypes.POINTER(ctypes.c_ubyte)),
            ('cbTag', wintypes.ULONG),
            ('pbMacContext', ctypes.POINTER(ctypes.c_ubyte)),
            ('cbMacContext', wintypes.ULONG),
            ('cbAAD', wintypes.ULONG),
            ('cbData', ctypes.c_uint64),
            ('dwFlags', wintypes.ULONG),
        ]

    alg = BCRYPT_ALG_HANDLE()
    status = bcrypt.BCryptOpenAlgorithmProvider(
        ctypes.byref(alg), 'AES', None, 0)
    if status != STATUS_SUCCESS:
        raise EncryptionError(f'BCryptOpenAlgorithmProvider failed: {status}')

    try:
        gcm = ctypes.create_unicode_buffer('ChainingModeGCM')
        status = bcrypt.BCryptSetProperty(
            alg, 'ChainingMode', gcm, ctypes.sizeof(gcm), 0)
        if status != STATUS_SUCCESS:
            raise EncryptionError(f'Set GCM mode failed: {status}')

        key_handle = BCRYPT_KEY_HANDLE()
        key_buf = (ctypes.c_ubyte * len(key)).from_buffer_copy(key)
        status = bcrypt.BCryptGenerateSymmetricKey(
            alg, ctypes.byref(key_handle), None, 0, key_buf, len(key), 0)
        if status != STATUS_SUCCESS:
            raise EncryptionError(f'GenerateSymmetricKey failed: {status}')

        try:
            tag_buf = (ctypes.c_ubyte * TAG_LEN)()
            if not encrypt and tag:
                ctypes.memmove(tag_buf, tag, TAG_LEN)
            nonce_buf = (ctypes.c_ubyte * len(nonce)).from_buffer_copy(nonce)

            info = BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO()
            info.cbSize = ctypes.sizeof(BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO)
            info.dwInfoVersion = 1
            info.pbNonce = ctypes.cast(nonce_buf, ctypes.POINTER(ctypes.c_ubyte))
            info.cbNonce = len(nonce)
            info.pbTag = ctypes.cast(tag_buf, ctypes.POINTER(ctypes.c_ubyte))
            info.cbTag = TAG_LEN

            in_buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data) if data else None
            out_len = wintypes.ULONG(0)
            out_buf = (ctypes.c_ubyte * len(data))() if data else None

            if encrypt:
                status = bcrypt.BCryptEncrypt(
                    key_handle,
                    in_buf, len(data) if data else 0,
                    ctypes.byref(info),
                    None, 0,
                    out_buf, len(data) if data else 0,
                    ctypes.byref(out_len), 0)
            else:
                status = bcrypt.BCryptDecrypt(
                    key_handle,
                    in_buf, len(data) if data else 0,
                    ctypes.byref(info),
                    None, 0,
                    out_buf, len(data) if data else 0,
                    ctypes.byref(out_len), 0)
            if status != STATUS_SUCCESS:
                raise EncryptionError(f'BCrypt cipher failed: 0x{status:08X}')

            result = bytes(out_buf[:out_len.value]) if out_buf else b''
            return result, bytes(tag_buf)
        finally:
            bcrypt.BCryptDestroyKey(key_handle)
    finally:
        bcrypt.BCryptCloseAlgorithmProvider(alg, 0)


def fingerprint_key(key: bytes) -> str:
    return hmac.new(b'mbt-fp', key, hashlib.sha256).hexdigest()[:16]
