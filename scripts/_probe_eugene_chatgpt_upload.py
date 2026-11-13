"""Probe whether Eugene ChatGPT accepts image upload right now."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests
import websocket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from stamp_qa_images import stamp

CDP = "http://127.0.0.1:9222"


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
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"])[:400])
        return (r.get("result") or {}).get("value")


def main():
    src = ROOT / "_qa_checkout_pro_design" / "iter_23" / "checkout_pro.png"
    out = ROOT / "_qa_full_system_polish" / "desktop_iter23" / "chatgpt_probe.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    stamp(src, out, "PROBE")

    tabs = [
        t for t in requests.get(f"{CDP}/json/list", timeout=5).json()
        if t.get("type") == "page" and "chatgpt.com" in (t.get("url") or "")
    ]
    if not tabs:
        print("NO_CHATGPT_TAB")
        return 2
    c = C(tabs[0]["webSocketDebuggerUrl"])
    c.call("Runtime.enable")
    c.call("Page.bringToFront")
    # Prefer a fresh chat so composer is clean
    href = c.ev("location.href") or ""
    if "/c/" in href or "temporary-chat" in href:
        pass
    else:
        c.call("Page.navigate", {"url": "https://chatgpt.com/"})
        time.sleep(4)

    c.ev(
        """(() => {
      let inp = document.querySelector('#mbt-up');
      if (!inp) {
        inp = document.createElement('input');
        inp.type = 'file';
        inp.id = 'mbt-up';
        inp.accept = 'image/*';
        inp.multiple = true;
        document.body.appendChild(inp);
      }
      return true;
    })()"""
    )
    c.call("DOM.enable")
    doc = c.call("DOM.getDocument", {"depth": 1})
    ids = c.call("DOM.querySelectorAll", {"nodeId": doc["root"]["nodeId"], "selector": "input[type=file]"}).get("nodeIds") or []
    print("inputs", len(ids), flush=True)
    for nid in ids:
        try:
            c.call("DOM.setFileInputFiles", {"nodeId": nid, "files": [str(out.resolve())]})
        except Exception as e:
            print("setfail", e, flush=True)
    time.sleep(3)
    info = c.ev(
        r"""(() => {
          const body = (document.body && document.body.innerText) || '';
          const wait = /wait .{0,24}hours? to upload|upload again|file uploads? are limited|You've reached|can't upload|unable to upload|Get Plus/i.test(body);
          const blobImgs = [...document.querySelectorAll('img')].filter(i => (i.src||'').startsWith('blob:')).length;
          const removeBtns = [...document.querySelectorAll('button')].filter(b => /remove|delete attachment|remove file/i.test((b.getAttribute('aria-label')||'') + b.innerText)).length;
          const send = [...document.querySelectorAll('button')].find(b =>
            (b.getAttribute('data-testid')||'') === 'send-button' || /send/i.test(b.getAttribute('aria-label')||''));
          return {
            wait,
            blobImgs,
            removeBtns,
            sendDisabled: !!(send && send.disabled),
            sendLabel: send ? ((send.getAttribute('aria-label')||send.innerText||'').slice(0,60)) : null,
            freeHint: /Free plan|Upgrade to Plus|Get Plus/i.test(body),
            tail: body.replace(/\s+/g,' ').slice(-600)
          };
        })()"""
    )
    print(json.dumps(info, indent=2)[:2000], flush=True)
    out_txt = ROOT / "_qa_full_system_polish" / "desktop_iter23" / "eugene_chatgpt_upload_probe.json"
    out_txt.write_text(json.dumps(info, indent=2), encoding="utf-8")
    print("WROTE", out_txt, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
