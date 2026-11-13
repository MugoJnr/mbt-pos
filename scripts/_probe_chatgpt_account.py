"""Check ChatGPT login account on CDP."""
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
        print("NO_TAB")
        return 2
    c = C(tab["webSocketDebuggerUrl"])
    c.call("Runtime.enable")
    time.sleep(2)
    info = c.ev(
        """(() => {
      const t = document.body ? document.body.innerText : '';
      return {
        href: location.href,
        title: document.title,
        loginWall: /log in|sign up|Welcome to ChatGPT/i.test(t.slice(0, 1200)),
        max0: /Max 0 uploads/i.test(t),
        hasComposer: !!(document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable=true]')),
        fileInputs: document.querySelectorAll('input[type=file]').length,
        snippet: t.replace(/\\s+/g, ' ').slice(0, 400)
      };
    })()"""
    )
    print("info", json.dumps(info, indent=2))
    sess = c.ev(
        """fetch('/api/auth/session').then(r => r.json()).then(j => ({
          email: (j && j.user && j.user.email) || null,
          name: (j && j.user && j.user.name) || null,
          planType: (j && j.account && j.account.planType) || null,
          rawKeys: j ? Object.keys(j) : []
        })).catch(e => ({err: String(e)}))""",
        await_promise=True,
    )
    print("session", json.dumps(sess, indent=2)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
