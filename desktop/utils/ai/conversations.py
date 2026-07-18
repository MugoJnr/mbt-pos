"""Per-user AI conversation store (local SQLite)."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from mbt_paths import get_data_dir, configure_sqlite_connection

log = logging.getLogger('ai.conversations')


def _db_path() -> str:
    d = get_data_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'ai_conversations.db')


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path(), timeout=15)
    c.row_factory = sqlite3.Row
    configure_sqlite_connection(c)
    c.executescript(
        '''
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT 'New chat',
            module TEXT DEFAULT 'dashboard',
            pinned INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL,
            meta_json TEXT DEFAULT '{}',
            FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, created_at);
        '''
    )
    c.commit()
    return c


class ConversationStore:
    def create(self, user_id: str, title: str = 'New chat', module: str = 'dashboard') -> str:
        cid = str(uuid.uuid4())
        now = time.time()
        with _conn() as c:
            c.execute(
                'INSERT INTO conversations(id,user_id,title,module,pinned,created_at,updated_at) '
                'VALUES(?,?,?,?,0,?,?)',
                (cid, str(user_id), title or 'New chat', module or 'dashboard', now, now),
            )
            c.commit()
        return cid

    def list(self, user_id: str, search: str = '') -> List[Dict[str, Any]]:
        q = '''SELECT * FROM conversations WHERE user_id=?'''
        args: list = [str(user_id)]
        if search.strip():
            q += ' AND (title LIKE ? OR id IN (SELECT conversation_id FROM messages WHERE content LIKE ?))'
            like = f'%{search.strip()}%'
            args.extend([like, like])
        q += ' ORDER BY pinned DESC, updated_at DESC LIMIT 100'
        with _conn() as c:
            return [dict(r) for r in c.execute(q, args).fetchall()]

    def rename(self, conversation_id: str, user_id: str, title: str) -> bool:
        with _conn() as c:
            cur = c.execute(
                'UPDATE conversations SET title=?, updated_at=? WHERE id=? AND user_id=?',
                (title[:120], time.time(), conversation_id, str(user_id)),
            )
            c.commit()
            return cur.rowcount > 0

    def pin(self, conversation_id: str, user_id: str, pinned: bool = True) -> bool:
        with _conn() as c:
            cur = c.execute(
                'UPDATE conversations SET pinned=?, updated_at=? WHERE id=? AND user_id=?',
                (1 if pinned else 0, time.time(), conversation_id, str(user_id)),
            )
            c.commit()
            return cur.rowcount > 0

    def delete(self, conversation_id: str, user_id: str) -> bool:
        with _conn() as c:
            c.execute('DELETE FROM messages WHERE conversation_id=?', (conversation_id,))
            cur = c.execute(
                'DELETE FROM conversations WHERE id=? AND user_id=?',
                (conversation_id, str(user_id)),
            )
            c.commit()
            return cur.rowcount > 0

    def add_message(
        self, conversation_id: str, role: str, content: str, meta: Optional[dict] = None
    ) -> str:
        mid = str(uuid.uuid4())
        now = time.time()
        with _conn() as c:
            c.execute(
                'INSERT INTO messages(id,conversation_id,role,content,created_at,meta_json) '
                'VALUES(?,?,?,?,?,?)',
                (mid, conversation_id, role, content, now, json.dumps(meta or {})),
            )
            c.execute(
                'UPDATE conversations SET updated_at=? WHERE id=?',
                (now, conversation_id),
            )
            # Auto-title from first user message
            row = c.execute(
                'SELECT title FROM conversations WHERE id=?', (conversation_id,)
            ).fetchone()
            if row and (row['title'] in ('New chat', '', None)) and role == 'user':
                t = (content or '').strip().replace('\n', ' ')[:48]
                if t:
                    c.execute(
                        'UPDATE conversations SET title=? WHERE id=?',
                        (t + ('…' if len(content) > 48 else ''), conversation_id),
                    )
            c.commit()
        return mid

    def messages(self, conversation_id: str, limit: int = 80) -> List[Dict[str, Any]]:
        with _conn() as c:
            rows = c.execute(
                'SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC LIMIT ?',
                (conversation_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]


_STORE: Optional[ConversationStore] = None


def get_conversation_store() -> ConversationStore:
    global _STORE
    if _STORE is None:
        _STORE = ConversationStore()
    return _STORE
