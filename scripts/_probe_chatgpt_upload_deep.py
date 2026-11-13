"""Deep probe ChatGPT composer after attempting file attach."""
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
    it = sys.argv[1] if len(sys.argv) > 1 else "21"
    folder = ROOT / "_qa_checkout_pro_design" / f"iter_{it}"
    up = ROOT / "_qa_full_system_polish" / f"desktop_iter{it}" / "chatgpt_upload"
    up.mkdir(parents=True, exist_ok=True)
    stamp_id = str(int(time.time()))
    imgs = []
    for name, label in (
        ("checkout_pro.png", "PRO"),
        ("product_explorer.png", "EXPLORER"),
        ("retail_classic.png", "CLASSIC"),
    ):
        d = up / f"probe_{label.lower()}_{stamp_id}.jpg"
        stamp(folder / name, d, f"{label}-{stamp_id}")
        imgs.append(d)

    tab = next((t for t in pages() if "chatgpt.com" in (t.get("url") or "")), None)
    c = C(tab["webSocketDebuggerUrl"])
    c.call("Runtime.enable")
    c.call("DOM.enable")
    c.call("Page.bringToFront")
    c.call("Page.navigate", {"url": "https://chatgpt.com/"})
    time.sleep(4)

    # Capture console/toast by patching
    c.ev(
        r"""(() => {
      window.__mbt_logs = [];
      const push = (x) => { try { window.__mbt_logs.push(String(x).slice(0,300)); } catch(e){} };
      ['log','warn','error'].forEach(k => {
        const o = console[k];
        console[k] = function(...a){ push(k+': '+a.map(String).join(' ')); return o.apply(this,a); };
      });
      const obs = new MutationObserver((muts) => {
        for (const m of muts) {
          for (const n of m.addedNodes) {
            if (n && n.innerText) {
              const t = (n.innerText||'').trim();
              if (/upload|unable|max |limit|quota|file|image/i.test(t) && t.length < 400) push('DOM:'+t);
            }
          }
        }
      });
      obs.observe(document.body, {childList:true, subtree:true});
      return true;
    })()"""
    )

    doc = c.call("DOM.getDocument", {"depth": 1})
    root = doc["root"]["nodeId"]
    ids = c.call("DOM.querySelectorAll", {"nodeId": root, "selector": "input[type=file]"}).get("nodeIds") or []
    paths = [str(p.resolve()) for p in imgs]
    print("inputs", len(ids), "files", paths)
    for nid in ids:
        try:
            c.call("DOM.setFileInputFiles", {"nodeId": nid, "files": paths})
            print("set ok", nid)
        except Exception as e:
            print("set fail", e)
    time.sleep(3)

    st = c.ev(
        r"""(() => {
      const t = document.body.innerText || '';
      const toasts = [...document.querySelectorAll('[role="alert"], [data-testid*="toast"], .toast, [class*="toast"]')].map(e => (e.innerText||'').trim()).filter(Boolean);
      return {
        max0: /Max 0 uploads/i.test(t),
        unable: /Unable to upload/i.test(t),
        bodyHit: (t.match(/upload[^\n]{0,80}/gi) || []).slice(0,8),
        toasts,
        logs: window.__mbt_logs || [],
        thumbs: document.querySelectorAll('[data-testid="file-thumbnail"], button[aria-label*="Remove file"]').length,
        fileCounts: [...document.querySelectorAll('input[type=file]')].map(f => (f.files && f.files.length) || 0),
        composerHtml: (document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable=true]') || {}).innerHTML?.slice?.(0,200) || null
      };
    })()"""
    )
    print(json.dumps(st, indent=2)[:4000])

    # Check conversation limits API if any
    lim = c.ev(
        """fetch('/backend-api/conversations?offset=0&limit=1', {credentials:'include'}).then(r => ({status:r.status})).catch(e => ({err:String(e)}))""",
        await_promise=True,
    )
    print("api", lim)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
