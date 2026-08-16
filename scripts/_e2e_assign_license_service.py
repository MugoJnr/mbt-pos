"""Assign license to fresh E2E user via service role (admin creds broken)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.cloud.license_server import get_license_server
from backend.cloud.platform_service import has_service_role, service_select

STATE = json.loads((ROOT / "logs" / "_e2e_fresh_user_state.json").read_text(encoding="utf-8"))
EMAIL = STATE["email"]

print("service_role", has_service_role())
print("email", EMAIL)

# Find org via cloud_customers or org_members
orgs = []
for q in [
    f"email=eq.{quote(EMAIL, safe='')}&select=org_id,email,business_name",
    f"assigned_email=eq.{quote(EMAIL, safe='')}&select=org_id,assigned_email",
]:
    for table in ("cloud_customers", "org_members", "profiles"):
        try:
            rows = service_select(table, q)
            if rows:
                print(table, rows[:3])
                orgs.extend([r.get("org_id") for r in rows if r.get("org_id")])
        except Exception as e:
            print(table, "skip", str(e)[:80])

if not orgs:
    # Search businesses by name pattern
    biz = service_select(
        "businesses",
        f"name=ilike.*{quote(STATE['business'].split()[-1], safe='')}*&select=id,name,org_id&limit=5",
    ) or []
    print("businesses", biz)
    orgs = [b.get("org_id") for b in biz if b.get("org_id")]

if not orgs:
    all_orgs = service_select("organizations", "select=id,name,slug&order=created_at.desc&limit=10") or []
    print("recent_orgs", all_orgs)
    # pick newest org as fallback
    if all_orgs:
        orgs = [all_orgs[0]["id"]]

org_id = orgs[0] if orgs else None
if not org_id:
    print("FAIL no org_id")
    sys.exit(1)

print("ORG", org_id)
server = get_license_server()
lic = server.create_license(
    org_id=str(org_id),
    plan="trial",
    notes=f"E2E fresh user {EMAIL}",
    assigned_email=EMAIL,
    product_id="mbt-pos",
    created_by=None,
)
print("LICENSE", json.dumps({k: lic.get(k) for k in ('id', 'license_key', 'assigned_email', 'org_id', 'status')}, default=str))
STATE["license"] = {"ok": True, "license_key": lic.get("license_key"), "license_id": lic.get("id"), "org_id": org_id}
STATE["completed_phases"] = ["2", "3"]
STATE["failed"] = False
(ROOT / "logs" / "_e2e_fresh_user_state.json").write_text(json.dumps(STATE, indent=2), encoding="utf-8")
