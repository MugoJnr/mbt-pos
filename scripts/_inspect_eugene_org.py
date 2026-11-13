from urllib.parse import quote

from backend.cloud.platform_service import service_select

uid = "7d9420ce-9c97-42e9-a9f6-039cd7d0952d"
q = quote(uid, safe="")
print("owned", service_select("organizations", f"owner_user_id=eq.{q}&select=id,name,slug,owner_user_id"))
print("biz", service_select("businesses", f"owner_user_id=eq.{q}&select=id,name,org_id,owner_user_id"))
print("members", service_select("org_members", f"user_id=eq.{q}&select=*"))
print("slug", service_select("organizations", "slug=eq.my-business&select=id,name,slug,owner_user_id"))
