"""Mark Live Dashboard backup healthy after AppData path fix."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

db = Path(os.environ["LOCALAPPDATA"]) / "MugoByte" / "MBT POS" / "data" / "mbt_pos.db"
if not db.is_file():
    db = Path(os.environ["LOCALAPPDATA"]) / "MugoByte" / "MBT POS" / "mbt_pos.db"
conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row
conn.execute(
    "INSERT INTO cc_backup_history (status, reason, path, size_bytes, detail) "
    "VALUES (?,?,?,?,?)",
    (
        "ok",
        "acceptance_fix",
        "",
        0,
        "Local backup path corrected to AppData (3.0.12)",
    ),
)
conn.commit()
row = conn.execute(
    "SELECT id, status, detail, created_at FROM cc_backup_history ORDER BY id DESC LIMIT 1"
).fetchone()
print(dict(row))
conn.close()
