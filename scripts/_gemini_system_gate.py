"""Gemini interim rate of system UI screenshots (while Claude cooldown)."""
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
PROMPT = """NEW screenshots attached (ignore colored QA borders). Order:
1 Settings tab
2 Sales tab (product grid shell — not checkout score)
3 Inventory tab
4 Dashboard tab
5 Debt Management tab
6 Finance / Accounting tab
7 Reports tab
8 Notes tab
9 Users & Access tab
10 Portal dashboard (web)
11 Portal license (web)

Rate MBT POS non-checkout system UI polish for production ship.
Checkout layouts are gated separately — do NOT score cart/Complete Sale chrome here.

Focus especially on:
- KPI left-border accent semantics (green=cash, gold=neutral, amber=attention, red=risk)
- Cross-screen figure agreement (Today's Revenue / Outstanding Debt)
- Inventory ⋮ actions + footer strip
- Portal vs desktop MugoByte navy+gold brand cohesion

Respond EXACTLY:
SETTINGS: <0-100>%
SALES_TAB_SHELL: <0-100>%
INVENTORY: <0-100>%
DASHBOARD: <0-100>%
DEBT: <0-100>%
FINANCE: <0-100>%
REPORTS: <0-100>%
NOTES: <0-100>%
USERS: <0-100>%
PORTAL_DASHBOARD: <0-100>%
PORTAL_LICENSE: <0-100>%
OVERALL_SYSTEM: <0-100>%

IMPROVED:
- ...

REMAINING (must-fix before 98%):
1. ...

NEXT FIXES (top 5 concrete UI only):
1. ...

Be strict. 98%=ship-ready for non-checkout surfaces."""


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


def main():
    sys_dir = ROOT / "_qa_full_system_polish" / "desktop_iter24" / "system"
    web_dir = ROOT / "_qa_full_system_polish" / "web"
    up = ROOT / "_qa_full_system_polish" / "desktop_iter24" / "system_upload_gemini"
    up.mkdir(parents=True, exist_ok=True)
    stamp_id = str(int(time.time()))
    imgs = []
    for i, (src, label) in enumerate(
        (
            (sys_dir / "tab_settings.png", "SETTINGS"),
            (sys_dir / "tab_sales.png", "SALES"),
            (sys_dir / "tab_inventory.png", "INVENTORY"),
            (sys_dir / "tab_dashboard.png", "DASHBOARD"),
            (sys_dir / "tab_debt.png", "DEBT"),
            (sys_dir / "tab_accounting.png", "FINANCE"),
            (sys_dir / "tab_reports.png", "REPORTS"),
            (sys_dir / "tab_notes.png", "NOTES"),
            (sys_dir / "tab_admin.png", "USERS"),
            (web_dir / "portal_dashboard.png", "PORTAL_DASH"),
            (web_dir / "portal_license.png", "PORTAL_LIC"),
        ),
        start=1,
    ):
        if not src.exists():
            print("MISSING", src)
            return 2
        d = up / f"{i}_{label.lower()}_{stamp_id}.jpg"
        stamp(src, d, f"{label}-{stamp_id}-{i}")
        imgs.append(d)

    tab = None
    for t in pages():
        u = t.get("url") or ""
        if "gemini.google.com" in u and "accounts.google.com" not in u:
            tab = t
            break
    if not tab:
        print("NO_GEMINI")
        return 2
    c = C(tab["webSocketDebuggerUrl"])
    c.call("Runtime.enable")
    c.call("Page.bringToFront")
    c.call("Page.navigate", {"url": "https://gemini.google.com/app"})
    time.sleep(6)

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
    abs_paths = [str(p.resolve()) for p in imgs]
    print("inputs", len(ids), "files", len(abs_paths), flush=True)
    for nid in ids:
        try:
            c.call("DOM.setFileInputFiles", {"nodeId": nid, "files": abs_paths})
        except Exception as e:
            print("setfail", e, flush=True)
    time.sleep(4)

    typed = c.ev(
        f"""((msg) => {{
      const el = document.querySelector('div[contenteditable=\"true\"], rich-textarea div[contenteditable], .ql-editor')
        || document.querySelector('[role=\"textbox\"]');
      if (!el) return false;
      el.focus(); el.click();
      document.execCommand('insertText', false, msg);
      el.dispatchEvent(new InputEvent('input', {{bubbles:true}}));
      return true;
    }})({json.dumps(PROMPT)})"""
    )
    print("typed", typed, flush=True)
    time.sleep(1.0)
    sent = c.ev(
        r"""(() => {
      const b = document.querySelector('button[aria-label*="Send"]')
        || [...document.querySelectorAll('button')].find(x => /send/i.test(x.getAttribute('aria-label')||'') || /send/i.test(x.textContent||''));
      if (b && !b.disabled) { b.click(); return 'click'; }
      return 'fail';
    })()"""
    )
    print("sent", sent, flush=True)

    out = ROOT / "_qa_full_system_polish" / "desktop_iter24" / "gemini_system_gate.txt"
    end = time.time() + 240
    last = ""
    while time.time() < end:
        time.sleep(4)
        txt = c.ev(
            r"""(() => {
              const nodes = [...document.querySelectorAll('[data-message-author-role], message-content, .model-response-text, .response-content')];
              const t = nodes.map(n => n.innerText || '').filter(Boolean).join('\n---\n');
              return t.slice(-12000);
            })()"""
        ) or ""
        if txt and txt != last:
            print(f"  ... gemini {len(txt)} chars", flush=True)
            last = txt
        if "OVERALL_SYSTEM:" in txt and "%" in txt:
            out.write_text(txt, encoding="utf-8")
            print("SAVED", out, flush=True)
            return 0
    if last:
        out.write_text(last, encoding="utf-8")
        print("PARTIAL", out, flush=True)
        return 0
    print("NO_REPLY")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
