"""Drive Eugene Chrome (CDP :9222) to open Gmail verify/reset links."""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request

try:
    import websocket  # type: ignore
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'websocket-client', '-q'])
    import websocket  # type: ignore


CDP_BASE = 'http://localhost:9222'


def http_json(url: str, method: str = 'GET'):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def pages():
    return [t for t in http_json(f'{CDP_BASE}/json/list') if t.get('type') == 'page']


def find_page(substr: str):
    for t in pages():
        blob = (t.get('url') or '') + ' ' + (t.get('title') or '')
        if substr.lower() in blob.lower():
            return t
    return None


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=30)
        self.id = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 30):
        self.id += 1
        msg = {'id': self.id, 'method': method}
        if params:
            msg['params'] = params
        self.ws.send(json.dumps(msg))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self.ws.recv()
            data = json.loads(raw)
            if data.get('id') == self.id:
                if 'error' in data:
                    raise RuntimeError(data['error'])
                return data.get('result') or {}
        raise TimeoutError(method)

    def eval(self, expression: str):
        return self.call('Runtime.evaluate', {
            'expression': expression,
            'returnByValue': True,
            'awaitPromise': True,
        }).get('result', {})

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def ensure_gmail() -> dict:
    p = find_page('mail.google.com')
    if not p:
        http_json('http://localhost:9222/json/new?https://mail.google.com/mail/u/0/#inbox', 'PUT')
        time.sleep(3)
        p = find_page('mail.google.com')
    if not p:
        raise SystemExit('Gmail tab not found')
    return p


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'scan'
    if cmd == 'scan':
        for t in pages():
            print(f"{t.get('id')}|{t.get('title')}|{t.get('url')}")
        return

    gmail = ensure_gmail()
    cdp = CDP(gmail['webSocketDebuggerUrl'])
    try:
        if cmd == 'search_verify':
            cdp.call('Page.navigate', {
                'url': 'https://mail.google.com/mail/u/0/#search/from%3A(mugobyte.com+OR+resend)+subject%3A(Verify+OR+Confirm)'
            })
            time.sleep(5)
            print(cdp.eval('document.title').get('value'))
            # Click first result row if present
            clicked = cdp.eval("""
(() => {
  const rows = [...document.querySelectorAll('tr.zA')];
  if (!rows.length) return 'no-rows';
  rows[0].click();
  return 'clicked:' + (rows[0].innerText || '').slice(0,120).replace(/\\s+/g,' ');
})()
""").get('value')
            print('CLICK', clicked)
            time.sleep(3)
            href = cdp.eval("""
(() => {
  const links = [...document.querySelectorAll('a')].map(a => a.href).filter(h =>
    h && (h.includes('auth/callback') || h.includes('verify') || h.includes('token') || h.includes('supabase.co/auth'))
  );
  return links[0] || '';
})()
""").get('value')
            print('HREF', href)
            if href:
                http_json('http://localhost:9222/json/new?' + urllib.parse.quote(href, safe=''), 'PUT')
                print('OPENED', href[:120])
            return

        if cmd == 'search_reset':
            cdp.call('Page.navigate', {
                'url': 'https://mail.google.com/mail/u/0/#search/subject%3A%22Reset+your+MugoByte%22'
            })
            time.sleep(5)
            clicked = cdp.eval("""
(() => {
  const rows = [...document.querySelectorAll('tr.zA')];
  if (!rows.length) return 'no-rows';
  rows[0].click();
  return 'clicked:' + (rows[0].innerText || '').slice(0,120).replace(/\\s+/g,' ');
})()
""").get('value')
            print('CLICK', clicked)
            time.sleep(3)
            href = cdp.eval("""
(() => {
  const links = [...document.querySelectorAll('a')].map(a => a.href).filter(h =>
    h && (h.includes('reset-password') || h.includes('recovery') || h.includes('supabase.co/auth') || h.includes('type=recovery'))
  );
  return links[0] || '';
})()
""").get('value')
            print('HREF', href)
            if href:
                http_json('http://localhost:9222/json/new?' + urllib.parse.quote(href, safe=''), 'PUT')
                print('OPENED', href[:120])
            return

        if cmd == 'body':
            print(cdp.eval('document.body.innerText.slice(0,1500)').get('value'))
            return
    finally:
        cdp.close()


if __name__ == '__main__':
    main()
