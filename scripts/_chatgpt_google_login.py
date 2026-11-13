"""Click ChatGPT Log in -> Continue with Google on CDP, using existing Google session."""
from __future__ import annotations

import json
import time

import requests
import websocket

CDP = "http://127.0.0.1:9222"


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
            raise RuntimeError(str(r["exceptionDetails"])[:400])
        return (r.get("result") or {}).get("value")


def main():
    tab = next((t for t in pages() if "chatgpt.com" in (t.get("url") or "")), None)
    if not tab:
        print("NO_CHATGPT")
        return 2
    c = C(tab["webSocketDebuggerUrl"])
    c.call("Runtime.enable")
    c.call("Page.bringToFront")
    print("url", c.ev("location.href"))
    # Click Log in
    clicked = c.ev(
        r"""(() => {
      const els = [...document.querySelectorAll('button, a, [role="button"]')];
      const b = els.find(e => /^(log in|sign in)$/i.test((e.innerText||'').trim()))
        || els.find(e => /log in|sign in/i.test((e.innerText||'').trim()));
      if (b) { b.click(); return (b.innerText||'').trim(); }
      return null;
    })()"""
    )
    print("clicked_login", clicked)
    time.sleep(3)
    # May have navigated or opened auth
    tabs = pages()
    for t in tabs:
        print("TAB", (t.get("title") or "")[:50], (t.get("url") or "")[:100])

    # Prefer auth.openai.com or accounts.google.com tab
    auth = next(
        (
            t
            for t in tabs
            if any(x in (t.get("url") or "") for x in ("auth.openai.com", "accounts.google.com", "login"))
        ),
        None,
    )
    if auth and auth["id"] != tab["id"]:
        c = C(auth["webSocketDebuggerUrl"])
        c.call("Runtime.enable")
        c.call("Page.bringToFront")
        print("switched", c.ev("location.href"))
        time.sleep(1)

    # Click Continue with Google
    g = c.ev(
        r"""(() => {
      const els = [...document.querySelectorAll('button, a, div[role="button"]')];
      const b = els.find(e => /google/i.test((e.innerText||'') + (e.getAttribute('aria-label')||'')));
      if (b) { b.click(); return (b.innerText||b.getAttribute('aria-label')||'').trim().slice(0,80); }
      return null;
    })()"""
    )
    print("clicked_google", g)
    time.sleep(4)

    # On Google account chooser, pick junior
    for t in pages():
        u = t.get("url") or ""
        if "accounts.google.com" in u:
            gc = C(t["webSocketDebuggerUrl"])
            gc.call("Runtime.enable")
            gc.call("Page.bringToFront")
            print("google_url", gc.ev("location.href"))
            print("google_text", (gc.ev("document.body.innerText") or "")[:500])
            picked = gc.ev(
                r"""(() => {
                  const els = [...document.querySelectorAll('[data-email], [data-identifier], li, div[role="link"], div[role="button"]')];
                  const j = els.find(e => /mugo\.junior\.1@gmail\.com/i.test(
                    (e.getAttribute('data-email')||'') + (e.getAttribute('data-identifier')||'') + (e.innerText||'')
                  ));
                  if (j) { j.click(); return 'junior'; }
                  // single account continue
                  const next = [...document.querySelectorAll('button, div[role="link"]')].find(e =>
                    /continue|next|junior/i.test(e.innerText||''));
                  if (next) { next.click(); return 'next:'+(next.innerText||'').trim().slice(0,40); }
                  return null;
                })()"""
            )
            print("picked", picked)
            time.sleep(5)
            break

    # Final session check
    time.sleep(3)
    tab2 = next((t for t in pages() if "chatgpt.com" in (t.get("url") or "")), None)
    if tab2:
        c2 = C(tab2["webSocketDebuggerUrl"])
        c2.call("Runtime.enable")
        sess = c2.ev(
            """fetch('/api/auth/session').then(r=>r.json()).then(j=>({
              email:(j.user||{}).email, name:(j.user||{}).name, plan:(j.account||{}).planType,
              loginWall:/log in/i.test((document.body.innerText||'').slice(0,500))
            })).catch(e=>({err:String(e)}))""",
            await_promise=True,
        )
        print("FINAL", json.dumps(sess, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
