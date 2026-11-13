import json, os, sqlite3, urllib.request
from pathlib import Path

db = Path(os.environ["LOCALAPPDATA"]) / "MugoByte" / "MBT POS" / "data" / "mbt_pos.db"
con = sqlite3.connect(str(db))
con.row_factory = sqlite3.Row
bak = con.execute(
    "SELECT status, created_at FROM cc_backup_history ORDER BY id DESC LIMIT 1"
).fetchone()
print("tip_backup", dict(bak) if bak else None)
print(
    "remote_health",
    urllib.request.urlopen("https://testshop.mugobyte.com/api/health", timeout=10)
    .read()
    .decode(),
)
