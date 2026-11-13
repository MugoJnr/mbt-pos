from urllib.parse import quote
from backend.cloud.platform_service import service_select, require_org_access, get_org_membership

rows = service_select(
    "licenses",
    "select=id,license_key,plan,status,org_id,activated_devices,max_devices,expires_at,created_at&order=created_at.desc&limit=30",
)
print("LICENSES", len(rows or []))
for r in rows or []:
    print(
        f"- status={r.get('status'):10} plan={r.get('plan'):8} "
        f"key={r.get('license_key')} org={r.get('org_id')} id={r.get('id')} "
        f"devs={r.get('activated_devices')}/{r.get('max_devices')}"
    )

uid = "7d9420ce-9c97-42e9-a9f6-039cd7d0952d"
print("\nMEMBERSHIPS / ACCESS")
for r in rows or []:
    oid = r.get("org_id")
    mem = get_org_membership(uid, oid)
    print(" org", oid, "membership", mem)
    try:
        require_org_access(uid, oid, admin=True)
        print("  admin_access OK")
    except Exception as e:
        print("  admin_access FAIL", e)

# history + activations + remote_commands for latest
if rows:
    for lic in rows[:5]:
        lid = lic["id"]
        acts = service_select(
            "license_activations",
            f"license_id=eq.{quote(str(lid), safe='')}&select=*",
        )
        hist = service_select(
            "license_history",
            f"license_id=eq.{quote(str(lid), safe='')}&select=*&order=created_at.desc&limit=5",
        )
        print("\nLIC", lic.get("license_key"), lic.get("status"))
        print(" acts", acts)
        print(" hist", [(h.get("action"), h.get("actor"), str(h.get("created_at") or "")[:19]) for h in (hist or [])])
        cmds = service_select(
            "remote_commands",
            f"org_id=eq.{quote(str(lic.get('org_id') or ''), safe='')}&select=id,command,status,device_id,created_at,error&order=created_at.desc&limit=8",
        )
        print(" cmds", [(c.get("command"), c.get("status"), c.get("device_id"), c.get("error"), str(c.get("created_at") or "")[:19]) for c in (cmds or [])])
