"""Diagnose ChatGPT send-disabled with attachments; try force-send."""
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

    def ev(self, expr):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"])[:400])
        return (r.get("result") or {}).get("value")


def main():
    tab = next((t for t in pages() if "chatgpt.com" in (t.get("url") or "")), None)
    c = C(tab["webSocketDebuggerUrl"])
    c.call("Runtime.enable")
    c.call("Page.bringToFront")
    st = c.ev(
        r"""(() => {
      const b = document.querySelector('button[data-testid="send-button"]') || document.querySelector('button[aria-label="Send prompt"]');
      const t = document.body.innerText || '';
      return {
        sendDisabled: b ? b.disabled : null,
        sendAria: b ? b.getAttribute('aria-disabled') : null,
        sendHtml: b ? b.outerHTML.slice(0, 300) : null,
        thumbs: document.querySelectorAll('[data-testid="file-thumbnail"], button[aria-label*="Remove file"]').length,
        max0: /Max 0 uploads/i.test(t),
        unable: /Unable to upload/i.test(t),
        already: /already uploaded/i.test(t),
        uploading: /uploading/i.test(t.slice(-2000)),
        alerts: [...document.querySelectorAll('[role="alert"], [data-testid*="toast"]')].map(e => (e.innerText||'').trim()).filter(Boolean).slice(0,5),
        composer: ((document.querySelector('#prompt-textarea')||{}).innerText || '').slice(0,120),
        bodyHits: (t.match(/upload[^\n]{0,60}|max [0-9]+|limit[^\n]{0,40}/gi) || []).slice(0,10)
      };
    })()"""
    )
    print(json.dumps(st, indent=2))

    # Type a short prompt if empty, wait for enable
    c.ev(
        r"""(() => {
      const el = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable="true"]');
      if (!el) return false;
      el.focus();
      const has = (el.innerText || '').trim().length > 10;
      if (!has) {
        document.execCommand('insertText', false, 'Rate these three MBT POS checkout screenshots.');
        el.dispatchEvent(new InputEvent('input', {bubbles:true}));
      }
      return true;
    })()"""
    )
    for i in range(30):
        d = c.ev(
            r"""(() => {
              const b = document.querySelector('button[data-testid="send-button"]') || document.querySelector('button[aria-label="Send prompt"]');
              return {disabled: b ? b.disabled : true, thumbs: document.querySelectorAll('[data-testid="file-thumbnail"], button[aria-label*="Remove file"]').length};
            })()"""
        )
        print("wait", i, d)
        if d and not d.get("disabled") and d.get("thumbs", 0) >= 1:
            sent = c.ev(
                r"""(() => {
                  const b = document.querySelector('button[data-testid="send-button"]') || document.querySelector('button[aria-label="Send prompt"]');
                  if (b && !b.disabled) { b.click(); return 'click'; }
                  return 'fail';
                })()"""
            )
            print("SENT", sent)
            return 0
        # dismiss toasts
        c.ev(
            r"""(() => {
              const b = [...document.querySelectorAll('button')].find(x => /^(OK|Got it|Dismiss)$/i.test((x.innerText||'').trim()));
              if (b) { b.click(); return true; }
              return false;
            })()"""
        )
        time.sleep(1)
    print("STILL_DISABLED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
