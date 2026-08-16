#!/usr/bin/env python3
"""Login portal as testshop owner and capture settled dashboard/license."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import requests
import cdp_capture_web as m
from _e2e_env import require_e2e_testshop

OUT = m.OUT
EMAIL, PASSWORD = require_e2e_testshop()
ORG_ID = "7951b8db-ec5a-4db5-a820-fe73a2d47ec8"  # testshop


def main() -> int:
    tab = None
    for t in m.pages():
        if "portal.mugobyte.com" in (t.get("url") or ""):
            tab = t
            break
    if not tab:
        # Prefer any page tab; /json/new is flaky on newer Chrome
        pages = m.pages()
        if not pages:
            print("NO_CDP_PAGES", flush=True)
            return 2
        tab = pages[0]
    c = m.C(tab["webSocketDebuggerUrl"])
    c.call("Page.enable")
    c.call("Page.bringToFront")
    # Capture at a wide desktop viewport so Claude doesn't see horizontal scrollbars
    try:
        c.call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": 1440,
                "height": 960,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
    except Exception as e:
        print("viewport_skip", e, flush=True)
    c.call("Page.navigate", {"url": "https://portal.mugobyte.com/login"})
    time.sleep(2.5)
    c.ev(
        """(() => {
          try { sessionStorage.clear(); localStorage.clear(); } catch(e) {}
          return true;
        })()"""
    )
    c.call("Page.navigate", {"url": "https://portal.mugobyte.com/login"})
    time.sleep(3.0)

    filled = c.ev(
        f"""(() => {{
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
    }})()"""
    )
    print("LOGIN_FILL", filled, flush=True)

    ok = False
    for i in range(25):
        time.sleep(1)
        info = c.ev(
            """(() => ({
              href: location.href,
              org: localStorage.getItem('mbt_org') || '',
              user: (localStorage.getItem('mbt_user') || '').slice(0,120),
              body: (document.body && document.body.innerText || '').slice(0,220).replace(/\\s+/g,' '),
            }))()"""
        ) or {}
        print(f"T{i}", (info.get("href") or "")[:90], "org=", info.get("org"), flush=True)
        if "/login" not in (info.get("href") or "") and (
            info.get("org") or "dashboard" in (info.get("href") or "") or "apps" in (info.get("href") or "")
        ):
            ok = True
            break
    if not ok:
        print("LOGIN_FAIL", flush=True)
        c.shot(OUT / "portal_login_fail.png")
        return 2

    # Force testshop org (already primary, but be explicit)
    c.ev(
        f"""(() => {{
          localStorage.setItem('mbt_org', {json.dumps(ORG_ID)});
          return localStorage.getItem('mbt_org');
        }})()"""
    )

    c.call("Page.navigate", {"url": "https://portal.mugobyte.com/dashboard"})
    time.sleep(5.0)
    body = ""
    for _ in range(24):
        body = c.ev("document.body ? document.body.innerText : ''") or ""
        if "Gross sales" in body and "Waiting for first" not in body:
            break
        if "Loading cloud KPIs" in body or "Waiting for first" in body:
            time.sleep(1.0)
            continue
        time.sleep(0.8)
    time.sleep(1.2)
    c.shot(OUT / "portal_dashboard.png")
    print("DASH_SNIP", body[:280].replace("\n", " | "), flush=True)
    if "Waiting for first" in body or "Pulse QA" in body:
        print("WARN_STILL_EMPTY", flush=True)

    c.call("Page.navigate", {"url": "https://portal.mugobyte.com/license"})
    time.sleep(4.5)
    # Scroll so Organization licenses / hardware binding aren't clipped at the fold
    c.ev(
        """(() => {
          const main = document.querySelector('main') || document.scrollingElement || document.body;
          const hw = [...document.querySelectorAll('div,span,p')].find(
            (n) => /^Hardware binding$/i.test((n.textContent || '').trim())
          );
          if (hw) {
            hw.scrollIntoView({ block: 'center', inline: 'nearest' });
            return 'hw-centered';
          }
          if (main && main.scrollHeight > main.clientHeight) {
            main.scrollTop = Math.min(main.scrollHeight, Math.floor(main.clientHeight * 0.55));
            return 'scrolled';
          }
          return 'noop';
        })()"""
    )
    time.sleep(0.6)
    lic = c.ev("document.body ? document.body.innerText.slice(0,400) : ''") or ""
    c.shot(OUT / "portal_license.png")
    print("LIC_SNIP", lic[:240].replace("\n", " | "), flush=True)

    # Also shot reports if present (extra evidence; gate uses dash+license)
    c.call("Page.navigate", {"url": "https://portal.mugobyte.com/reports"})
    time.sleep(5.0)
    c.shot(OUT / "portal_reports.png")
    c.call("Page.navigate", {"url": "https://portal.mugobyte.com/devices"})
    time.sleep(4.0)
    c.shot(OUT / "portal_devices.png")

    (OUT / "portal_capture_status.txt").write_text(
        f"email={EMAIL}\norg={ORG_ID}\ndash_has_gross={'gross sales' in body.lower()}\n"
        f"waiting={'waiting for first' in body.lower()}\n"
        f"last_sync={'last sync' in body.lower()}\nbody={body[:500]}\n",
        encoding="utf-8",
    )
    print("PORTAL_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
