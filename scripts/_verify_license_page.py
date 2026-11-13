"""Verify /license works for eugenemugo after permission fix."""
from __future__ import annotations

import json
import time

from _cdp_gmail_auth import CDP, pages

ORG_WITH_LICENSES = "61788aed-c62d-482b-832b-0784391a2bb1"


def main() -> None:
    tab = next(t for t in pages() if "portal.mugobyte.com" in (t.get("url") or ""))
    cdp = CDP(tab["webSocketDebuggerUrl"])
    try:
        cdp.eval(f"localStorage.setItem('mbt_org', {json.dumps(ORG_WITH_LICENSES)});")
        cdp.call("Page.navigate", {"url": "https://portal.mugobyte.com/license"})
        time.sleep(5)
        ui = cdp.eval(
            """
(() => {
  const t = document.body.innerText || '';
  const idx = t.indexOf('Organization licenses');
  return {
    href: location.href,
    forbidden: t.includes('Manager or administrator access is required'),
    allCounts: (t.match(/All \\((\\d+)\\)/) || [])[1] || null,
    pulseCounts: (t.match(/Pulse \\((\\d+)\\)/) || [])[1] || null,
    mbtCounts: (t.match(/MBT POS \\((\\d+)\\)/) || [])[1] || null,
    hasEugene: t.includes('eugenemugo@gmail.com'),
    hasPulseProduct: /\\bPulse\\b/.test(t),
    snippet: t.slice(Math.max(0, idx), Math.max(0, idx) + 700).replace(/\\s+/g, ' '),
  };
})()
"""
        ).get("value")
        print(json.dumps(ui, default=str, indent=2))
    finally:
        cdp.close()


if __name__ == "__main__":
    main()
