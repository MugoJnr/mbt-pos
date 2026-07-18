"""Local AI usage monitor (SQLite)."""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from mbt_paths import get_data_dir, configure_sqlite_connection

log = logging.getLogger('ai.usage')


def _db_path() -> str:
    d = get_data_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'ai_usage.db')


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path(), timeout=10)
    c.row_factory = sqlite3.Row
    configure_sqlite_connection(c)
    c.execute(
        '''CREATE TABLE IF NOT EXISTS ai_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            request_id TEXT,
            user_id TEXT,
            username TEXT,
            module TEXT,
            domain TEXT,
            model TEXT,
            provider TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            estimated_cost_usd REAL DEFAULT 0,
            success INTEGER DEFAULT 1,
            error TEXT
        )'''
    )
    c.commit()
    return c


def log_usage(
    *,
    request_id: str = '',
    user_id: str = '',
    username: str = '',
    module: str = '',
    domain: str = '',
    model: str = '',
    provider: str = 'openrouter',
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    latency_ms: int = 0,
    estimated_cost_usd: float = 0.0,
    success: bool = True,
    error: str = '',
) -> None:
    try:
        with _conn() as c:
            c.execute(
                '''INSERT INTO ai_usage(
                    ts, request_id, user_id, username, module, domain, model, provider,
                    prompt_tokens, completion_tokens, total_tokens, latency_ms,
                    estimated_cost_usd, success, error
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    time.time(), request_id, str(user_id or ''), username or '',
                    module or '', domain or '', model or '', provider,
                    int(prompt_tokens), int(completion_tokens), int(total_tokens),
                    int(latency_ms), float(estimated_cost_usd),
                    1 if success else 0, (error or '')[:500],
                ),
            )
            c.commit()
    except Exception as e:
        log.debug('usage log failed: %s', e)


def recent_usage(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        with _conn() as c:
            rows = c.execute(
                'SELECT * FROM ai_usage ORDER BY id DESC LIMIT ?', (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []
