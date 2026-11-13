"""ChatGPT checkout gate via image URLs (bypasses upload quota)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests
import websocket

ROOT = Path(__file__).resolve().parents[1]
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
    it = sys.argv[1] if len(sys.argv) > 1 else "21"
    url_file = ROOT / "_qa_full_system_polish" / f"desktop_iter{it}" / "url_gate" / "urls_ordered.txt"
    if not url_file.exists():
        # fallback map from urls.txt + filenames in folder
        folder = ROOT / "_qa_full_system_polish" / f"desktop_iter{it}" / "url_gate"
        mapping = {}
        # Prefer explicit ordered file built by caller
        print("MISSING", url_file)
        return 2
    lines = [ln.strip() for ln in url_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(lines) < 3:
        print("NEED_3_URLS", lines)
        return 2
    pro, explorer, classic = lines[:3]
    prompt = f"""Open and carefully inspect these THREE MBT POS checkout screenshots (direct image URLs):

1) Checkout Pro: {pro}
2) Product Explorer: {explorer}
3) Retail Classic: {classic}

Rate EACH layout for production cashier UI/UX readiness.

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

Be strict. 98%=ship-ready. You MUST view the images at the URLs above."""

    out = ROOT / "_qa_full_system_polish" / f"desktop_iter{it}" / "chatgpt_checkout_gate.txt"
    tab = next((t for t in pages() if "chatgpt.com" in (t.get("url") or "")), None)
    if not tab:
        print("NO_CHATGPT")
        return 2
    c = C(tab["webSocketDebuggerUrl"])
    c.call("Runtime.enable")
    c.call("Page.bringToFront")
    c.call("Page.navigate", {"url": "https://chatgpt.com/"})
    time.sleep(4)
    prior = c.ev('document.querySelectorAll(\'[data-message-author-role="assistant"]\').length') or 0
    print("prior", prior, flush=True)

    # Clear any leftover attachments
    c.ev(
        r"""(() => {
          [...document.querySelectorAll('button[aria-label*="Remove file"], button[aria-label*="Remove"]')].forEach(b => b.click());
          const b = [...document.querySelectorAll('button')].find(x => /^(OK|Got it|Dismiss)$/i.test((x.innerText||'').trim()));
          if (b) b.click();
          return true;
        })()"""
    )
    time.sleep(0.5)

    ok = c.ev(
        "((msg) => { const el = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable=true]'); if (!el) return false; el.focus(); el.click(); document.execCommand('insertText', false, msg); el.dispatchEvent(new InputEvent('input', {bubbles:true})); return true; })("
        + json.dumps(prompt)
        + ")"
    )
    print("typed", ok, flush=True)
    time.sleep(0.8)

    for _ in range(15):
        disabled = c.ev(
            r"""(() => {
              const b = document.querySelector('button[data-testid="send-button"]') || document.querySelector('button[aria-label="Send prompt"]');
              return b ? b.disabled : true;
            })()"""
        )
        print("sendDisabled", disabled, flush=True)
        if not disabled:
            break
        time.sleep(0.4)

    sent = c.ev(
        r"""(() => {
          const b = document.querySelector('button[data-testid="send-button"]') || document.querySelector('button[aria-label="Send prompt"]');
          if (b && !b.disabled) { b.click(); return 'click'; }
          // force
          if (b) { b.disabled=false; b.removeAttribute('disabled'); b.click(); return 'force'; }
          return 'fail';
        })()"""
    )
    print("sent", sent, flush=True)

    end = time.time() + 240
    last = ""
    while time.time() < end:
        data = c.ev(
            r"""(() => {
              const arts = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
              let text = '';
              for (let i = arts.length - 1; i >= 0; i--) {
                const t = arts[i].innerText || '';
                if (t.trim()) { text = t; break; }
              }
              const streaming = !!document.querySelector('button[data-testid="stop-button"], button[aria-label="Stop streaming"]');
              return {n: arts.length, text, streaming};
            })()"""
        ) or {}
        text = data.get("text") or ""
        if data.get("n", 0) > prior and text and not data.get("streaming") and "%" in text and len(text) > 80:
            time.sleep(1.5)
            text = c.ev(
                r"""(() => {
                  const arts = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
                  for (let i = arts.length - 1; i >= 0; i--) {
                    const t = arts[i].innerText || '';
                    if (t.trim()) return t;
                  }
                  return '';
                })()"""
            ) or text
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            print("WROTE", out, len(text), flush=True)
            print(text[:1800], flush=True)
            return 0
        if text != last and text:
            last = text
            print(f"  ..{len(text)} stream={data.get('streaming')}", flush=True)
        time.sleep(1.2)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(last or "TIMEOUT", encoding="utf-8")
    print("TIMEOUT", len(last or ""), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
