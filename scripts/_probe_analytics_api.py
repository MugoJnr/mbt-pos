# -*- coding: utf-8 -*-
"""Probe analytics_overview locally with service role for known orgs."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Ensure local cloud_config is used
os.environ.setdefault("MBT_DATA_ROOT", str(Path(os.environ["LOCALAPPDATA"]) / "MugoByte" / "MBT POS"))

EDMUS = "99a8b1d9-2210-4b7e-9922-28db987bc7b9"
TESTSHOP = "7951b8db-ec5a-4db5-a820-fe73a2d47ec8"


def main() -> int:
    from backend.cloud.platform_service import (
        analytics_overview,
        analytics_list_sales,
        has_service_role,
        analytics_day_bounds,
    )
    from backend.cloud_backup.paths import load_cloud_config

    cfg = load_cloud_config()
    print("configured_url", cfg.get("supabase_url"))
    print("has_service_role", has_service_role())
    print("today_bounds", analytics_day_bounds("2026-07-22", "2026-07-22"))
    print("june_bounds", analytics_day_bounds("2026-06-01", "2026-07-22"))

    for label, oid in [("EDMUS", EDMUS), ("testshop", TESTSHOP)]:
        try:
            ov = analytics_overview(oid, start="2026-07-22", end="2026-07-22")
            summary = ov.get("summary") or ov.get("kpis") or {}
            print(
                f"{label} today: txns={summary.get('transactions')} "
                f"gross={summary.get('gross_sales')} "
                f"keys={list(ov.keys())[:12]}"
            )
            print("  summary_sample", {k: summary.get(k) for k in list(summary)[:12]})
        except Exception as e:
            print(f"{label} today FAILED: {type(e).__name__}: {e}")

        try:
            ov = analytics_overview(oid, start="2026-06-01", end="2026-07-22")
            summary = ov.get("summary") or ov.get("kpis") or {}
            print(
                f"{label} range: txns={summary.get('transactions')} "
                f"gross={summary.get('gross_sales')} last_sync={ov.get('last_sync_at')}"
            )
        except Exception as e:
            print(f"{label} range FAILED: {type(e).__name__}: {e}")

        try:
            sales = analytics_list_sales(oid, start="2026-07-22", end="2026-07-22", page=1, page_size=3)
            print(f"{label} sales_today total={sales.get('total')} n={len(sales.get('sales') or [])}")
            if sales.get("sales"):
                print("  first", sales["sales"][0].get("receipt_number"), sales["sales"][0].get("total"))
        except Exception as e:
            print(f"{label} list_sales FAILED: {type(e).__name__}: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
