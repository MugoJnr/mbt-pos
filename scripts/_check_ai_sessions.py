"""Quick CDP probe: ChatGPT / Claude / Gemini login + upload-limit signals."""
from __future__ import annotations

import json
import time

import requests
import websocket

CDP = "http://127.0.0.1:9222"


def pages():
    return [t for t in requests.get(f"{CDP}/json/list", timeout=5).json() if t.get("type") == "page"]


def ev(ws_url: str, expr: str):
    ws = websocket.create_connection(ws_url, timeout=25)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expr, "returnByValue": True}}))
        end = time.time() + 25
        while time.time() < end:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                if "error" in msg:
                    return {"error": msg["error"]}
                return (msg.get("result") or {}).get("result", {}).get("value")
    finally:
        ws.close()
    return None


EXPR = r"""(() => {
  const body = (document.body && document.body.innerText) || '';
  const head = body.slice(0, 3500);
  const login = /log in|sign in|welcome back|create an account/i.test(head);
  const plus = /Upgrade to Plus|Get Plus|ChatGPT Plus|you've hit the free|Free plan/i.test(body);
  const wait = /wait .{0,12}hours? to upload|upload again|too many files|file uploads? are limited|You've reached/i.test(body);
  const composer = !!document.querySelector('[contenteditable="true"], textarea, rich-textarea, .ProseMirror');
  const planHints = [];
  if (/Plus/i.test(body.slice(0, 4000))) planHints.push('plus_mentioned');
  if (/Free/i.test(body.slice(0, 4000))) planHints.push('free_mentioned');
  return {
    href: location.href.slice(0, 100),
    title: document.title.slice(0, 80),
    login, plus, wait, composer,
    planHints,
    snippet: body.replace(/\s+/g, ' ').slice(0, 280)
  };
})()"""


def main():
    for t in pages():
        u = t.get("url") or ""
        if not any(x in u for x in ("chatgpt.com", "claude.ai", "gemini.google.com")):
            continue
        info = ev(t["webSocketDebuggerUrl"], EXPR)
        print("====", u[:90])
        print(json.dumps(info, indent=2)[:1200])


if __name__ == "__main__":
    main()
