"""Open a fully-encoded URL in Eugene Chrome via CDP /json/new."""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request

from _cdp_gmail_auth import CDP, pages


def open_url(url: str) -> str:
    # CRITICAL: encode the entire target URL so &type=... is not eaten by /json/new.
    encoded = urllib.parse.quote(url, safe="")
    req = urllib.request.Request(f"http://localhost:9222/json/new?{encoded}", method="PUT")
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    return data.get("id") or ""


def wait_portal(timeout: float = 20.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for t in pages():
            u = t.get("url") or ""
            if "portal.mugobyte.com" in u and "supabase.co" not in u:
                return t
        time.sleep(0.5)
    return None


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else open("logs/_last_magiclink.txt", encoding="utf-8").read().strip()
    print("OPEN", url[:180])
    tid = open_url(url)
    print("TAB_ID", tid)
    time.sleep(4)
    tab = wait_portal(25)
    if not tab:
        print("NO_PORTAL_TAB")
        for t in pages():
            print(" -", (t.get("url") or "")[:200])
        return
    print("LAND", (tab.get("url") or "")[:220])
    c = CDP(tab["webSocketDebuggerUrl"])
    try:
        time.sleep(2)
        info = c.eval(
            "(() => ({href: location.href, hash: location.hash.slice(0,120), title: document.title, "
            "body: (document.body && document.body.innerText || '').slice(0,600), "
            "token: localStorage.getItem('mbt_token') || localStorage.getItem('token') || '', "
            "keys: Object.keys(localStorage)}))()"
        )
        print("INFO", json.dumps(info.get("value"), ensure_ascii=True)[:1200])
    finally:
        c.close()


if __name__ == "__main__":
    main()
