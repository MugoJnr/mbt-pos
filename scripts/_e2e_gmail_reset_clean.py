"""Clean Gmail recovery: send once, open newest recovery href only, set password."""
from __future__ import annotations

import json
import secrets
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _cdp_gmail_auth import CDP, ensure_gmail, http_json, pages
from _open_auth_link import open_url
from _e2e_env import e2e_admin_email, require_e2e_admin
from backend.cloud.platform_service import cloud_forgot_password, cloud_sign_in

NEW_PASSWORD = "MugoByteTest!" + secrets.token_hex(3)


def main() -> None:
    email = e2e_admin_email() or require_e2e_admin()[0]
    print("SEND", cloud_forgot_password(email))
    Path("logs/_e2e_reset_password.txt").write_text(NEW_PASSWORD, encoding="utf-8")
    time.sleep(10)

    gmail = ensure_gmail()
    cdp = CDP(gmail["webSocketDebuggerUrl"])
    href = ""
    try:
        cdp.call(
            "Page.navigate",
            {
                "url": "https://mail.google.com/mail/u/0/#search/"
                + urllib.parse.quote("newer_than:1d subject:(Reset your MugoByte Platform password)")
            },
        )
        time.sleep(5)
        # Open first row (newest)
        cdp.eval(
            """
(() => {
  const rows = [...document.querySelectorAll('tr.zA')];
  if (!rows.length) return 'no-rows';
  rows[0].click();
  return 'ok';
})()
"""
        )
        time.sleep(3)
        # Expand all messages in thread if needed and pick last recovery link
        href = cdp.eval(
            """
(() => {
  // Expand collapsed messages
  [...document.querySelectorAll('.ajz, .ajy, span.ams')].forEach(el => { try { el.click(); } catch(e){} });
  const links = [...document.querySelectorAll('a')]
    .map(a => a.href)
    .filter(h => h && h.includes('type=recovery'));
  return links.length ? links[links.length - 1] : '';
})()
"""
        ).get("value") or ""
        print("HREF", href[:220])
        subj = cdp.eval("(document.querySelector('h2.hP')||{}).innerText || ''").get("value")
        print("SUBJECT", subj)
    finally:
        cdp.close()

    if not href:
        print("FAIL no recovery href in Gmail")
        return

    open_url(href)
    time.sleep(5)
    tab = None
    for t in pages():
        u = t.get("url") or ""
        if "portal.mugobyte.com/reset-password" in u:
            tab = t
            break
    if not tab:
        print("FAIL land")
        for t in pages():
            if "portal.mugobyte" in (t.get("url") or ""):
                print(" -", (t.get("url") or "")[:180])
        return
    print("LAND", (tab.get("url") or "")[:220])
    if "error=" in (tab.get("url") or ""):
        print("FAIL expired or invalid link from Gmail")
        return

    cdp = CDP(tab["webSocketDebuggerUrl"])
    try:
        time.sleep(1.5)
        filled = cdp.eval(
            f"""
(() => {{
  const inputs = [...document.querySelectorAll('input[type=password]')];
  if (inputs.length < 2) return 'inputs:' + inputs.length;
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
    finally:
        cdp.close()

    try:
        sess = cloud_sign_in(email, NEW_PASSWORD)
        print("LOGIN_OK", sess.get("user", {}).get("email"))
    except Exception as e:
        print("LOGIN_FAIL", e)


if __name__ == "__main__":
    main()
