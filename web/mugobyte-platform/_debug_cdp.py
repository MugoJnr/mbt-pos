import json, time, urllib.request, websocket
CDP = "http://127.0.0.1:9222"
tabs = json.loads(urllib.request.urlopen(CDP + "/json/list").read())
tab = next(t for t in tabs if "3c6f4730" in t.get("url", ""))
ws = websocket.create_connection(tab["webSocketDebuggerUrl"])
mid = 0

def call(method, params=None, timeout=30):
    global mid
    mid += 1
    i = mid
    ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
    end = time.time() + timeout
    while time.time() < end:
        ws.settimeout(max(1, end - time.time()))
        d = json.loads(ws.recv())
        if d.get("id") == i:
            return d.get("result", {})
    raise TimeoutError(method)

expr = """
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const expand = document.querySelector('button[aria-label="Expand all folders"]');
  if (expand) expand.click();
  await sleep(1200);
  const items = [];
  const walk = (root) => {
    root.querySelectorAll('[role="treeitem"]').forEach(el => items.push(el));
    root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) walk(el.shadowRoot); });
  };
  walk(document);
  return items.slice(0,8).map(el => ({
    text: el.textContent,
    aria: el.getAttribute('aria-label'),
    path: el.getAttribute('data-path'),
    title: el.getAttribute('title')
  }));
})()
"""
r = call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
print(json.dumps(r.get("result", {}), indent=2))
ws.close()
