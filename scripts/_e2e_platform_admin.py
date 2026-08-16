"""Login as platform admin and verify /admin/licenses works."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from _cdp_gmail_auth import CDP, pages
from _open_auth_link import open_url
from _e2e_env import require_e2e_admin

EMAIL, PASSWORD = require_e2e_admin()


def find_portal(substr: str = "portal.mugobyte.com"):
    for t in pages():
        if substr in (t.get("url") or ""):
            return t
    return None


def main() -> None:
    open_url("https://portal.mugobyte.com/login")
    time.sleep(3)
    tab = find_portal("/login") or find_portal()
    if not tab:
        raise SystemExit("no portal tab")
    cdp = CDP(tab["webSocketDebuggerUrl"])
    try:
        # Clear session and reload login
        cdp.eval("sessionStorage.clear(); localStorage.clear();")
        cdp.call("Page.navigate", {"url": "https://portal.mugobyte.com/login"})
        time.sleep(3)

        login = cdp.eval(
            f"""
(async () => {{
  const r = await fetch('/api/cloud/auth/login', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    credentials: 'same-origin',
    body: JSON.stringify({{email: {json.dumps(EMAIL)}, password: {json.dumps(PASSWORD)}}})
  }});
  const data = await r.json().catch(() => ({{}}));
  if (!r.ok || !data.token) {{
    return {{ok:false, status:r.status, error:data.error || data, data}};
  }}
  sessionStorage.setItem('mbt_token', data.token);
  sessionStorage.setItem('mbt_user', JSON.stringify(data.user || {{}}));
  sessionStorage.setItem('mbt_provider', data.provider || 'supabase');
  if (data.organizations && data.organizations[0]) {{
    sessionStorage.setItem('mbt_org_id', data.organizations[0].id);
  }}
  return {{
    ok: true,
    role: (data.user || {{}}).role,
    email: (data.user || {{}}).email,
    orgs: (data.organizations || []).length,
  }};
}})()
"""
        ).get("value")
        print("LOGIN", json.dumps(login))
        if not (login or {}).get("ok"):
            return

        cdp.call("Page.navigate", {"url": "https://portal.mugobyte.com/admin/licenses"})
        time.sleep(4)
        for i in range(8):
            info = cdp.eval(
                """
(() => ({
  href: location.href,
  title: document.title,
  body: (document.body && document.body.innerText || '').slice(0, 900),
  role: (() => { try { return JSON.parse(sessionStorage.getItem('mbt_user')||'null')?.role } catch(e){ return null } })(),
}))()
"""
            ).get("value") or {}
            href = info.get("href") or ""
            body = info.get("body") or ""
            print(f"T{i}", href[:120], "role=", info.get("role"))
            print("BODY", body[:350].replace("\n", " | "))
            if "/admin/licenses" in href and ("License" in body or "license" in body.lower()):
                # Also hit admin API if any
                api = cdp.eval(
                    """
(async () => {
  const token = sessionStorage.getItem('mbt_token') || '';
  const paths = [
    '/api/cloud/admin/licenses',
    '/api/cloud/licenses',
    '/api/admin/licenses',
  ];
  const out = [];
  for (const p of paths) {
    try {
      const r = await fetch(p, {headers:{Authorization:'Bearer '+token}, credentials:'same-origin'});
      out.push({path:p, status:r.status, text:(await r.text()).slice(0,120)});
    } catch(e) {
      out.push({path:p, error:String(e)});
    }
  }
  return out;
})()
"""
                ).get("value")
                print("APIS", json.dumps(api)[:800])
                if "/login" not in href and "Access" not in body and "denied" not in body.lower() and "forbidden" not in body.lower():
                    print("SUCCESS_ADMIN_LICENSES")
                return
            if "/login" in href or "Access denied" in body or "not authorized" in body.lower():
                print("FAIL_ACCESS")
                return
            time.sleep(1)
        print("TIMEOUT")
    finally:
        cdp.close()


if __name__ == "__main__":
    main()
