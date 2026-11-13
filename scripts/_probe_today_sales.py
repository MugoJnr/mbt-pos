# -*- coding: utf-8 -*-
"""Count EDMUS/testshop sales for today vs all-time via REST."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

EDMUS = "99a8b1d9-2210-4b7e-9922-28db987bc7b9"
TESTSHOP = "7951b8db-ec5a-4db5-a820-fe73a2d47ec8"

try:
    NAIROBI = ZoneInfo("Africa/Nairobi")
except Exception:
    NAIROBI = timezone(timedelta(hours=3))


def main() -> None:
    cfg = json.loads(
        (Path(os.environ["LOCALAPPDATA"]) / "MugoByte" / "MBT POS" / "config" / "cloud_config.json").read_text(
            encoding="utf-8"
        )
    )
    url = cfg["supabase_url"].rstrip("/")
    key = cfg["service_key"]
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Prefer": "count=exact",
    }
    today = datetime.now(NAIROBI).date()
    start_local = datetime(today.year, today.month, today.day, tzinfo=NAIROBI)
    end_local = start_local + timedelta(days=1)
    start_iso = start_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end_iso = end_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    print("today", today.isoformat(), "bounds", start_iso, end_iso)

    for name, oid in [("EDMUS", EDMUS), ("testshop", TESTSHOP)]:
        q = (
            f"org_id=eq.{quote(oid)}&source_created_at=gte.{quote(start_iso, safe=':')}"
            f"&source_created_at=lt.{quote(end_iso, safe=':')}&select=id&limit=1"
        )
        r = requests.get(f"{url}/rest/v1/cloud_sales?{q}", headers=headers, timeout=60)
        cr = r.headers.get("content-range", "")
        print(f"{name} today_sales status={r.status_code} range={cr}")

        # last 30 days
        start30 = (start_local - timedelta(days=30)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        q30 = (
            f"org_id=eq.{quote(oid)}&source_created_at=gte.{quote(start30, safe=':')}"
            f"&source_created_at=lt.{quote(end_iso, safe=':')}&select=id&limit=1"
        )
        r = requests.get(f"{url}/rest/v1/cloud_sales?{q30}", headers=headers, timeout=60)
        print(f"{name} last30 status={r.status_code} range={r.headers.get('content-range')}")

        # sample today rows
        q2 = (
            f"org_id=eq.{quote(oid)}&source_created_at=gte.{quote(start_iso, safe=':')}"
            f"&source_created_at=lt.{quote(end_iso, safe=':')}"
            f"&select=receipt_number,total,source_created_at&order=source_created_at.desc&limit=3"
        )
        r = requests.get(
            f"{url}/rest/v1/cloud_sales?{q2}",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=60,
        )
        print(f"{name} today_sample", r.status_code, r.text[:400])


if __name__ == "__main__":
    main()
