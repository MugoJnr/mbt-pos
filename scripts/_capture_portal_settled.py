"""Capture portal pages after analytics settle."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import requests
import cdp_capture_web as m

OUT = m.OUT


def main() -> int:
    tab = None
    for t in m.pages():
        if "portal.mugobyte.com" in (t.get("url") or ""):
            tab = t
            break
    if not tab:
        tab = requests.get(
            f"{m.CDP}/json/new?https://portal.mugobyte.com/dashboard", timeout=10
        ).json()
    c = m.C(tab["webSocketDebuggerUrl"])
    c.call("Page.enable")
    c.call("Page.bringToFront")

    c.call("Page.navigate", {"url": "https://portal.mugobyte.com/dashboard"})
    time.sleep(6.0)
    for _ in range(18):
        txt = c.call(
            "Runtime.evaluate",
            {
                "expression": "document.body ? document.body.innerText : ''",
                "returnByValue": True,
            },
        )
        body = ((txt.get("result") or {}).get("value") or "")
        if "Activate license" in body or "Gross sales" in body:
            break
        if "Loading cloud KPIs" in body:
            time.sleep(1.0)
            continue
        if "Waiting for first" in body:
            time.sleep(0.8)
            continue
        time.sleep(0.8)
    time.sleep(1.5)
    c.shot(OUT / "portal_dashboard.png")

    c.call("Page.navigate", {"url": "https://portal.mugobyte.com/license"})
    time.sleep(4.5)
    c.shot(OUT / "portal_license.png")
    print("PORTAL_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
