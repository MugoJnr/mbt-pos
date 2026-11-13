import json, time, requests, websocket

CDP = 'http://127.0.0.1:9222'
pages = [t for t in requests.get(f'{CDP}/json/list', timeout=5).json() if t.get('type') == 'page']
tab = next(t for t in pages if t.get('type') == 'page' and 'chatgpt.com' in t.get('url', ''))
ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=30)
i = 0

def call(method, params=None, timeout=30):
    global i
    i += 1
    mid = i
    ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
    end = time.time() + timeout
    while time.time() < end:
        msg = json.loads(ws.recv())
        if msg.get('id') == mid:
            return msg.get('result') or {}
    raise TimeoutError(method)

# Click the recent chat "UI/UX Checkout Rating"
clicked = call('Runtime.evaluate', {
    'expression': r"""(() => {
      const links = Array.from(document.querySelectorAll('a, button, div[role="button"]'));
      const hit = links.find(el => /UI\/UX Checkout Rating|UI\/UX Rating for MBT/i.test(el.innerText||''));
      if (hit) { hit.click(); return hit.innerText.slice(0,80); }
      return null;
    })()""",
    'returnByValue': True,
})
print('clicked', (clicked.get('result') or {}).get('value'))
time.sleep(3)
url = call('Runtime.evaluate', {'expression': 'location.href', 'returnByValue': True})
print('url', (url.get('result') or {}).get('value'))
