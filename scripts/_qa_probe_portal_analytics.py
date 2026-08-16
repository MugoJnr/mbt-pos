#!/usr/bin/env python3
"""Probe portal analytics for testshop with user JWT."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests
from _e2e_env import require_e2e_testshop

EMAIL, PASSWORD = require_e2e_testshop()
ORG = "7951b8db-ec5a-4db5-a820-fe73a2d47ec8"


def main() -> int:
    r = requests.post(
        "https://portal.mugobyte.com/api/cloud/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    print("login", r.status_code)
    data = r.json()
    token = data.get("token") or ""
    print("orgs", data.get("organizations"))
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)
    qs = {
        "org_id": ORG,
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
    }
    for path in [
        "/api/cloud/v1/analytics/overview",
        "/api/cloud/analytics/overview",
        "/api/cloud/v1/reports/overview",
        "/api/platform/analytics/overview",
    ]:
        try:
            rr = requests.get(
                f"https://portal.mugobyte.com{path}",
                headers=H,
                params=qs,
                timeout=30,
            )
            print(path, rr.status_code, rr.text[:500])
        except Exception as e:
            print(path, e)

    # service-role local probe of what overview should return
    cfg = json.loads(
        (
            Path(os.environ["LOCALAPPDATA"])
            / "MugoByte"
            / "MBT POS"
            / "config"
            / "cloud_config.json"
        ).read_text(encoding="utf-8")
    )
    url = cfg["supabase_url"].rstrip("/")
    key = cfg["service_key"]
    SH = {"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "count=exact"}
    sr = requests.get(
        f"{url}/rest/v1/cloud_sales?org_id=eq.{ORG}&select=id&limit=1",
        headers=SH,
        timeout=30,
    )
    print("svc_sales", sr.status_code, sr.headers.get("content-range"), sr.text[:120])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
