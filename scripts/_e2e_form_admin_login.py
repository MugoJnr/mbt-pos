"""Full UI form login as platform admin; verify /admin/licenses."""
from __future__ import annotations

import json
import time

from _cdp_gmail_auth import CDP, pages
from _open_auth_link import open_url
from _e2e_env import require_e2e_admin

EMAIL, PASSWORD = require_e2e_admin()


def main() -> None:
    open_url("https://portal.mugobyte.com/login?redirect=/admin/licenses")
    time.sleep(4)
    tab = None
    for t in pages():
        if "portal.mugobyte.com/login" in (t.get("url") or ""):
            tab = t
            break
    if not tab:
        for t in pages():
            if "portal.mugobyte.com" in (t.get("url") or ""):
                tab = t
                break
    cdp = CDP(tab["webSocketDebuggerUrl"])
    try:
        cdp.eval("sessionStorage.clear(); localStorage.clear();")
        cdp.call("Page.navigate", {"url": "https://portal.mugobyte.com/login?redirect=/admin/licenses"})
        time.sleep(3)

        # Hard-refresh to pick up new SPA bundle
        cdp.call("Page.reload", {"ignoreCache": True})
        time.sleep(3)

        filled = cdp.eval(
            f"""
(() => {{
  const email = document.querySelector('#email, input[type=email], input[autocomplete=username]');
  const pw = document.querySelector('#password, input[type=password]');
  if (!email || !pw) return 'missing-inputs';
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(email, {json.dumps(EMAIL)});
  email.dispatchEvent(new Event('input', {{bubbles:true}}));
  setter.call(pw, {json.dumps(PASSWORD)});
  pw.dispatchEvent(new Event('input', {{bubbles:true}}));
  const form = email.closest('form');
  if (form) form.requestSubmit();
  else document.querySelector('button[type=submit]')?.click();
  return 'submitted';
}})()
"""
        ).get("value")
        print("FILL", filled)

        for i in range(20):
            time.sleep(1)
            info = cdp.eval(
                """
(() => ({
  href: location.href,
  role: (() => { try { return JSON.parse(sessionStorage.getItem('mbt_user')||'null')?.role } catch(e){return null} })(),
  body: (document.body && document.body.innerText || '').slice(0,280).replace(/\\s+/g,' '),
}))()
"""
            ).get("value") or {}
            href = info.get("href") or ""
            print(f"T{i}", href[:100], "role=", info.get("role"))
            if "/admin/licenses" in href and info.get("role") == "platform_admin":
                print("SUCCESS", info.get("body"))
                return
            if "/dashboard" in href and info.get("role") == "platform_admin":
                cdp.call("Page.navigate", {"url": "https://portal.mugobyte.com/admin/licenses"})
                time.sleep(2)
        print("FAIL", info)
    finally:
        cdp.close()


if __name__ == "__main__":
    main()
