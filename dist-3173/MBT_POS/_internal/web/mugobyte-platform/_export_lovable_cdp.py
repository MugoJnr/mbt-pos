"""Export Lovable MBT Cloud Canvas via Chrome CDP (shadow DOM aware)."""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

import websocket

PROJECT_URL = "https://lovable.dev/projects/3c6f4730-7ce5-4853-a8d6-e87af65334e7?view=codeEditor"
CDP = "http://127.0.0.1:9222"
OUT = Path(__file__).resolve().parent
MANIFEST = OUT / "MANIFEST.json"

EXTRACT_JS = r"""
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  const walk = (root, out = []) => {
    root.querySelectorAll('[role="treeitem"]').forEach(el => out.push(el));
    root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) walk(el.shadowRoot, out); });
    return out;
  };

  const allLines = () => {
    const lines = [];
    const collect = root => {
      root.querySelectorAll('.cm-content .cm-line, .cm-line').forEach(l => lines.push(l));
      root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) collect(el.shadowRoot); });
    };
    collect(document);
    return lines;
  };

  const allGutters = () => {
    const g = [];
    const collect = root => {
      root.querySelectorAll('.cm-gutterElement').forEach(x => g.push(x));
      root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) collect(el.shadowRoot); });
    };
    collect(document);
    return g;
  };

  const scroller = () => {
    let s = null;
    const find = root => {
      root.querySelectorAll('.cm-scroller').forEach(x => { s = x; });
      root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) find(el.shadowRoot); });
    };
    find(document);
    return s;
  };

  const expand = document.querySelector('button[aria-label="Expand all folders"]');
  if (expand) expand.click();
  await sleep(1200);

  const exts = ['.tsx', '.ts', '.css', '.json', '.js', '.md', '.toml'];
  const items = walk(document);
  const files = [...new Set(items.map(el => el.getAttribute('aria-label') || '').filter(Boolean))]
    .filter(n => exts.some(e => n.endsWith(e)) || n === 'AGENTS.md');

  const results = [];
  for (const name of files) {
    const matches = items.filter(el => (el.getAttribute('aria-label') || '') === name);
    if (!matches.length) {
      results.push({ name, error: 'not found' });
      continue;
    }
    matches[0].click();
    await sleep(450);

    let rel = name;
    document.querySelectorAll('[role="tab"][aria-selected="true"]').forEach(t => {
      const tx = t.textContent?.trim();
      if (tx && tx !== 'Code') rel = tx;
    });
    document.querySelectorAll('*').forEach(el => {
      if (!el.shadowRoot) return;
      el.shadowRoot.querySelectorAll('[role="tab"][aria-selected="true"]').forEach(t => {
        const tx = t.textContent?.trim();
        if (tx && tx !== 'Code') rel = tx;
      });
    });

    const map = new Map();
    const scroll = scroller();
    if (scroll) {
      scroll.scrollTop = 0;
      await sleep(100);
      let unchanged = 0;
      while (unchanged < 5) {
        const gutters = allGutters();
        const lines = allLines();
        gutters.forEach((g, i) => {
          const n = parseInt(g.textContent, 10);
          if (n && lines[i]) map.set(n, lines[i].textContent);
        });
        const prev = scroll.scrollTop;
        scroll.scrollTop += 320;
        await sleep(45);
        if (scroll.scrollTop === prev) unchanged++; else unchanged = 0;
      }
    }
    const keys = [...map.keys()].sort((a, b) => a - b);
    let content = keys.map(k => map.get(k)).join('\n');
    if (!content) content = allLines().map(l => l.textContent).join('\n');
    results.push({ name, path: rel, bytes: content.length, content });
  }
  return { count: results.length, files: results };
})()
"""


class Cdp:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, suppress_origin=True)
        self._id = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 180.0) -> dict:
        self._id += 1
        msg_id = self._id
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.ws.settimeout(max(1.0, deadline - time.time()))
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            data = json.loads(raw)
            if data.get("id") != msg_id:
                continue
            if "error" in data:
                raise RuntimeError(data["error"])
            return data.get("result", {})
        raise TimeoutError(method)

    def evaluate(self, expression: str) -> object:
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout=600.0,
        )
        r = result.get("result", {})
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"])
        return r.get("value")

    def close(self) -> None:
        self.ws.close()


def get_lovable_page() -> dict:
    tabs = json.loads(urllib.request.urlopen(f"{CDP}/json/list").read())
    for t in tabs:
        if "3c6f4730-7ce5-4853-a8d6-e87af65334e7" in t.get("url", ""):
            return t
    return json.loads(
        urllib.request.urlopen(
            urllib.request.Request(f"{CDP}/json/new?{PROJECT_URL}", method="PUT")
        ).read()
    )


def save(rel: str, content: str, manifest: dict) -> None:
    rel = rel.replace("\\", "/").lstrip("/")
    if not rel or rel == "Code":
        return
    dest = OUT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8", newline="\n")
    manifest[rel] = len(content.encode("utf-8"))


def main() -> None:
    manifest: dict[str, int] = {}
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    tab = get_lovable_page()
    cdp = Cdp(tab["webSocketDebuggerUrl"])
    try:
        cdp.call("Runtime.enable")
        if PROJECT_URL not in tab.get("url", ""):
            cdp.call("Page.navigate", {"url": PROJECT_URL})
            time.sleep(12)
        else:
            time.sleep(2)

        for _ in range(40):
            ready = cdp.evaluate(
                '!!document.querySelector(\'button[aria-label="Expand all folders"]\')'
            )
            if ready:
                break
            time.sleep(2)
        else:
            raise SystemExit("Lovable code tree did not load in Chrome.")

        data = cdp.evaluate(EXTRACT_JS)
        if not isinstance(data, dict):
            raise SystemExit(f"Unexpected payload: {data!r}")

        ok = 0
        for item in data.get("files", []):
            if item.get("error"):
                print("SKIP", item["name"], item["error"])
                continue
            path = item.get("path") or item.get("name")
            content = item.get("content") or ""
            if not content.strip():
                print("EMPTY", path)
                continue
            save(path, content, manifest)
            ok += 1
            print("OK", path, len(content))

        MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Done — {ok} files saved ({len(manifest)} in manifest)")
    finally:
        cdp.close()


if __name__ == "__main__":
    main()
