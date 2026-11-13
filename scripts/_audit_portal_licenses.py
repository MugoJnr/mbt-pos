"""One-off portal license/device audit. Do not commit secrets. Mask keys."""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.cloud.platform_service import (  # noqa: E402
    has_service_role,
    service_select,
    service_select_page,
    service_update,
)

EDMUS_ORG = "99a8b1d9"
MYBIZ_PREFIX = "61788aed"
EDMUS_BIZ = "a5795322"


def mask_key(k: str) -> str:
    k = str(k or "")
    if len(k) <= 10:
        return k[:3] + "…" if k else ""
    return k[:8] + "…" + k[-4:]


def fetch_all(table: str, select: str, extra: str = "") -> list:
    out = []
    offset = 0
    while True:
        q = f"select={select}"
        if extra:
            q = extra.rstrip("&") + "&" + q
        rows, total = service_select_page(table, q, limit=1000, offset=offset)
        out.extend(rows or [])
        offset += len(rows or [])
        if not rows or offset >= (total or 0) or len(rows) < 1000:
            break
        if offset > 20000:
            break
    return out


def main():
    print("has_service_role", has_service_role())
    if not has_service_role():
        print("NO SERVICE ROLE — abort")
        return 1

    orgs = service_select("organizations", "select=id,name,slug,owner_user_id&limit=200") or []
    biz = service_select("businesses", "select=id,name,org_id,owner_user_id&limit=500") or []
    print("ORGS", len(orgs))
    for o in orgs:
        print(f"  org {str(o.get('id'))[:8]}… name={o.get('name')!r} slug={o.get('slug')}")
    print("BUSINESSES", len(biz))
    biz_by_id = {b["id"]: b for b in biz if b.get("id")}
    org_by_id = {o["id"]: o for o in orgs if o.get("id")}

    lics = fetch_all(
        "licenses",
        "id,license_key,plan,status,org_id,activated_devices,max_devices,"
        "assigned_email,reserved_device_id,claim_status,expires_at,created_at,product_id",
    )
    acts = fetch_all(
        "license_activations",
        "id,license_id,device_id,org_id,is_active,activated_at,last_validated_at",
    )
    devices = fetch_all(
        "devices",
        "id,device_id,org_id,business_id,hardware_fingerprint,hostname,last_seen_at,created_at",
    )
    print("LICENSES", len(lics), "ACTIVATIONS", len(acts), "DEVICES", len(devices))

    acts_by_lic = defaultdict(list)
    for a in acts:
        acts_by_lic[a.get("license_id")].append(a)

    # Pattern reports
    invalid_email = []
    reserved_but_active = []
    inflated = []
    many_keys_one_device = defaultdict(list)
    device_wrong_org = []

    for lic in lics:
        email = str(lic.get("assigned_email") or "").strip()
        if email and "@" not in email:
            invalid_email.append(lic)
        active = [a for a in acts_by_lic.get(lic["id"], []) if a.get("is_active")]
        unique_devs = {a.get("device_id") for a in active if a.get("device_id")}
        claimed_count = int(lic.get("activated_devices") or 0)
        if unique_devs and str(lic.get("claim_status") or "") == "reserved":
            reserved_but_active.append((lic, unique_devs))
        if claimed_count != len(unique_devs):
            inflated.append((lic, claimed_count, len(unique_devs), unique_devs))
        for did in unique_devs:
            many_keys_one_device[did].append(lic)

    for d in devices:
        did = d.get("device_id")
        dorg = d.get("org_id")
        bid = d.get("business_id")
        b = biz_by_id.get(bid) if bid else None
        borg = b.get("org_id") if b else None
        if bid and borg and dorg and borg != dorg:
            device_wrong_org.append((d, borg, org_by_id.get(dorg, {}).get("name"), org_by_id.get(borg, {}).get("name")))

    print("\n=== invalid assigned_email (no @) ===", len(invalid_email))
    for lic in invalid_email:
        print(
            " ",
            mask_key(lic.get("license_key")),
            "email=",
            repr(lic.get("assigned_email")),
            "claim=",
            lic.get("claim_status"),
            "status=",
            lic.get("status"),
        )

    print("\n=== claim_status reserved but has active activation ===", len(reserved_but_active))
    for lic, devs in reserved_but_active:
        print(
            " ",
            mask_key(lic.get("license_key")),
            "plan=",
            lic.get("plan"),
            "status=",
            lic.get("status"),
            "org=",
            str(lic.get("org_id") or "")[:8],
            "email=",
            lic.get("assigned_email"),
            "reserved=",
            lic.get("reserved_device_id"),
            "devs=",
            sorted(devs),
        )

    print("\n=== activated_devices != unique active acts ===", len(inflated))
    for lic, claimed, uniq, devs in inflated:
        print(
            " ",
            mask_key(lic.get("license_key")),
            "plan=",
            lic.get("plan"),
            "status=",
            lic.get("status"),
            "count=",
            claimed,
            "unique=",
            uniq,
            "devs=",
            sorted(devs),
        )

    print("\n=== devices org_id != business.org_id ===", len(device_wrong_org))
    for d, borg, dname, bname in device_wrong_org:
        print(
            " ",
            d.get("device_id"),
            "host=",
            d.get("hostname"),
            "device_org=",
            str(d.get("org_id") or "")[:8],
            dname,
            "biz_org=",
            str(borg)[:8],
            bname,
            "biz=",
            str(d.get("business_id") or "")[:8],
        )

    print("\n=== many active keys on one device ===")
    for did, ll in sorted(many_keys_one_device.items(), key=lambda x: -len(x[1])):
        active_ll = [x for x in ll if x.get("status") == "active"]
        if len(active_ll) < 2:
            continue
        print(" ", did, "active_keys=", len(active_ll))
        for lic in active_ll:
            print(
                "   ",
                mask_key(lic.get("license_key")),
                lic.get("plan"),
                lic.get("status"),
                "org=",
                str(lic.get("org_id") or "")[:8],
                "claim=",
                lic.get("claim_status"),
                "email=",
                lic.get("assigned_email"),
            )

    print("\n=== all licenses summary ===")
    for lic in sorted(lics, key=lambda x: str(x.get("created_at") or ""), reverse=True):
        active = [a for a in acts_by_lic.get(lic["id"], []) if a.get("is_active")]
        print(
            mask_key(lic.get("license_key")),
            lic.get("plan"),
            lic.get("status"),
            "claim=",
            lic.get("claim_status"),
            "act=",
            lic.get("activated_devices"),
            "uniq=",
            len({a.get("device_id") for a in active}),
            "org=",
            str(lic.get("org_id") or "")[:8],
            "email=",
            lic.get("assigned_email") or "-",
            "res=",
            lic.get("reserved_device_id") or "-",
            "exp=",
            str(lic.get("expires_at") or "")[:10],
        )

    # Safe repairs (apply=1)
    apply = os.environ.get("APPLY_REPAIRS") == "1"
    repairs = []
    if apply:
        for lic, devs in reserved_but_active:
            if lic.get("status") in ("revoked", "suspended"):
                continue
            reserved = lic.get("reserved_device_id") or (sorted(devs)[0] if devs else None)
            patch = {"claim_status": "claimed"}
            if reserved and not lic.get("reserved_device_id"):
                patch["reserved_device_id"] = reserved
            service_update("licenses", f"id=eq.{lic['id']}", patch)
            repairs.append(("claim_status", mask_key(lic.get("license_key")), patch))

        for lic, claimed, uniq, devs in inflated:
            if claimed != uniq:
                service_update(
                    "licenses",
                    f"id=eq.{lic['id']}",
                    {"activated_devices": uniq},
                )
                repairs.append(
                    ("activated_devices", mask_key(lic.get("license_key")), claimed, uniq)
                )

        for lic in lics:
            if lic.get("status") in ("revoked", "suspended"):
                continue
            active = [a for a in acts_by_lic.get(lic["id"], []) if a.get("is_active")]
            unique_devs = sorted({a.get("device_id") for a in active if a.get("device_id")})
            if len(unique_devs) == 1 and not str(lic.get("reserved_device_id") or "").strip():
                service_update(
                    "licenses",
                    f"id=eq.{lic['id']}",
                    {"reserved_device_id": unique_devs[0]},
                )
                repairs.append(
                    ("reserved_device_id", mask_key(lic.get("license_key")), unique_devs[0])
                )

        for d, borg, *_rest in device_wrong_org:
            if not borg or not d.get("id"):
                continue
            service_update("devices", f"id=eq.{d['id']}", {"org_id": borg})
            repairs.append(("device_org", d.get("device_id"), str(borg)[:8]))

        print("\n=== REPAIRS APPLIED ===")
        for r in repairs:
            print(" ", r)
    else:
        print("\n(set APPLY_REPAIRS=1 to apply safe repairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
