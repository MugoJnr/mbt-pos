import json, time, requests, websocket

CDP = 'http://127.0.0.1:9222'
pages = [t for t in requests.get(f'{CDP}/json/list', timeout=5).json() if t.get('type') == 'page']
tab = next((t for t in pages if 'chatgpt.com' in (t.get('url') or '')), None)
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
  const sels = [
    '[data-message-author-role="assistant"]',
    '[data-message-author-role="user"]',
    'article',
    '[data-testid="conversation-turn-3"]',
    '.agent-turn',
    '[class*="markdown"]'
  ];
  const counts = {};
  for (const s of sels) counts[s] = document.querySelectorAll(s).length;
  const arts = Array.from(document.querySelectorAll('article'));
  const texts = arts.slice(-4).map(a => (a.innerText||'').slice(0, 300));
  const roles = Array.from(document.querySelectorAll('[data-message-author-role]')).slice(-6).map(el => ({
    role: el.getAttribute('data-message-author-role'),
    len: (el.innerText||'').length,
    head: (el.innerText||'').slice(0, 120)
  }));
  const body = (document.body.innerText||'').slice(-2500);
  return {counts, texts, roles, bodyTail: body};
})()"""
r = call('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
print(json.dumps((r.get('result') or {}).get('value'), indent=2)[:6000])
