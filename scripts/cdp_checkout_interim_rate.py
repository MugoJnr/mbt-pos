"""Rate three checkout layouts via Gemini or Claude using CDP file attach."""
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


def pages():
    return [t for t in requests.get(f"{CDP}/json/list", timeout=5).json() if t.get("type") == "page"]


def find(target: str):
    if target == "gemini":
        for t in pages():
            if "gemini.google.com" in (t.get("url") or ""):
                return t
    else:
        for pref in ("claude.ai/new", "claude.ai/chat", "claude.ai"):
            for t in pages():
                u = t.get("url") or ""
                if pref in u and "login" not in u.lower():
                    return t
    return None


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


def prepare_images(it: str):
    folder = ROOT / "_qa_checkout_pro_design" / f"iter_{it}"
    up = ROOT / "_qa_full_system_polish" / f"desktop_iter{it}" / "interim_upload"
    up.mkdir(parents=True, exist_ok=True)
    stamp_id = str(int(time.time()))
    imgs = []
    for name, label in (
        ("checkout_pro.png", "PRO"),
        ("product_explorer.png", "EXPLORER"),
        ("retail_classic.png", "CLASSIC"),
    ):
        d = up / f"{label.lower()}_{stamp_id}.jpg"
        stamp(folder / name, d, f"{label}-{stamp_id}")
        imgs.append(d)
    return imgs


def attach_files(c: C, paths: list[Path]):
    c.ev(
        """(() => {
      let inp = document.querySelector('#mbt-up');
      if (!inp) {
        inp = document.createElement('input');
        inp.type = 'file';
        inp.id = 'mbt-up';
        inp.accept = 'image/*';
        inp.multiple = true;
        inp.style.display = 'block';
        document.body.appendChild(inp);
      }
      return true;
    })()"""
    )
    c.call("DOM.enable")
    doc = c.call("DOM.getDocument", {"depth": 1})
    root = doc["root"]["nodeId"]
    ids = c.call("DOM.querySelectorAll", {"nodeId": root, "selector": "input[type=file]"}).get("nodeIds") or []
    abs_paths = [str(p.resolve()) for p in paths]
    print("inputs", len(ids), flush=True)
    for nid in ids:
        try:
            c.call("DOM.setFileInputFiles", {"nodeId": nid, "files": abs_paths})
        except Exception as e:
            print("set fail", e, flush=True)
    time.sleep(2.5)


def type_prompt(c: C, target: str):
    if target == "gemini":
        sel = 'div.ql-editor[contenteditable="true"], rich-textarea div[contenteditable="true"], div[contenteditable="true"]'
    else:
        sel = 'div[contenteditable="true"], [data-testid="chat-input"], p[data-placeholder]'
    ok = c.ev(
        f"""((msg) => {{
      const el = document.querySelector({json.dumps(sel.split(',')[0].strip())})
        || document.querySelector('div[contenteditable="true"]');
      if (!el) return false;
      el.focus(); el.click();
      document.execCommand('insertText', false, msg);
      el.dispatchEvent(new InputEvent('input', {{bubbles:true}}));
      return true;
    }})({json.dumps(PROMPT)})"""
    )
    print("typed", ok, flush=True)
    time.sleep(0.6)
    sent = c.ev(
        r"""(() => {
      const b = document.querySelector('button[aria-label="Send Message"]')
        || document.querySelector('button[aria-label*="Send"]')
        || document.querySelector('button.send-button')
        || document.querySelector('button[data-testid="send-button"]')
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


def wait_reply(c: C, out: Path, timeout=240):
    end = time.time() + timeout
    last = ""
    stable = 0
    while time.time() < end:
        data = c.ev(
            r"""(() => {
              const body = document.body ? document.body.innerText : '';
              let best = '';
              const arts = [...document.querySelectorAll(
                '[data-message-author-role="assistant"], .font-claude-message, .markdown, message-content, .model-response-text'
              )];
              for (const n of arts) {
                const t = (n.innerText || '').trim();
                if (t.length > best.length) best = t;
              }
              if (!best || best.length < 80) {
                const idx = body.lastIndexOf('CHECKOUT_PRO:');
                if (idx >= 0) best = body.slice(idx, idx + 9000);
                else {
                  const s = body.lastIndexOf('SCORE:');
                  if (s >= 0) best = body.slice(s, s + 9000);
                }
              }
              const streaming = !!document.querySelector(
                'button[aria-label*="Stop"], button[data-testid="stop-button"]'
              ) || /stop (response|generating)/i.test(body.slice(-400));
              return {text: best, streaming, len: best.length};
            })()"""
        ) or {}
        t = data.get("text") or ""
        if ("CHECKOUT_PRO" in t or "SCORE:" in t) and not data.get("streaming") and len(t) > 120:
            if t == last:
                stable += 1
                if stable >= 3:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(t, encoding="utf-8")
                    print("WROTE", out, len(t), flush=True)
                    print(t[:1500], flush=True)
                    return 0
            else:
                stable = 0
                last = t
                print(f"  ..{len(t)}", flush=True)
        elif t and t != last:
            last = t
            print(f"  ..{len(t)} stream={data.get('streaming')}", flush=True)
        time.sleep(1.3)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(last or "TIMEOUT", encoding="utf-8")
    print("TIMEOUT", len(last), flush=True)
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["gemini", "claude"], required=True)
    ap.add_argument("--iter", default="21")
    args = ap.parse_args()
    out = ROOT / "_qa_full_system_polish" / f"desktop_iter{args.iter}" / f"{args.target}_checkout_interim.txt"
    imgs = prepare_images(args.iter)
    tab = find(args.target)
    if not tab:
        print("NO_TAB", args.target)
        return 2
    print("TAB", tab.get("title"), tab.get("url"), flush=True)
    c = C(tab["webSocketDebuggerUrl"])
    c.call("Runtime.enable")
    c.call("Page.bringToFront")
    if args.target == "claude" and "claude.ai/new" not in (tab.get("url") or ""):
        c.call("Page.navigate", {"url": "https://claude.ai/new"})
        time.sleep(4)
    attach_files(c, imgs)
    type_prompt(c, args.target)
    return wait_reply(c, out)


if __name__ == "__main__":
    raise SystemExit(main())
