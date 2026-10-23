"""Shop-local till sign-ins, web sessions, and shared PIN attempt limits."""
from __future__ import annotations

import secrets
import time
from datetime import datetime

_PIN_WINDOW_SECONDS = 600
_PIN_MAX_FAILURES = 8


def ensure(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS till_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            role TEXT,
            started_at TEXT,
            ended_at TEXT,
            end_requested INTEGER DEFAULT 0,
            state TEXT DEFAULT 'signed_in'
        );
        CREATE TABLE IF NOT EXISTS web_sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            role TEXT,
            ip TEXT,
            created_at TEXT,
            revoked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS pin_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key TEXT NOT NULL,
            attempted_at REAL NOT NULL
        );
        """
    )


def open_till_session(conn, user: dict) -> int:
    ensure(conn)
    now = datetime.now().isoformat(timespec='seconds')
    conn.execute(
        "INSERT INTO till_sessions (user_id, username, full_name, role, started_at, state) "
        "VALUES (?,?,?,?,?, 'signed_in')",
        (
            user.get('id'),
            user.get('username') or '',
            user.get('full_name') or '',
            user.get('role') or '',
            now,
        ),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def list_till_sessions(conn) -> list[dict]:
    ensure(conn)
    rows = conn.execute(
        "SELECT * FROM till_sessions WHERE ended_at IS NULL OR state='pending' "
        "ORDER BY id DESC LIMIT 50"
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        if int(item.get('end_requested') or 0) and item.get('state') != 'signed_out':
            item['state'] = 'pending'
        out.append(item)
    return out


def request_till_end(conn, session_id: int) -> dict:
    ensure(conn)
    row = conn.execute(
        "SELECT * FROM till_sessions WHERE id=?", (int(session_id),)
    ).fetchone()
    if not row:
        return {'error': 'Till sign-in was not found.'}
    if row['state'] == 'signed_out' or row['ended_at']:
        return {'success': True, 'duplicate': True, 'state': 'signed_out'}
    conn.execute(
        "UPDATE till_sessions SET end_requested=1, state='pending' WHERE id=? AND ended_at IS NULL",
        (int(session_id),),
    )
    return {'success': True, 'state': 'pending'}


def take_till_end(conn, session_id: int) -> bool:
    """Return True once when the dashboard has asked this till to sign out."""
    if not session_id:
        return False
    ensure(conn)
    row = conn.execute(
        "SELECT end_requested, state FROM till_sessions WHERE id=?",
        (int(session_id),),
    ).fetchone()
    if not row or int(row['end_requested'] or 0) != 1 or row['state'] == 'signed_out':
        return False
    now = datetime.now().isoformat(timespec='seconds')
    changed = conn.execute(
        "UPDATE till_sessions SET state='signed_out', ended_at=? "
        "WHERE id=? AND state!='signed_out'",
        (now, int(session_id)),
    )
    return changed.rowcount == 1


def open_web_session(conn, user: dict, ip: str = '') -> str:
    ensure(conn)
    sid = secrets.token_hex(16)
    conn.execute(
        "INSERT INTO web_sessions (id, user_id, username, full_name, role, ip, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            sid,
            user.get('id'),
            user.get('username') or '',
            user.get('full_name') or '',
            user.get('role') or '',
            ip or '',
            datetime.now().isoformat(timespec='seconds'),
        ),
    )
    return sid


def web_session_active(conn, sid: str) -> bool:
    if not sid:
        return True
    ensure(conn)
    row = conn.execute(
        "SELECT revoked_at FROM web_sessions WHERE id=?", (sid,)
    ).fetchone()
    if not row:
        return False
    return not row['revoked_at']


def list_web_sessions(conn) -> list[dict]:
    ensure(conn)
    rows = conn.execute(
        "SELECT id, user_id, username, full_name, role, ip, created_at "
        "FROM web_sessions WHERE revoked_at IS NULL ORDER BY created_at DESC LIMIT 100"
    ).fetchall()
    return [dict(row) for row in rows]


def revoke_web_session(conn, sid: str) -> dict:
    ensure(conn)
    row = conn.execute(
        "SELECT revoked_at FROM web_sessions WHERE id=?", (sid,)
    ).fetchone()
    if not row:
        return {'error': 'Session was not found.'}
    if row['revoked_at']:
        return {'success': True, 'duplicate': True}
    conn.execute(
        "UPDATE web_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
        (datetime.now().isoformat(timespec='seconds'), sid),
    )
    return {'success': True}


def revoke_other_web_sessions(conn, user_id, keep_sid: str = '') -> None:
    ensure(conn)
    conn.execute(
        "UPDATE web_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL AND id!=?",
        (datetime.now().isoformat(timespec='seconds'), user_id, keep_sid or ''),
    )


def pin_blocked(user_id) -> tuple[bool, int]:
    from desktop.utils.api_client import _db
    now = time.time()
    key = str(user_id or 0)
    db = _db()
    try:
        ensure(db)
        cutoff = now - _PIN_WINDOW_SECONDS
        db.execute("DELETE FROM pin_attempts WHERE attempted_at < ?", (cutoff,))
        rows = db.execute(
            "SELECT attempted_at FROM pin_attempts WHERE user_key=? ORDER BY attempted_at",
            (key,),
        ).fetchall()
        db.commit()
        if len(rows) >= _PIN_MAX_FAILURES:
            retry_after = max(1, int(_PIN_WINDOW_SECONDS - (now - float(rows[0]['attempted_at']))))
            return True, retry_after
        return False, 0
    finally:
        db.close()


def pin_record(user_id) -> None:
    from desktop.utils.api_client import _db
    db = _db()
    try:
        ensure(db)
        now = time.time()
        cutoff = now - _PIN_WINDOW_SECONDS
        key = str(user_id or 0)
        db.execute("DELETE FROM pin_attempts WHERE attempted_at < ?", (cutoff,))
        db.execute(
            "INSERT INTO pin_attempts (user_key, attempted_at) VALUES (?,?)",
            (key, now),
        )
        db.commit()
    finally:
        db.close()


def pin_clear(user_id) -> None:
    from desktop.utils.api_client import _db
    db = _db()
    try:
        ensure(db)
        db.execute("DELETE FROM pin_attempts WHERE user_key=?", (str(user_id or 0),))
        db.commit()
    finally:
        db.close()
