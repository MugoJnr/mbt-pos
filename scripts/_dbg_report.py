import sys
from datetime import date, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sqlite3
from mbt_paths import get_db_path
from desktop.utils.api_client import APIClient, _sale_day_expr

db = sqlite3.connect(get_db_path())
db.row_factory = sqlite3.Row
rows = db.execute("SELECT id, total, status, created_at, sale_date FROM sales LIMIT 8").fetchall()
print("sales sample", [dict(r) for r in rows])
expr = _sale_day_expr()
end = date.today().isoformat()
start = (date.today() - timedelta(days=30)).isoformat()
q = f"SELECT COUNT(*), SUM(total) FROM sales WHERE {expr} BETWEEN ? AND ? AND status IN ('completed','return')"
print("q count", db.execute(q, (start, end)).fetchone())
os.environ.setdefault("MBT_QA_ALLOW_DEV_BOOTSTRAP", "1")
from _qa_local_auth import qa_admin_password, qa_admin_user, qa_login
print("summary", api.get_report_summary(start, end))
