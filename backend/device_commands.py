"""Commands the dashboard asks the till to run on this computer.

A command stays pending until the till claims it. Nothing here reports a
print as finished paper. The till may only report that a test page was queued
or that queueing failed.
"""
from __future__ import annotations

from datetime import datetime

ALLOWED = frozenset({'print_test'})
RESULTS = frozenset({'queued', 'failed'})


def ensure_schema(db) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS device_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command TEXT NOT NULL,
            status TEXT NOT NULL,
            requested_by TEXT,
            result TEXT,
            detail TEXT,
            created_at TEXT,
            updated_at TEXT
        )"""
    )


def enqueue(db, command: str, username: str = '') -> dict:
    ensure_schema(db)
    name = str(command or '').strip()
    if name not in ALLOWED:
        raise ValueError('That device action is not available.')
    now = _now()
    cursor = db.execute(
        "INSERT INTO device_commands (command, status, requested_by, result, detail, created_at, updated_at) "
        "VALUES (?, 'pending', ?, '', '', ?, ?)",
        (name, username or '', now, now),
    )
    db.commit()
    return get_command(db, int(cursor.lastrowid))


def get_command(db, command_id: int) -> dict | None:
    ensure_schema(db)
    row = db.execute(
        "SELECT id, command, status, requested_by, result, detail, created_at, updated_at "
        "FROM device_commands WHERE id=?",
        (int(command_id),),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def claim_next_print_test(db, username: str = '') -> dict | None:
    ensure_schema(db)
    row = db.execute(
        "SELECT id FROM device_commands WHERE command='print_test' AND status='pending' "
        "ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    command_id = int(row['id'] if hasattr(row, 'keys') else row[0])
    cursor = db.execute(
        "UPDATE device_commands SET status='running', updated_at=?, requested_by=COALESCE(NULLIF(requested_by,''), ?) "
        "WHERE id=? AND status='pending'",
        (_now(), username or '', command_id),
    )
    if cursor.rowcount != 1:
        db.rollback()
        return None
    db.commit()
    return get_command(db, command_id)


def finish(db, command_id: int, result: str, detail: str = '') -> dict | None:
    ensure_schema(db)
    outcome = str(result or '').strip()
    if outcome not in RESULTS:
        raise ValueError('The till must report queued or failed.')
    safe_detail = str(detail or '')[:240]
    cursor = db.execute(
        "UPDATE device_commands SET status=?, result=?, detail=?, updated_at=? "
        "WHERE id=? AND status='running'",
        ('completed' if outcome == 'queued' else 'failed', outcome, safe_detail, _now(), int(command_id)),
    )
    if cursor.rowcount != 1:
        db.rollback()
        return None
    db.commit()
    return get_command(db, int(command_id))


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')
