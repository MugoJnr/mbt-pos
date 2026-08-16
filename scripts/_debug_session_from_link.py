"""Fresh magiclink -> extract tokens from browser -> test session APIs."""
from __future__ import annotations

import json
import time
import traceback
import urllib.parse
import urllib.request

from _cdp_gmail_auth import CDP, pages
from _open_auth_link import open_url, wait_portal
from _e2e_env import require_e2e_admin


def generate_and_open():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.cloud_backup.supabase_client import SupabaseClient
    from _e2e_env import require_e2e_admin

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
    return action


def main() -> None:
    generate_and_open()
    time.sleep(5)
    tab = wait_portal(20)
    if not tab:
        print("NO_PORTAL")
        return
    print("LAND", (tab.get("url") or "")[:180])
    c = CDP(tab["webSocketDebuggerUrl"])
    try:
        # Wait for SPA to settle
        time.sleep(2)
        tokens = c.eval(
            """
(() => {
  const hash = new URLSearchParams(location.hash.replace(/^#/, ''));
  return {
    href: location.href.slice(0,120),
    access: hash.get('access_token') || '',
    refresh: hash.get('refresh_token') || '',
    type: hash.get('type') || '',
    error: hash.get('error_description') || hash.get('error') || '',
    body: (document.body && document.body.innerText || '').slice(0,300),
  };
})()
"""
        ).get("value") or {}
        print("TOKENS", {k: (v[:40] + "..." if k in ("access", "refresh") and v else v) for k, v in tokens.items()})
        access = tokens.get("access") or ""
        refresh = tokens.get("refresh") or ""
        if not access:
            print("NO_ACCESS")
            return

        # 1) Local cloud_session_from_tokens
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from backend.cloud.platform_service import cloud_session_from_tokens

        try:
            out = cloud_session_from_tokens(access, refresh)
            print("LOCAL_OK", out.get("user", {}).get("email"), "orgs", len(out.get("organizations") or []))
        except Exception as e:
            print("LOCAL_FAIL", e)
            traceback.print_exc()

        # 2) Direct /auth/v1/user
        from backend.cloud_backup.supabase_client import SupabaseClient

        client = SupabaseClient()
        r = client._session.get(
            client._url("/auth/v1/user"),
            headers=client._headers(token=access),
            timeout=30,
        )
        print("USER_API", r.status_code, r.text[:300])

        # 3) Production session endpoint
        payload = json.dumps({"access_token": access, "refresh_token": refresh}).encode()
        req = urllib.request.Request(
            "https://portal.mugobyte.com/api/cloud/auth/session",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                print("PROD_OK", resp.status, resp.read()[:400])
        except urllib.error.HTTPError as e:
            print("PROD_FAIL", e.code, e.read()[:400])
    finally:
        c.close()


if __name__ == "__main__":
    main()
