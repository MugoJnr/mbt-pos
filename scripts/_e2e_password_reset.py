"""E2E password reset: request reset, open Gmail link, set password, login."""
from __future__ import annotations

import json
import secrets
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _cdp_gmail_auth import CDP, ensure_gmail, pages
from _open_auth_link import open_url
from _e2e_env import e2e_admin_email, require_e2e_admin
from backend.cloud.platform_service import cloud_forgot_password, cloud_sign_in


NEW_PASSWORD = "MugoByteTest!" + secrets.token_hex(3)  # 12+ chars


def open_fully(url: str) -> None:
    open_url(url)


def main() -> None:
    email = e2e_admin_email() or require_e2e_admin()[0]
    print("REQUEST_RESET", cloud_forgot_password(email))
    print("NEW_PASSWORD_LEN", len(NEW_PASSWORD))
    Path("logs/_e2e_reset_password.txt").write_text(NEW_PASSWORD, encoding="utf-8")

    # Prefer direct recovery link (same path email uses) so we don't depend on inbox latency.
    from backend.cloud_backup.supabase_client import SupabaseClient
    from backend.cloud.platform_service import _auth_redirect

    client = SupabaseClient()
    data = client.generate_auth_link(
        email=email,
        link_type="recovery",
        redirect_to=_auth_redirect(),
    )
    action = data.get("action_link") or (data.get("properties") or {}).get("action_link") or ""
    print("RECOVERY_REDIRECT", "auth/callback" in action, action[:160])
    Path("logs/_last_recovery.txt").write_text(action, encoding="utf-8")
    open_fully(action)
    time.sleep(5)

    tab = None
    for t in pages():
        u = t.get("url") or ""
        if "portal.mugobyte.com" in u and ("reset-password" in u or "auth/callback" in u):
            tab = t
            break
    if not tab:
        print("FAIL no reset tab")
        for t in pages():
            print(" -", (t.get("url") or "")[:160])
        return
    print("LAND", (tab.get("url") or "")[:200])
    cdp = CDP(tab["webSocketDebuggerUrl"])
    try:
        # If still on callback, wait for redirect to reset-password
        for _ in range(10):
            href = cdp.eval("location.href").get("value") or ""
            print("HREF", href[:160])
            if "/reset-password" in href:
                break
            time.sleep(0.8)
        time.sleep(1)
        # Fill form via DOM
        filled = cdp.eval(
            f"""
(() => {{
  const inputs = [...document.querySelectorAll('input[type=password]')];
  if (inputs.length < 2) return 'need-2-inputs:' + inputs.length;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(inputs[0], {json.dumps(NEW_PASSWORD)});
  inputs[0].dispatchEvent(new Event('input', {{bubbles:true}}));
  setter.call(inputs[1], {json.dumps(NEW_PASSWORD)});
  inputs[1].dispatchEvent(new Event('input', {{bubbles:true}}));
  const btn = document.querySelector('button[type=submit]');
  if (btn) btn.click();
  return 'submitted';
}})()
"""
        ).get("value")
        print("FILL", filled)
        time.sleep(4)
        print("AFTER", cdp.eval("location.href").get("value"))
        print("BODY", (cdp.eval("(document.body&&document.body.innerText||'').slice(0,300)").get("value") or "")[:300])
    finally:
        cdp.close()

    # Verify password works via API
    try:
        sess = cloud_sign_in(email, NEW_PASSWORD)
        print("LOGIN_OK", sess.get("user", {}).get("email"), "orgs", len(sess.get("organizations") or []))
    except Exception as e:
        print("LOGIN_FAIL", e)
        return

    # Also exercise UI login page
    open_fully("https://portal.mugobyte.com/login")
    time.sleep(3)
    login_tab = None
    for t in pages():
        if "portal.mugobyte.com/login" in (t.get("url") or ""):
            login_tab = t
            break
    if not login_tab:
        print("NO_LOGIN_TAB")
        return
    cdp = CDP(login_tab["webSocketDebuggerUrl"])
    try:
        # clear any existing session
        cdp.eval("sessionStorage.clear(); localStorage.clear();")
        cdp.call("Page.reload", {"ignoreCache": True})
        time.sleep(3)
        result = cdp.eval(
            f"""
(async () => {{
  const r = await fetch('/api/cloud/auth/login', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    credentials:'same-origin',
    body: JSON.stringify({{email:{json.dumps(email)}, password:{json.dumps(NEW_PASSWORD)}}})
  }});
  const data = await r.json().catch(() => ({{}}));
  if (r.ok && data.token) {{
    sessionStorage.setItem('mbt_token', data.token);
    sessionStorage.setItem('mbt_user', JSON.stringify(data.user || {{}}));
    sessionStorage.setItem('mbt_provider', 'supabase');
    location.href = '/dashboard';
  }}
  return {{status:r.status, error:data.error, hasToken:!!data.token}};
}})()
"""
        ).get("value")
        print("UI_LOGIN_API", result)
        time.sleep(3)
        print("FINAL", cdp.eval("location.href").get("value"), "token", bool(cdp.eval("sessionStorage.getItem('mbt_token')").get("value")))
    finally:
        cdp.close()


if __name__ == "__main__":
    main()
