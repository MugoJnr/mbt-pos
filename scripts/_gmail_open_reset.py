"""Find and open the latest MugoByte password-reset email in Gmail."""
from __future__ import annotations

import time
import urllib.parse

from _cdp_gmail_auth import CDP, ensure_gmail, http_json


def main() -> None:
    gmail = ensure_gmail()
    cdp = CDP(gmail["webSocketDebuggerUrl"])
    try:
        cdp.call(
            "Page.navigate",
            {
                "url": "https://mail.google.com/mail/u/0/#search/"
                + urllib.parse.quote('subject:(Reset your MugoByte Platform password)')
            },
        )
        time.sleep(5)
        clicked = cdp.eval(
            """
(() => {
  const rows = [...document.querySelectorAll('tr.zA')];
  if (!rows.length) return 'no-rows';
  // Prefer newest unread-ish row whose snippet mentions Reset/password
  const prefer = rows.find(r => /reset|password/i.test(r.innerText || '')) || rows[0];
  prefer.click();
  return 'clicked:' + (prefer.innerText || '').slice(0,160).replace(/\\s+/g,' ');
})()
"""
        ).get("value")
        print("CLICK", clicked)
        time.sleep(3)
        href = cdp.eval(
            """
(() => {
  const links = [...document.querySelectorAll('a')].map(a => a.href).filter(h =>
    h && (h.includes('type=recovery') || h.includes('reset-password') || (h.includes('supabase.co/auth') && h.includes('verify')))
  );
  // Prefer recovery explicitly
  const recovery = links.find(h => h.includes('type=recovery')) || links[0] || '';
  return recovery;
})()
"""
        ).get("value")
        print("HREF", (href or "")[:220])
        subject = cdp.eval(
            """
(() => {
  const h = document.querySelector('h2.hP') || document.querySelector('h2');
  return (h && h.innerText) || document.title || '';
})()
"""
        ).get("value")
        print("SUBJECT", subject)
        if href:
            http_json("http://127.0.0.1:9222/json/new?" + urllib.parse.quote(href, safe=""), "PUT")
            print("OPENED")
            time.sleep(5)
    finally:
        cdp.close()


if __name__ == "__main__":
    main()
