"""Portal confirm for 3.0.49. Mask keys. Do not download shop DBs."""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.cloud.platform_service import (  # noqa: E402
    has_service_role,
    service_select,
    service_update,
)

EDMUS_ORG = "99a8b1d9-2210-4b7e-9922-28db987bc7b9"
EDMUS_BIZ = "a5795322-4eae-4ed1-9b94-6a1a00c347ce"
MYBIZ = "61788aed"
DEVICE = "MBT-PC-52E5"


def mask_key(k: str) -> str:
    k = str(k or "")
    if len(k) <= 10:
        return k[:3] + "…" if k else ""
    return k[:8] + "…" + k[-4:]


def main() -> int:
    print("has_service_role", has_service_role())
    if not has_service_role():
        print("FAIL: no service role")
        return 1

    orgs = service_select("organizations", "select=id,name,slug&limit=50") or []
    print("ORGS", [(str(o.get("id"))[:8], o.get("name"), o.get("slug")) for o in orgs])

    biz = service_select(
        "businesses",
        f"id=eq.{quote(EDMUS_BIZ, safe='')}&select=id,name,org_id,owner_user_id",
    ) or []
    print("EDMUS_BIZ", biz)

    devices = service_select(
        "devices",
        f"device_id=eq.{quote(DEVICE, safe='')}&select=id,device_id,org_id,business_id,"
        "hardware_fingerprint,hostname,last_seen_at,status,name",
    ) or []
    print("DEVICE_ROWS", json.dumps(devices, default=str)[:2000])

    patched = False
    for d in devices:
        org = str(d.get("org_id") or "")
        biz_id = str(d.get("business_id") or "")
        fp = str(d.get("hardware_fingerprint") or "")
        print(
            "device",
            d.get("device_id"),
            "org",
            org[:8],
            "biz",
            biz_id[:8],
            "fp",
            bool(fp),
            "fp_len",
            len(fp),
            "last_seen",
            d.get("last_seen_at"),
            "host",
            d.get("hostname"),
        )
        if org != EDMUS_ORG or biz_id != EDMUS_BIZ:
            print("PATCHING device org/biz drift")
            service_update(
                "devices",
                f"id=eq.{quote(str(d['id']), safe='')}",
                {"org_id": EDMUS_ORG, "business_id": EDMUS_BIZ},
            )
            patched = True

    if patched:
        devices = service_select(
            "devices",
            f"device_id=eq.{quote(DEVICE, safe='')}&select=id,device_id,org_id,business_id,"
            "hardware_fingerprint,last_seen_at,hostname",
        ) or []
        print("DEVICE_AFTER_PATCH", json.dumps(devices, default=str)[:1500])

    lics = (
        service_select(
            "licenses",
            f"org_id=eq.{quote(EDMUS_ORG, safe='')}&select=id,license_key,plan,status,org_id,"
            "activated_devices,max_devices,assigned_email,reserved_device_id,claim_status,"
            "expires_at,created_at",
        )
        or []
    )
    acts = (
        service_select(
            "license_activations",
            f"org_id=eq.{quote(EDMUS_ORG, safe='')}&select=id,license_id,device_id,org_id,"
            "is_active,activated_at,last_validated_at",
        )
        or []
    )
    acts_by_lic = defaultdict(list)
    for a in acts:
        acts_by_lic[a.get("license_id")].append(a)

    print("EDMUS_LICENSES", len(lics), "ACTIVATIONS", len(acts))
    for r in lics:
        active_unique = {
            a.get("device_id")
            for a in acts_by_lic.get(r.get("id"), [])
            if a.get("is_active")
        }
        count = int(r.get("activated_devices") or 0)
        unique_n = len(active_unique)
        print(
            "LIC",
            mask_key(r.get("license_key")),
            "status",
            r.get("status"),
            "claim",
            r.get("claim_status"),
            "email",
            r.get("assigned_email"),
            "reserved",
            r.get("reserved_device_id"),
            "activated_devices",
            count,
            "unique_active",
            unique_n,
            "max",
            r.get("max_devices"),
        )
        if count != unique_n:
            print("  COUNT_MISMATCH — patching activated_devices to", unique_n)
            service_update(
                "licenses",
                f"id=eq.{quote(str(r['id']), safe='')}",
                {"activated_devices": unique_n},
            )

    # Admin-visible other orgs (testshop) still listed
    all_lics = (
        service_select(
            "licenses",
            "select=id,org_id,status,assigned_email,reserved_device_id,claim_status,activated_devices&limit=80",
        )
        or []
    )
    by_org = defaultdict(int)
    for r in all_lics:
        by_org[str(r.get("org_id") or "")[:8]] += 1
    print("LICENSES_BY_ORG_PREFIX", dict(by_org))

    # Backups for Edmus business
    baks = (
        service_select(
            "backups",
            f"business_id=eq.{quote(EDMUS_BIZ, safe='')}&select=id,business_id,org_id,storage_path,"
            "size_bytes,mbt_version,status,created_at&order=created_at.desc&limit=8",
        )
        or []
    )
    if not baks:
        baks = (
            service_select(
                "backups",
                f"org_id=eq.{quote(EDMUS_ORG, safe='')}&select=id,business_id,org_id,storage_path,"
                "size_bytes,mbt_version,status,created_at&order=created_at.desc&limit=8",
            )
            or []
        )
    print("BACKUPS", len(baks))
    for b in baks:
        print(
            "  bak",
            str(b.get("id"))[:8],
            "size",
            b.get("size_bytes"),
            "ver",
            b.get("mbt_version"),
            "status",
            b.get("status"),
            "path",
            (str(b.get("storage_path") or "")[:60]),
            "at",
            str(b.get("created_at") or "")[:19],
        )

    for lid in [r["id"] for r in lics[:6]]:
        hist = (
            service_select(
                "license_history",
                f"license_id=eq.{quote(str(lid), safe='')}&select=action,actor,created_at&"
                "order=created_at.desc&limit=5",
            )
            or []
        )
        print(
            "HISTORY",
            str(lid)[:8],
            [(h.get("action"), h.get("actor"), str(h.get("created_at") or "")[:19]) for h in hist],
        )

    for table in ("restore_history", "sync_logs"):
        try:
            rows = (
                service_select(
                    table,
                    f"org_id=eq.{quote(EDMUS_ORG, safe='')}&select=*&order=created_at.desc&limit=3",
                )
                or []
            )
            if not rows:
                rows = (
                    service_select(
                        table,
                        f"business_id=eq.{quote(EDMUS_BIZ, safe='')}&select=*&order=created_at.desc&limit=3",
                    )
                    or []
                )
            print(table.upper(), "count_sample", len(rows))
            if rows:
                keys = list(rows[0].keys())
                print("  cols", keys[:12])
                sample = {k: rows[0].get(k) for k in keys[:8]}
                print("  sample", json.dumps(sample, default=str)[:400])
        except Exception as e:
            print(table, "ERR", type(e).__name__, str(e)[:200])

    print("API_NOTE /api/cloud/licenses and /api/cloud/devices require user JWT (token_required).")
    print("API_NOTE /api/cloud/reports requires user JWT. No /api/cloud/backups route; local /api/backup/status.")
    print("PATCHED", patched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
