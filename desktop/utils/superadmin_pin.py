"""One PIN per Super Admin account.

The hash is salted per person. The PIN is never stored or written to the audit log.
Five wrong attempts lock that account for fifteen minutes. A successful check
authorises only the action the caller presents. It does not change the cashier's role.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta


def ensure_pin_columns(db) -> None:
    cols = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    if "pin_hash" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN pin_hash TEXT")
    if "pin_salt" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN pin_salt TEXT")
    if "pin_fails" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN pin_fails INTEGER DEFAULT 0")
    if "pin_locked_until" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN pin_locked_until TEXT")


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()


def set_superadmin_user_pin(db, user_id: int, pin: str) -> dict:
    ensure_pin_columns(db)
    pin = str(pin or "").strip()
    if not pin.isdigit() or not 6 <= len(pin) <= 8:
        return {"error": "Use a 6 to 8 digit PIN."}
    row = db.execute(
        "SELECT id, role FROM users WHERE id=? AND COALESCE(is_active,1)=1",
        (int(user_id),),
    ).fetchone()
    if not row or str(row[1] or "").lower() != "superadmin":
        return {"error": "Only a Super Admin can set their own PIN."}
    salt = os.urandom(16).hex()
    db.execute(
        "UPDATE users SET pin_hash=?, pin_salt=?, pin_fails=0, pin_locked_until=NULL WHERE id=?",
        (_hash(pin, salt), salt, int(user_id)),
    )
    return {"success": True, "user_id": int(user_id)}


def gate_personal_pin(db, pin: str, username: str) -> dict | None:
    """None when this Super Admin's own PIN is accepted.

    The old shop-wide PIN is not an approval credential.
    """
    result = verify_superadmin_user_pin(db, username, pin or "")
    if result.get("success"):
        return None
    return {
        "error": result.get("error") or "That Super Admin PIN was not accepted.",
        "status": 429 if result.get("locked") else 403,
        "authoriser_id": result.get("authoriser_id"),
        "authoriser_username": result.get("authoriser_username") or username,
    }


def _unnamed_shop_pin(db, pin: str) -> dict:
    """A PIN with no username matches the shop PIN only while nobody has their own."""
    ensure_pin_columns(db)
    personal = db.execute(
        "SELECT id FROM users WHERE lower(role)='superadmin' AND COALESCE(is_active,1)=1 "
        "AND COALESCE(pin_hash,'') != '' LIMIT 1"
    ).fetchone()
    if personal:
        return {"error": "That Super Admin PIN was not accepted."}
    owner = db.execute(
        "SELECT id, username, full_name FROM users "
        "WHERE lower(role)='superadmin' AND COALESCE(is_active,1)=1 "
        "ORDER BY id LIMIT 1"
    ).fetchone()
    if not owner:
        return {"error": "That Super Admin PIN was not accepted."}
    return _shop_pin_fallback(db, pin, (owner[0], owner[1], owner[2]))


def _shop_pin_fallback(db, pin: str, row) -> dict:
    """Accept the legacy shop PIN only until this Super Admin sets their own."""
    try:
        from desktop.utils.security import _pin_hash
        stored = db.execute(
            "SELECT value FROM system_settings WHERE key='superadmin_pin_hash'"
        ).fetchone()
    except Exception:
        stored = None
    value = ""
    if stored is not None:
        value = stored["value"] if hasattr(stored, "keys") else stored[0]
    if value and _pin_hash(str(pin or "")) == str(value):
        return {
            "success": True,
            "authoriser_id": int(row[0]),
            "authoriser_username": row[1],
            "authoriser_name": row[2] or row[1],
            "legacy_shop_pin": True,
        }
    return {"error": "That Super Admin PIN was not accepted."}


def verify_superadmin_user_pin(db, username: str, pin: str) -> dict:
    """Check one Super Admin's PIN. The return value never includes the PIN or the hash."""
    ensure_pin_columns(db)
    name = str(username or "").strip()
    pin = str(pin or "")
    if not name:
        return _unnamed_shop_pin(db, pin)
    row = db.execute(
        "SELECT id, username, full_name, role, pin_hash, pin_salt, pin_fails, pin_locked_until "
        "FROM users WHERE lower(username)=lower(?) AND COALESCE(is_active,1)=1",
        (name,),
    ).fetchone()
    if not row or str(row[3] or "").lower() != "superadmin":
        return {"error": "That Super Admin PIN was not accepted."}
    if not row[4] or not row[5]:
        return _shop_pin_fallback(db, pin, row)
    locked = row[7]
    if locked:
        try:
            until = datetime.fromisoformat(str(locked))
        except ValueError:
            until = None
        if until and until > datetime.now():
            return {"error": "This PIN is locked. Try again later.", "locked": True}
    if _hash(pin, row[5]) != row[4]:
        fails = int(row[6] or 0) + 1
        until = None
        if fails >= 5:
            until = (datetime.now() + timedelta(minutes=15)).isoformat(timespec="seconds")
            fails = 0
        db.execute(
            "UPDATE users SET pin_fails=?, pin_locked_until=? WHERE id=?",
            (fails, until, row[0]),
        )
        if until:
            return {"error": "Too many wrong PINs. This account is locked for 15 minutes.", "locked": True}
        return {"error": "That Super Admin PIN was not accepted."}
    db.execute(
        "UPDATE users SET pin_fails=0, pin_locked_until=NULL WHERE id=?",
        (row[0],),
    )
    return {
        "success": True,
        "authoriser_id": int(row[0]),
        "authoriser_username": row[1],
        "authoriser_name": row[2] or row[1],
    }
