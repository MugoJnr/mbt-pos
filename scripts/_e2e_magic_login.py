"""End-to-end: magiclink login should land on dashboard after deploy."""
from __future__ import annotations

import json
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _cdp_gmail_auth import CDP, pages
from _open_auth_link import open_url, wait_portal
from _e2e_env import require_e2e_admin
from backend.cloud_backup.supabase_client import SupabaseClient


def main() -> None:
    email, _password = require_e2e_admin()
    c = SupabaseClient()
    data = c.generate_auth_link(
        email=email,
        link_type="magiclink",
        redirect_to="https://portal.mugobyte.com/auth/callback",
    )
    action = data.get("action_link") or ""
    Path("logs/_last_magiclink.txt").write_text(action, encoding="utf-8")
    open_url(action)
    time.sleep(6)
    # Prefer callback / dashboard tabs
    deadline = time.time() + 25
    tab = None
    while time.time() < deadline:
        for t in pages():
            u = t.get("url") or ""
            if "portal.mugobyte.com" in u and ("auth/callback" in u or "dashboard" in u):
                tab = t
                break
        if tab:
            break
        time.sleep(0.7)
    if not tab:
        tab = wait_portal(5)
    if not tab:
        print("FAIL no portal tab")
        return
    print("LAND", (tab.get("url") or "")[:200])
    cdp = CDP(tab["webSocketDebuggerUrl"])
    try:
        for i in range(12):
            info = cdp.eval(
                """
(() => ({
  href: location.href,
  body: (document.body && document.body.innerText || '').slice(0,400),
  token: sessionStorage.getItem('mbt_token') || '',
  user: sessionStorage.getItem('mbt_user') || '',
}))()
"""
            ).get("value") or {}
            href = info.get("href") or ""
            token = info.get("token") or ""
            print(f"T{i}", href[:120], "token", bool(token), "body", (info.get("body") or "")[:120].replace("\n", " | "))
            if "/dashboard" in href and token:
                print("SUCCESS_DASHBOARD_LOGIN")
                return
            if "Signed in" in (info.get("body") or "") or "Opening your workspace" in (info.get("body") or ""):
                time.sleep(1)
                continue
            if "Verification link failed" in (info.get("body") or ""):
                print("FAIL_CALLBACK", info.get("body"))
                # Try manual session once more for diagnosis
                api = cdp.eval(
                    """
(async () => {
  const hash = new URLSearchParams(location.hash.replace(/^#/, ''));
  const access = hash.get('access_token') || '';
  const refresh = hash.get('refresh_token') || '';
  const r = await fetch('/api/cloud/auth/session', {
    method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin',
    body: JSON.stringify({access_token:access, refresh_token:refresh})
  });
  return {status:r.status, text:(await r.text()).slice(0,300)};
})()
"""
                ).get("value")
                print("API", api)
                return
            time.sleep(1.2)
        print("TIMEOUT", json.dumps(info)[:500])
    finally:
        cdp.close()


if __name__ == "__main__":
    main()
