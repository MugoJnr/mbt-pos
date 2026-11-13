"""Inspect portal/supabase auth tabs via Eugene Chrome CDP."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from _cdp_gmail_auth import CDP, pages


def main() -> None:
    for t in pages():
        u = t.get("url") or ""
        if not any(x in u for x in ("supabase.co/auth", "portal.mugobyte", "auth/callback", "reset-password")):
            continue
        print("TAB", u[:220])
        try:
            c = CDP(t["webSocketDebuggerUrl"])
            info = c.eval(
                "(() => ({href: location.href, hash: location.hash.slice(0,160), "
                "title: document.title, body: (document.body && document.body.innerText || '').slice(0,500)}))()"
            )
            print("INFO", json.dumps(info.get("value"), ensure_ascii=True)[:800])
            c.close()
        except Exception as e:
            print("ERR", e)
        print("---")


if __name__ == "__main__":
    main()
