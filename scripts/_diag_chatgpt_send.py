"""Diagnose why ChatGPT send stays disabled after image attach."""
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

    def call(self, method, params=None, timeout=60):
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
        return (r.get("result") or {}).get("value")


def main():
    tab = next(t for t in pages() if "chatgpt.com" in (t.get("url") or ""))
    c = C(tab["webSocketDebuggerUrl"])
    c.call("Runtime.enable")
    c.call("Page.bringToFront")
    info = c.ev(
        r"""(() => {
          const body = (document.body && document.body.innerText) || '';
          const send = [...document.querySelectorAll('button')].find(b =>
            (b.getAttribute('data-testid')||'') === 'send-button'
            || /send prompt|send message/i.test(b.getAttribute('aria-label')||''));
          const composer = document.querySelector('[contenteditable="true"], #prompt-textarea, textarea');
          const blobs = [...document.querySelectorAll('img')].filter(i => (i.src||'').startsWith('blob:')).length;
          const toasts = [...document.querySelectorAll('[role="alert"], [data-testid*="toast"], div')].
            filter(n => /upload|plus|wait|hours|limit|free|already uploaded|something new/i.test(n.innerText||''))
            .slice(0, 8).map(n => (n.innerText||'').replace(/\s+/g,' ').slice(0,120));
          return {
            href: location.href.slice(0,100),
            blobs,
            sendDisabled: !!(send && send.disabled),
            sendLabel: send ? (send.getAttribute('aria-label')||'') : null,
            composerText: composer ? ((composer.innerText||composer.value||'').slice(0,80)) : null,
            freeOrPlus: /Free plan|Plus|Upgrade|Get Plus|wait .{0,20}hours/i.test(body),
            waitHours: /wait .{0,24}hours? to upload/i.test(body),
            tail: body.replace(/\s+/g,' ').slice(-700),
            toasts
          };
        })()"""
    )
    print(json.dumps(info, indent=2)[:2500])
    Path = __import__("pathlib").Path
    out = Path(r"C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\_qa_full_system_polish\desktop_iter24\eugene_chatgpt_send_state.json")
    out.write_text(json.dumps(info, indent=2), encoding="utf-8")
    print("WROTE", out)


if __name__ == "__main__":
    main()
