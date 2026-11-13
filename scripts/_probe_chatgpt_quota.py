"""Probe ChatGPT tab for upload quota / account state."""
from __future__ import annotations

import json
import sys
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

    def ev(self, expr):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"])[:400])
        return (r.get("result") or {}).get("value")


def main():
    tab = next((t for t in pages() if "chatgpt.com" in (t.get("url") or "") and "6a5dc244" not in (t.get("url") or "")), None)
    if not tab:
        tab = next((t for t in pages() if "chatgpt.com" in (t.get("url") or "")), None)
    if not tab:
        print("NO_CHATGPT")
        return 2
    c = C(tab["webSocketDebuggerUrl"])
    c.call("Runtime.enable")
    print("url", c.ev("location.href"))
    st = c.ev(
        r"""(() => {
      const t = document.body.innerText || "";
      const btn = document.querySelector('button[data-testid="send-button"]')
        || document.querySelector('button[aria-label="Send prompt"]');
      return {
        max0: /Max 0 uploads/i.test(t),
        unable: /Unable to upload/i.test(t),
        title: document.title,
        sendDisabled: btn ? btn.disabled : null,
        fileInputs: document.querySelectorAll('input[type=file]').length,
        snippet: t.slice(0, 400)
      };
    })()"""
    )
    print(json.dumps(st, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
