from backend.cloud_backup.supabase_client import SupabaseClient

c = SupabaseClient()
r = c._session.get(
    c._url("/auth/v1/admin/users"),
    headers=c._headers(use_service=True),
    params={"per_page": 100},
    timeout=30,
)
print("status", r.status_code)
payload = r.json() or {}
users = payload.get("users") if isinstance(payload, dict) else payload
if not isinstance(users, list):
    print(payload)
    raise SystemExit(1)
for u in users:
    email = u.get("email")
    app = u.get("app_metadata") or {}
    role = app.get("platform_role") or app.get("role") or ""
    print(f"{email}\tplatform_role={role}\tuid={u.get('id')}")
