import json, time, requests, websocket

CDP = 'http://127.0.0.1:9222'
pages = [t for t in requests.get(f'{CDP}/json/list', timeout=5).json() if t.get('type') == 'page']
tab = next((t for t in pages if 'chatgpt.com' in (t.get('url') or '')), None)
print('tab', (tab or {}).get('title'), (tab or {}).get('url', '')[:90])
if not tab:
    raise SystemExit(2)
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
            if 'error' in msg:
                raise RuntimeError(msg['error'])
            return msg.get('result') or {}
    raise TimeoutError(method)

expr = r"""(() => {
  const arts = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
  const last = arts.length ? (arts[arts.length-1].innerText || '') : '';
  const stop = !!document.querySelector('button[data-testid="stop-button"], button[aria-label="Stop streaming"]');
  const el = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable="true"]');
  const composer = el ? (el.innerText || '') : '';
  return {
    n: arts.length,
    stop,
    lastLen: last.length,
    lastHead: last.slice(0, 800),
    lastTail: last.slice(-800),
    composer: composer.slice(0, 240)
  };
})()"""
r = call('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
val = (r.get('result') or {}).get('value')
print(json.dumps(val, indent=2)[:4000])
