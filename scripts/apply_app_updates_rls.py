"""Apply app_updates public-read RLS to production Supabase.

Usage:
  set SUPABASE_DB_PASSWORD=...
  python scripts/apply_app_updates_rls.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260816120000_app_updates_public_read.sql"
PROJECT_REF = "uynfglgttkaibyeglsrt"


def main() -> int:
    password = os.environ.get("SUPABASE_DB_PASSWORD", "").strip()
    if not password:
        print("SUPABASE_DB_PASSWORD not set — cannot apply SQL migration.")
        print(f"Migration ready at: {MIGRATION}")
        return 1
    if not MIGRATION.is_file():
        print(f"Missing migration: {MIGRATION}")
        return 1
    sql = MIGRATION.read_text(encoding="utf-8")
    db_url = (
        f"postgresql://postgres.{PROJECT_REF}:{password}"
        f"@aws-0-eu-central-1.pooler.supabase.com:6543/postgres?sslmode=require"
    )
    try:
        import psycopg2
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary", "-q"])
        import psycopg2
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.close()
    print("Applied app_updates public-read RLS policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
