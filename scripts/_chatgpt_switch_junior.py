"""Switch ChatGPT account to mugo.junior.1@gmail.com via account menu."""
from __future__ import annotations

import json
import time

import requests
import websocket

CDP = "http://127.0.0.1:9222"
TARGET = "mugo.junior.1@gmail.com"


def pages():
    return [t for t in requests.get(f"{CDP}/json/list", timeout=5).json() if t.get("type") == "page"]


class C:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, timeout=30)
        self.i = 0

    def call(self, method, params=None, timeout=90):
        self.i += 1
        mid = self.i
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result") or {}
        raise TimeoutError(method)

    def ev(self, expr, await_promise=False):
        r = self.call(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": await_promise},
        )
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"])[:500])
        return (r.get("result") or {}).get("value")


def main():
    tab = next((t for t in pages() if "chatgpt.com" in (t.get("url") or "")), None)
    if not tab:
        print("NO_TAB")
        return 2
    c = C(tab["webSocketDebuggerUrl"])
    c.call("Runtime.enable")
    c.call("Page.bringToFront")

    # Open profile / account menu
    opened = c.ev(
        r"""(() => {
          const cands = [
            ...document.querySelectorAll('button[data-testid="accounts-profile-button"]'),
            ...document.querySelectorAll('button[aria-label*="Open profile"], button[aria-label*="Account"], img[alt*="User"]'),
            ...document.querySelectorAll('button'),
          ];
          for (const b of cands) {
            const t = ((b.getAttribute('aria-label')||'') + ' ' + (b.innerText||'')).toLowerCase();
            if (b.getAttribute('data-testid')==='accounts-profile-button' || /profile|account|eugene|mugo/.test(t)) {
              b.click();
              return (b.getAttribute('data-testid')||b.getAttribute('aria-label')||b.innerText||'').slice(0,80);
            }
          }
          // bottom-left avatar often last button with img
          const imgs = [...document.querySelectorAll('nav img, button img')];
          if (imgs.length) { imgs[imgs.length-1].closest('button')?.click(); return 'avatar-img'; }
          return null;
        })()"""
    )
    print("opened_menu", opened)
    time.sleep(1.5)
    print("menu_text", (c.ev("document.body.innerText") or "")[-800:])

    # Click switch account / add account / junior email
    clicked = c.ev(
        f"""(() => {{
          const want = {json.dumps(TARGET)};
          const els = [...document.querySelectorAll('button, a, div[role="menuitem"], div[role="button"], span')];
          const hit = els.find(e => (e.innerText||'').includes(want));
          if (hit) {{ hit.click(); return 'email:'+want; }}
          const sw = els.find(e => /switch account|add account|log out|logout/i.test((e.innerText||'').trim()));
          if (sw) {{ sw.click(); return 'action:'+(sw.innerText||'').trim().slice(0,60); }}
          return null;
        }})()"""
    )
    print("clicked", clicked)
    time.sleep(3)

    # If logout, then login as junior
    if clicked and "log" in str(clicked).lower():
        time.sleep(2)
        c.ev(
            r"""(() => {
              const b = [...document.querySelectorAll('button,a')].find(e => /^(log in|sign in)$/i.test((e.innerText||'').trim()));
              if (b) { b.click(); return true; }
              return false;
            })()"""
        )
        time.sleep(2)

    # Google account chooser / continue
    for _ in range(8):
        for t in pages():
            u = t.get("url") or ""
            if "accounts.google.com" in u or "auth.openai.com" in u:
                g = C(t["webSocketDebuggerUrl"])
                g.call("Runtime.enable")
                g.call("Page.bringToFront")
                print("auth_url", u[:120])
                print("auth_text", (g.ev("document.body.innerText") or "")[:500])
                pick = g.ev(
                    f"""(() => {{
                      const want = {json.dumps(TARGET)};
                      const els = [...document.querySelectorAll('[data-email], [data-identifier], li, div[role="link"], div[role="button"], button')];
                      const j = els.find(e => ((e.getAttribute('data-email')||'')+(e.getAttribute('data-identifier')||'')+(e.innerText||'')).includes(want));
                      if (j) {{ j.click(); return 'picked-junior'; }}
                      const next = els.find(e => /^(next|continue)$/i.test((e.innerText||'').trim()));
                      if (next) {{ next.click(); return 'next'; }}
                      return null;
                    }})()"""
                )
                print("pick", pick)
                time.sleep(3)

        sess = c.ev(
            """fetch('/api/auth/session').then(r=>r.json()).then(j=>({
              email:(j.user||{}).email, plan:(j.account||{}).planType
            })).catch(e=>({err:String(e)}))""",
            await_promise=True,
        )
        print("sess", sess)
        if isinstance(sess, dict) and sess.get("email") and "junior" in sess.get("email", ""):
            print("SUCCESS_JUNIOR")
            return 0
        time.sleep(2)
    print("NOT_SWITCHED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
