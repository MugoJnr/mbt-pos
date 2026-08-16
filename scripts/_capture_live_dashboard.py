#!/usr/bin/env python3
"""Login to shop Live Dashboard and capture authenticated view."""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

import requests
import websocket

CDP = "http://127.0.0.1:9222"
OUT = Path(__file__).resolve().parents[1] / "_qa_full_system_polish" / "web"
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://testshop.mugobyte.com/"
os.environ.setdefault("MBT_QA_ALLOW_DEV_BOOTSTRAP", "1")
from _qa_local_auth import qa_admin_password, qa_admin_user

USER = qa_admin_user()
PASS = qa_admin_password()


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

    def ev(self, expr, await_promise=False):
        r = self.call(
            "Runtime.evaluate",
            {
                "expression": expr,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
        )
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"])[:400])
        return (r.get("result") or {}).get("value")

    def shot(self, path: Path):
        r = self.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
        path.write_bytes(base64.b64decode(r["data"]))
        print("SAVED", path.name, path.stat().st_size, flush=True)


def pages():
    return [
        t
        for t in requests.get(f"{CDP}/json/list", timeout=5).json()
        if t.get("type") == "page"
    ]


def main() -> int:
    tab = None
    for t in pages():
        if "testshop.mugobyte.com" in (t.get("url") or ""):
            tab = t
            break
    if not tab:
        pages_list = pages()
        if not pages_list:
            print("NO_CDP_PAGES", flush=True)
            return 2
        tab = pages_list[0]
    c = C(tab["webSocketDebuggerUrl"])
    c.call("Page.enable")
    c.call("Page.bringToFront")
    c.call("Page.navigate", {"url": URL})
    time.sleep(3.5)

    # Prefer API login + inject session (React controlled inputs ignore .value=)
    token = ""
    user_obj = {}
    try:
        r = requests.post(
            "https://testshop.mugobyte.com/api/auth/login",
            json={"username": USER, "password": PASS},
            timeout=20,
        )
        if r.ok:
            data = r.json() or {}
            token = data.get("token") or ""
            user_obj = data.get("user") or {}
            print("API_LOGIN_OK", bool(token), flush=True)
        else:
            print("API_LOGIN_FAIL", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("API_LOGIN_ERR", e, flush=True)

    if token:
        c.ev(
            f"""(() => {{
              localStorage.setItem('mbt_token', {json.dumps(token)});
              localStorage.setItem('mbt_user', {json.dumps(json.dumps(user_obj))});
              return true;
            }})()"""
        )
        # mbt_user must be JSON string of object
        c.ev(
            f"""(() => {{
              localStorage.setItem('mbt_user', {json.dumps(json.dumps(user_obj))});
              location.href = '/';
              return true;
            }})()"""
        )
        time.sleep(4.0)
    else:
        # Fallback: native value setter for controlled React inputs
        filled = c.ev(
            f"""(() => {{
          const inputs = Array.from(document.querySelectorAll('input'));
          const user = inputs.find(i => /user|email|login/i.test(i.name||'') || /user|email|login/i.test(i.placeholder||'') || i.type==='text')
                    || inputs[0];
          const pass = inputs.find(i => i.type==='password') || inputs[1];
          if (!user || !pass) return 'no-form:' + inputs.length;
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          setter.call(user, {json.dumps(USER)});
          user.dispatchEvent(new Event('input', {{bubbles:true}}));
          setter.call(pass, {json.dumps(PASS)});
          pass.dispatchEvent(new Event('input', {{bubbles:true}}));
          const btn = Array.from(document.querySelectorAll('button')).find(b => /sign\\s*in|login|log\\s*in/i.test(b.textContent||''));
          if (btn) btn.click();
          return 'ok';
        }})()"""
        )
        print("LOGIN_FILL", filled, flush=True)
        time.sleep(4.5)

    body = c.ev("document.body ? document.body.innerText.slice(0,500) : ''") or ""
    print("BODY", body[:240].replace("\n", " | "), flush=True)
    # Wait for live content if still on login
    if "Invalid credentials" in body or "Sign in" in body and "Gross" not in body:
        for _ in range(8):
            time.sleep(1.0)
            body = c.ev("document.body ? document.body.innerText.slice(0,500) : ''") or ""
            if "SIGN IN" not in body.upper() or "Live" in body:
                break
    c.shot(OUT / "live_dashboard.png")
    c.shot(OUT / "live_testshop_mugobyte_com.png")
    (OUT / "live_dashboard_status.txt").write_text(
        f"Live dashboard https://testshop.mugobyte.com/\napi_token={bool(token)}\nbody_snip={body[:400]}\n",
        encoding="utf-8",
    )
    return 0 if token or "Invalid credentials" not in body else 1


if __name__ == "__main__":
    raise SystemExit(main())
