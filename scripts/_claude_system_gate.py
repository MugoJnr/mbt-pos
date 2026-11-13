"""Claude-rate system UI screenshots (tabs/settings/portal) aiming ≥98%."""
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
    up = ROOT / "_qa_full_system_polish" / "desktop_iter24" / "system_upload"
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
        if "claude.ai" in u and "login" not in u.lower():
            tab = t
            break
    if not tab:
        print("NO_CLAUDE")
        return 2
    c = C(tab["webSocketDebuggerUrl"])
    c.call("Runtime.enable")
    c.call("Page.bringToFront")
    c.call("Page.navigate", {"url": "https://claude.ai/new"})
    time.sleep(5)

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
    time.sleep(3)

    typed = c.ev(
        f"""((msg) => {{
      const el = document.querySelector('div[contenteditable=\"true\"]');
      if (!el) return false;
      el.focus(); el.click();
      document.execCommand('insertText', false, msg);
      el.dispatchEvent(new InputEvent('input', {{bubbles:true}}));
      return true;
    }})({json.dumps(PROMPT)})"""
    )
    print("typed", typed, flush=True)
    time.sleep(0.8)
    sent = c.ev(
        r"""(() => {
      const b = document.querySelector('button[aria-label="Send Message"]')
        || document.querySelector('button[aria-label*="Send"]')
        || [...document.querySelectorAll('button')].find(x => /send/i.test(x.getAttribute('aria-label')||''));
      if (b && !b.disabled) { b.click(); return 'click'; }
      return 'fail';
    })()"""
    )
    print("send", sent, flush=True)

    out = ROOT / "_qa_full_system_polish" / "desktop_iter24" / "claude_system_gate.txt"
    end = time.time() + 300
    last = ""
    stable = 0
    while time.time() < end:
        data = c.ev(
            r"""(() => {
              const body = document.body ? document.body.innerText : '';
              let best = '';
              const arts = [...document.querySelectorAll('.font-claude-message, .markdown, [data-is-streaming]')];
              for (const n of arts) {
                const t = (n.innerText || '').trim();
                if (t.length > best.length) best = t;
              }
              const idx = body.lastIndexOf('SETTINGS:');
              if (idx >= 0) {
                const slice = body.slice(idx, idx + 12000);
                if (slice.length > best.length) best = slice;
              }
              const streaming = !!document.querySelector('button[aria-label*="Stop"]');
              return {text: best, streaming, len: (best||'').length};
            })()"""
        ) or {}
        t = data.get("text") or ""
        if "SETTINGS:" in t and "OVERALL_SYSTEM" in t and not data.get("streaming") and len(t) > 150:
            if t == last:
                stable += 1
                if stable >= 3:
                    out.write_text(t, encoding="utf-8")
                    print("WROTE", out, len(t), flush=True)
                    print(t[:1800].encode("ascii", "replace").decode("ascii"), flush=True)
                    return 0
            else:
                stable = 0
                last = t
                print(f"  ..{len(t)}", flush=True)
        elif t and t != last:
            last = t
            print(f"  ..{len(t)} stream={data.get('streaming')}", flush=True)
        time.sleep(1.4)
    out.write_text(last or "TIMEOUT", encoding="utf-8")
    print("TIMEOUT", len(last), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
