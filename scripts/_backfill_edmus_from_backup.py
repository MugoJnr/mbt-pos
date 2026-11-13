# -*- coding: utf-8 -*-
"""Backfill EDMUS analytics from latest cloud backup (sales/sale_items/debts)."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

import requests

from backend.cloud_backup.encryption import derive_candidate_keys, decrypt_file, EncryptionError
from backend.cloud_backup.sync_manager import serialize_entity_payload, _payload_hash
from backend.cloud.platform_service import ingest_sync_batch, service_select

EDMUS_ORG = "99a8b1d9-2210-4b7e-9922-28db987bc7b9"
EDMUS_BIZ = "a5795322-4eae-4ed1-9b94-6a1a00c347ce"
EDMUS_OWNER = "c89a75aa-6c86-4357-afd3-e6b7aa20ae62"
DEVICE_CODE = "MBT-PC-52E5"
BATCH = 100
# Catch up everything after the cloud watermark (source_id 2200 / Jul 16).
MIN_SALE_ID = 2201


def _cfg():
    cfg = json.loads(
        (Path(os.environ["LOCALAPPDATA"]) / "MugoByte" / "MBT POS" / "config" / "cloud_config.json").read_text(
            encoding="utf-8"
        )
    )
    return cfg


def download_latest_backup(cfg: dict) -> Path:
    url = cfg["supabase_url"].rstrip("/")
    key = cfg["service_key"]
    bucket = cfg.get("bucket") or "mbt-backups"
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    r = requests.get(
        f"{url}/rest/v1/backups?business_id=eq.{quote(EDMUS_BIZ)}"
        f"&select=storage_path,created_at,size_bytes&order=created_at.desc&limit=1",
        headers=h,
        timeout=60,
    )
    r.raise_for_status()
    row = r.json()[0]
    print("backup", row)
    storage_path = row["storage_path"]
    dl = requests.get(
        f"{url}/storage/v1/object/{bucket}/{storage_path}",
        headers=h,
        timeout=180,
    )
    dl.raise_for_status()
    tmp = Path(tempfile.mkdtemp(prefix="edmus_backfill_"))
    enc = tmp / "backup.mbtenc"
    enc.write_bytes(dl.content)
    zip_path = tmp / "backup.zip"
    identity = {"business_id": EDMUS_BIZ, "user_id": EDMUS_OWNER, "encryption_salt": ""}
    ok = False
    for cand in derive_candidate_keys(identity, password=""):
        try:
            decrypt_file(str(enc), str(zip_path), cand)
            ok = True
            break
        except EncryptionError:
            continue
    if not ok:
        raise RuntimeError("decrypt failed")
    out = tmp / "out"
    out.mkdir()
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out)
    db = out / "mbt_pos.db"
    if not db.exists():
        db = next(out.rglob("mbt_pos.db"))
    return db


def _entity(entity_type: str, row: dict, version: int) -> dict:
    payload = serialize_entity_payload(entity_type, row)
    updated = (
        payload.get("updated_at")
        or payload.get("created_at")
        or "2026-07-22T00:00:00Z"
    )
    # Ensure timestamptz-ish string
    if isinstance(updated, str) and "T" not in updated and " " in updated:
        updated = updated.replace(" ", "T")
        if not updated.endswith("Z") and "+" not in updated:
            # Shop clocks are Africa/Nairobi (+03:00)
            updated = updated + "+03:00"
    return {
        "branch_id": "",
        "entity_type": entity_type,
        "source_id": str(row["id"]),
        "source_version": max(1, int(version)),
        "source_updated_at": updated,
        "payload": payload,
        "payload_hash": _payload_hash(payload),
        "deleted": False,
    }


def _post_batches(entities: list[dict], label: str) -> int:
    sent = 0
    for i in range(0, len(entities), BATCH):
        chunk = entities[i : i + BATCH]
        key = hashlib.sha256(
            f"edmus-backfill-{label}-{chunk[0]['source_id']}-{chunk[-1]['source_id']}-{len(chunk)}".encode()
        ).hexdigest()
        result = ingest_sync_batch(EDMUS_ORG, DEVICE_CODE, key, chunk)
        print(f"  {label} batch {i // BATCH + 1}: {len(chunk)} -> {result}")
        sent += len(chunk)
    return sent


def main() -> None:
    cfg = _cfg()
    # Ensure platform_service picks up service key from env/config
    os.environ.setdefault("MBT_SUPABASE_URL", cfg["supabase_url"])
    os.environ.setdefault("MBT_SUPABASE_SERVICE_KEY", cfg["service_key"])
    os.environ.setdefault("MBT_SUPABASE_ANON_KEY", cfg.get("anon_key") or "")

    db_path = download_latest_backup(cfg)
    print("db", db_path)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    sales = [
        dict(r)
        for r in con.execute(
            "SELECT * FROM sales WHERE id >= ? ORDER BY id ASC",
            (MIN_SALE_ID,),
        )
    ]
    sale_ids = [s["id"] for s in sales]
    print("sales_to_sync", len(sales), "id_range", sale_ids[0] if sale_ids else None, sale_ids[-1] if sale_ids else None)
    today = [s for s in sales if str(s.get("created_at") or "").startswith("2026-07-22")]
    print("of_which_today", len(today))

    items = []
    if sale_ids:
        q = ",".join("?" * len(sale_ids))
        items = [
            dict(r)
            for r in con.execute(
                f"SELECT * FROM sale_items WHERE sale_id IN ({q}) ORDER BY id ASC",
                sale_ids,
            )
        ]
    print("sale_items_to_sync", len(items))

    debts = [
        dict(r)
        for r in con.execute(
            "SELECT * FROM debt_invoices WHERE id >= 1 ORDER BY id ASC"
        )
    ]
    # Only debts linked to missing sales or created recently — sync all open-ish for completeness if few
    print("debt_invoices_total", len(debts))
    debt_pays = [dict(r) for r in con.execute("SELECT * FROM debt_payments ORDER BY id ASC")]
    print("debt_payments_total", len(debt_pays))

    sale_entities = [_entity("sale", s, s["id"] + 100000) for s in sales]
    item_entities = [_entity("sale_item", it, it["id"] + 100000) for it in items]
    # Prefer debts tied to synced sales
    sale_id_set = {str(i) for i in sale_ids}
    debt_entities = [
        _entity("debt_invoice", d, d["id"] + 100000)
        for d in debts
        if str(d.get("sale_id") or "") in sale_id_set
        or str(d.get("created_at") or "").startswith("2026-07-2")
    ]
    pay_entities = [
        _entity("debt_payment", p, p["id"] + 100000)
        for p in debt_pays
        if str(p.get("created_at") or "").startswith("2026-07-2")
    ]
    print(
        "entities",
        len(sale_entities),
        "items",
        len(item_entities),
        "debts",
        len(debt_entities),
        "pays",
        len(pay_entities),
    )

    n = 0
    n += _post_batches(sale_entities, "sale")
    n += _post_batches(item_entities, "sale_item")
    if debt_entities:
        n += _post_batches(debt_entities, "debt_invoice")
    if pay_entities:
        n += _post_batches(pay_entities, "debt_payment")
    print("posted_entities", n)

    # Verify today count
    from datetime import datetime, timedelta, timezone

    nairobi = timezone(timedelta(hours=3))
    start = datetime(2026, 7, 22, tzinfo=nairobi).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end = datetime(2026, 7, 23, tzinfo=nairobi).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    url = cfg["supabase_url"].rstrip("/")
    key = cfg["service_key"]
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "count=exact"}
    r = requests.get(
        f"{url}/rest/v1/cloud_sales?org_id=eq.{quote(EDMUS_ORG)}"
        f"&source_created_at=gte.{quote(start, safe=':')}"
        f"&source_created_at=lt.{quote(end, safe=':')}"
        f"&select=receipt_number,total,source_created_at,status&order=source_created_at.desc&limit=5",
        headers=h,
        timeout=60,
    )
    print("today_verify_range", r.headers.get("content-range"), r.status_code)
    print("today_sample", r.text[:800])
    con.close()


if __name__ == "__main__":
    main()
