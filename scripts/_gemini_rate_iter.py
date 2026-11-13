"""Rate iter_N checkout layouts via Gemini with robust file attach."""
from __future__ import annotations

import argparse
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
PROMPT = """NEW screenshots attached (ignore colored QA borders).

Rate MBT POS checkout layouts in order: 1 Checkout Pro, 2 Product Explorer, 3 Retail Classic.

Respond EXACTLY:
CHECKOUT_PRO: <0-100>%
PRODUCT_EXPLORER: <0-100>%
RETAIL_CLASSIC: <0-100>%
OVERALL_CHECKOUT: <0-100>%

IMPROVED:
- ...

REMAINING (must-fix before 98%):
1. ...

NEXT FIXES (top 5 concrete UI only):
1. ...

Be strict. 98%=ship-ready."""


class C:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, timeout=30)
        self.i = 0

    def call(self, method, params=None, timeout=120):
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


def pages():
    return [t for t in requests.get(f"{CDP}/json/list", timeout=5).json() if t.get("type") == "page"]


def prepare(it: str):
    folder = ROOT / "_qa_checkout_pro_design" / f"iter_{it}"
    up = ROOT / "_qa_full_system_polish" / f"desktop_iter{it}" / "gemini_upload"
    up.mkdir(parents=True, exist_ok=True)
    stamp_id = str(int(time.time()))
    imgs = []
    for i, (name, label) in enumerate(
        (
            ("checkout_pro.png", "PRO"),
            ("product_explorer.png", "EXPLORER"),
            ("retail_classic.png", "CLASSIC"),
        ),
        start=1,
    ):
        # Unique stamp per file so Gemini/ChatGPT don't dedupe
        d = up / f"{i}_{label.lower()}_{stamp_id}.jpg"
        stamp(folder / name, d, f"{label}-{stamp_id}-{i}")
        imgs.append(d)
    return imgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iter", default="24")
    args = ap.parse_args()
    out = ROOT / "_qa_full_system_polish" / f"desktop_iter{args.iter}" / "gemini_checkout_interim.txt"
    imgs = prepare(args.iter)

    tab = None
    for t in pages():
        if "gemini.google.com" in (t.get("url") or ""):
            tab = t
            break
    if not tab:
        print("NO_GEMINI")
        return 2
    c = C(tab["webSocketDebuggerUrl"])
    c.call("Runtime.enable")
    c.call("Page.bringToFront")
    c.call("Page.navigate", {"url": "https://gemini.google.com/app"})
    time.sleep(5)

    # Create dedicated file input + set files
    c.ev(
        """(() => {
      let inp = document.querySelector('#mbt-up');
      if (!inp) {
        inp = document.createElement('input');
        inp.type = 'file';
        inp.id = 'mbt-up';
        inp.accept = 'image/*';
        inp.multiple = true;
        inp.style.cssText = 'position:fixed;left:8px;top:8px;z-index:99999;opacity:0.01';
        document.body.appendChild(inp);
      }
      return true;
    })()"""
    )
    c.call("DOM.enable")
    doc = c.call("DOM.getDocument", {"depth": 1})
    ids = c.call("DOM.querySelectorAll", {"nodeId": doc["root"]["nodeId"], "selector": "input[type=file]"}).get("nodeIds") or []
    abs_paths = [str(p.resolve()) for p in imgs]
    print("inputs", len(ids), "files", len(abs_paths), flush=True)
    for nid in ids:
        try:
            c.call("DOM.setFileInputFiles", {"nodeId": nid, "files": abs_paths})
        except Exception as e:
            print("setfail", e, flush=True)
    time.sleep(4)
    preview = c.ev(
        r"""(() => {
          const blobs = [...document.querySelectorAll('img')].filter(i => (i.src||'').startsWith('blob:')).length;
          const chips = document.querySelectorAll('[data-test-id*="file"], [class*="attachment"], [class*="uploader"]').length;
          return {blobs, chips, bodyHasUpload: /uploaded|attachment|preview/i.test(document.body.innerText.slice(0,2000))};
        })()"""
    )
    print("preview", preview, flush=True)

    # Type prompt
    typed = c.ev(
        f"""((msg) => {{
      const el = document.querySelector('div.ql-editor[contenteditable="true"]')
        || document.querySelector('rich-textarea div[contenteditable="true"]')
        || document.querySelector('div[contenteditable="true"]');
      if (!el) return false;
      el.focus(); el.click();
      document.execCommand('selectAll', false);
      document.execCommand('insertText', false, msg);
      el.dispatchEvent(new InputEvent('input', {{bubbles:true}}));
      return true;
    }})({json.dumps(PROMPT)})"""
    )
    print("typed", typed, flush=True)
    time.sleep(1)
    sent = c.ev(
        r"""(() => {
      const b = document.querySelector('button.send-button')
        || document.querySelector('button[aria-label*="Send"]')
        || [...document.querySelectorAll('button')].find(x => /send/i.test(x.getAttribute('aria-label')||''));
      if (b && !b.disabled) { b.click(); return 'click'; }
      const el = document.querySelector('div[contenteditable="true"]');
      if (el) {
        el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));
        return 'enter';
      }
      return 'fail';
    })()"""
    )
    print("send", sent, flush=True)

    end = time.time() + 240
    last = ""
    stable = 0
    while time.time() < end:
        data = c.ev(
            r"""(() => {
              const body = document.body ? document.body.innerText : '';
              let best = '';
              const nodes = [...document.querySelectorAll('message-content, .model-response-text, .markdown')];
              for (const n of nodes) {
                const t = (n.innerText || '').trim();
                if (t.length > best.length) best = t;
              }
              const idx = body.lastIndexOf('CHECKOUT_PRO:');
              if (idx >= 0) {
                const slice = body.slice(idx, idx + 9000);
                if (slice.length > best.length) best = slice;
              }
              const streaming = !!document.querySelector('button[aria-label*="Stop"]')
                || /stop generating/i.test(body.slice(-300));
              return {text: best, streaming, len: (best||'').length};
            })()"""
        ) or {}
        t = data.get("text") or ""
        if "CHECKOUT_PRO" in t and not data.get("streaming") and len(t) > 120:
            if t == last:
                stable += 1
                if stable >= 3:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(t, encoding="utf-8")
                    print("WROTE", out, len(t), flush=True)
                    print(t[:1600], flush=True)
                    return 0
            else:
                stable = 0
                last = t
                print(f"  ..{len(t)}", flush=True)
        elif t and t != last:
            last = t
            print(f"  ..{len(t)} stream={data.get('streaming')}", flush=True)
        time.sleep(1.4)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(last or "TIMEOUT", encoding="utf-8")
    print("TIMEOUT", len(last), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
