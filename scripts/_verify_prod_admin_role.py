"""Reproduce exact UI login flow against production and inspect role."""
from __future__ import annotations

import base64
import json
import time

from _cdp_gmail_auth import CDP, pages
from _open_auth_link import open_url
from _e2e_env import require_e2e_admin

EMAIL, PASSWORD = require_e2e_admin()


def b64url_json(part: str):
    pad = "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part + pad))


def main() -> None:
    open_url("https://portal.mugobyte.com/login")
    time.sleep(3)
    tab = None
    for t in pages():
        if "portal.mugobyte.com" in (t.get("url") or ""):
            tab = t
            break
    cdp = CDP(tab["webSocketDebuggerUrl"])
    try:
        cdp.eval("sessionStorage.clear(); localStorage.clear();")
        cdp.call("Page.reload", {"ignoreCache": True})
        time.sleep(3)

        # Exact same endpoint the login form uses
        res = cdp.eval(
            f"""
(async () => {{
  const r = await fetch('/api/cloud/auth/login', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    credentials:'same-origin',
    body: JSON.stringify({{email:{json.dumps(EMAIL)}, password:{json.dumps(PASSWORD)}}})
  }});
  const data = await r.json();
  return {{status:r.status, role:(data.user||{{}}).role, user:data.user, hasToken:!!data.token}};
}})()
"""
        ).get("value")
        print("PROD_LOGIN", json.dumps(res, default=str)[:500])

        # Store like the app does, then navigate admin via SPA
        store = cdp.eval(
            f"""
(async () => {{
  const r = await fetch('/api/cloud/auth/login', {{
    method:'POST', headers:{{'Content-Type':'application/json'}}, credentials:'same-origin',
    body: JSON.stringify({{email:{json.dumps(EMAIL)}, password:{json.dumps(PASSWORD)}}})
  }});
  const data = await r.json();
  sessionStorage.setItem('mbt_token', data.token);
  sessionStorage.setItem('mbt_user', JSON.stringify(data.user));
  sessionStorage.setItem('mbt_auth_provider', 'supabase');
  return data.token;
}})()
"""
        ).get("value")
        if store and store.count(".") == 2:
            payload = b64url_json(store.split(".")[1])
            print("JWT_app_metadata", payload.get("app_metadata"))
            print("JWT_role_claim", payload.get("role"), payload.get("user_metadata"))

        cdp.call("Page.navigate", {"url": "https://portal.mugobyte.com/dashboard"})
        time.sleep(3)
        dash = cdp.eval(
            """
(() => ({
  href: location.href,
  storedRole: JSON.parse(sessionStorage.getItem('mbt_user')||'null')?.role,
  bodyHasAdmin: /Platform Admin|License Control|\\/admin\\/licenses/i.test(document.body.innerText||''),
  sidebar: (document.body.innerText||'').includes('Platform Admin'),
}))()
"""
        ).get("value")
        print("DASH", dash)

        cdp.call("Page.navigate", {"url": "https://portal.mugobyte.com/admin/licenses"})
        time.sleep(3)
        admin = cdp.eval(
            """
(() => ({
  href: location.href,
  storedRole: JSON.parse(sessionStorage.getItem('mbt_user')||'null')?.role,
  title: document.title,
  body: (document.body.innerText||'').slice(0,400),
}))()
"""
        ).get("value")
        print("ADMIN", json.dumps(admin, default=str)[:600])
    finally:
        cdp.close()


if __name__ == "__main__":
    main()
