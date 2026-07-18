"""Knowledge base + ops audit events (local SQLite)."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from mbt_paths import get_data_dir, configure_sqlite_connection

log = logging.getLogger('ai.ops.knowledge')


def _db() -> sqlite3.Connection:
    path = os.path.join(get_data_dir(), 'ai_ops.db')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path, timeout=15)
    c.row_factory = sqlite3.Row
    configure_sqlite_connection(c)
    c.executescript(
        '''
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            symptoms TEXT,
            resolution TEXT,
            tags TEXT,
            created_at REAL,
            updated_at REAL,
            created_by TEXT
        );
        CREATE TABLE IF NOT EXISTS ops_events (
            id TEXT PRIMARY KEY,
            ts REAL,
            kind TEXT,
            title TEXT,
            detail TEXT,
            user_id TEXT,
            username TEXT,
            meta_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_kb_title ON knowledge_base(title);
        CREATE INDEX IF NOT EXISTS idx_ops_ts ON ops_events(ts DESC);
        '''
    )
    c.commit()
    return c


def log_ops_event(
    *,
    kind: str,
    title: str,
    detail: str = '',
    user_id: str = '',
    username: str = '',
    meta: Optional[dict] = None,
) -> str:
    eid = str(uuid.uuid4())
    try:
        with _db() as c:
            c.execute(
                'INSERT INTO ops_events(id,ts,kind,title,detail,user_id,username,meta_json) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (eid, time.time(), kind, title[:200], (detail or '')[:2000],
                 user_id, username, json.dumps(meta or {})),
            )
            c.commit()
    except Exception as e:
        log.debug('ops event: %s', e)
    return eid


def add_knowledge(
    title: str,
    symptoms: str,
    resolution: str,
    *,
    tags: str = '',
    created_by: str = '',
) -> str:
    kid = str(uuid.uuid4())
    now = time.time()
    with _db() as c:
        c.execute(
            'INSERT INTO knowledge_base(id,title,symptoms,resolution,tags,created_at,updated_at,created_by) '
            'VALUES(?,?,?,?,?,?,?,?)',
            (kid, title[:200], symptoms or '', resolution or '', tags or '', now, now, created_by),
        )
        c.commit()
    return kid


def list_knowledge(search: str = '', limit: int = 50) -> List[Dict[str, Any]]:
    q = 'SELECT * FROM knowledge_base'
    args: list = []
    if search.strip():
        q += ' WHERE title LIKE ? OR symptoms LIKE ? OR resolution LIKE ? OR tags LIKE ?'
        like = f'%{search.strip()}%'
        args = [like, like, like, like]
    q += ' ORDER BY updated_at DESC LIMIT ?'
    args.append(limit)
    with _db() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def delete_knowledge(kid: str) -> bool:
    with _db() as c:
        cur = c.execute('DELETE FROM knowledge_base WHERE id=?', (kid,))
        c.commit()
        return cur.rowcount > 0


def recent_events(limit: int = 40) -> List[Dict[str, Any]]:
    with _db() as c:
        return [dict(r) for r in c.execute(
            'SELECT * FROM ops_events ORDER BY ts DESC LIMIT ?', (limit,)
        ).fetchall()]
