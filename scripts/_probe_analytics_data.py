# -*- coding: utf-8 -*-
"""One-shot: probe Supabase analytics tables via local service role."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests

EDMUS = "99a8b1d9-2210-4b7e-9922-28db987bc7b9"


def main() -> int:
    cfg_path = Path(os.environ["LOCALAPPDATA"]) / "MugoByte" / "MBT POS" / "config" / "cloud_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    url = cfg["supabase_url"].rstrip("/")
    key = (cfg.get("service_key") or cfg.get("service_role") or "").strip()
    if not key:
        print("NO_SERVICE_KEY")
        return 1
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "count=exact",
    }
    print("service_key_len", len(key))
    print("url", url)

    def count(table: str, q: str = "") -> tuple[int, int | None, str]:
        base = f"{url}/rest/v1/{table}?{q}" if q else f"{url}/rest/v1/{table}?select=id"
        r = requests.get(base, headers=headers, timeout=60)
        cr = r.headers.get("content-range", "")
        total = None
        if "/" in cr:
            try:
                total = int(cr.split("/")[-1])
            except ValueError:
                total = None
        err = r.text[:240] if r.status_code >= 400 else ""
        return r.status_code, total, err

    for table in [
        "cloud_sales",
        "cloud_sale_items",
        "cloud_debt_invoices",
        "cloud_debt_payments",
        "cloud_products",
        "cloud_stock_movements",
        "sync_entities",
        "sync_batches",
        "devices",
        "organizations",
    ]:
        st, tot, err = count(table, "select=id&limit=1")
        print(f"{table}: status={st} total={tot} {err}")

    orgs = requests.get(
        f"{url}/rest/v1/organizations?select=id,name&order=name.asc",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=60,
    )
    print("orgs_status", orgs.status_code)
    org_rows = orgs.json() if orgs.ok else []
    print("org_count", len(org_rows))
    for o in org_rows[:40]:
        oid = o["id"]
        name = o.get("name")
        _, sales, _ = count("cloud_sales", f"org_id=eq.{quote(oid)}&select=id&limit=1")
        _, devices, _ = count("devices", f"org_id=eq.{quote(oid)}&select=id&limit=1")
        _, batches, _ = count("sync_batches", f"org_id=eq.{quote(oid)}&select=id&limit=1")
        _, entities, _ = count("sync_entities", f"org_id=eq.{quote(oid)}&select=id&limit=1")
        print(
            f"ORG {name!r} {oid}: sales={sales} devices={devices} "
            f"sync_batches={batches} sync_entities={entities}"
        )

    print("--- EDMUS detail ---")
    for table in [
        "cloud_sales",
        "cloud_sale_items",
        "cloud_debt_invoices",
        "cloud_products",
        "sync_entities",
        "sync_batches",
    ]:
        st, tot, err = count(table, f"org_id=eq.{quote(EDMUS)}&select=id&limit=1")
        print(f"EDMUS {table}: status={st} total={tot} {err}")

    soft = {"apikey": key, "Authorization": f"Bearer {key}"}
    r = requests.get(
        f"{url}/rest/v1/cloud_sales?select=org_id,source_created_at,total,receipt_number,synced_at"
        f"&order=synced_at.desc.nullslast&limit=5",
        headers=soft,
        timeout=60,
    )
    print("sample_sales", r.status_code, r.text[:900])

    r = requests.get(
        f"{url}/rest/v1/devices?org_id=eq.{quote(EDMUS)}"
        f"&select=id,device_id,computer_name,last_sync_at,status,mbt_version",
        headers=soft,
        timeout=60,
    )
    print("edmus_devices", r.status_code, r.text[:1200])

    r = requests.get(
        f"{url}/rest/v1/sync_entities?select=entity_type,org_id,source_id,created_at"
        f"&order=created_at.desc&limit=10",
        headers=soft,
        timeout=60,
    )
    print("sync_entities_sample", r.status_code, r.text[:1200])

    # Date span of any cloud_sales
    r = requests.get(
        f"{url}/rest/v1/cloud_sales?select=source_created_at&order=source_created_at.asc&limit=1",
        headers=soft,
        timeout=60,
    )
    print("oldest_sale", r.status_code, r.text[:300])
    r = requests.get(
        f"{url}/rest/v1/cloud_sales?select=source_created_at&order=source_created_at.desc&limit=1",
        headers=soft,
        timeout=60,
    )
    print("newest_sale", r.status_code, r.text[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
