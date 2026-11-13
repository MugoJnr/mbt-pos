"""Capture portal + live dashboard screenshots via CDP Page.captureScreenshot."""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

import requests
import websocket

CDP = 'http://127.0.0.1:9222'
OUT = Path(r'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\_qa_full_system_polish\web')
OUT.mkdir(parents=True, exist_ok=True)


def pages():
    return [t for t in requests.get(f'{CDP}/json/list', timeout=5).json() if t.get('type') == 'page']


class C:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, timeout=30)
        self.i = 0

    def call(self, method, params=None, timeout=60):
        self.i += 1
        mid = self.i
        self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            msg = json.loads(self.ws.recv())
            if msg.get('id') == mid:
                if 'error' in msg:
                    raise RuntimeError(msg['error'])
                return msg.get('result') or {}
        raise TimeoutError(method)

    def ev(self, expr, await_promise=False):
        r = self.call(
            'Runtime.evaluate',
            {
                'expression': expr,
                'returnByValue': True,
                'awaitPromise': await_promise,
            },
        )
        if r.get('exceptionDetails'):
            raise RuntimeError(str(r['exceptionDetails'])[:400])
        return (r.get('result') or {}).get('value')

    def shot(self, path: Path):
        r = self.call('Page.captureScreenshot', {'format': 'png', 'fromSurface': True})
        data = base64.b64decode(r['data'])
        path.write_bytes(data)
        print('SAVED', path.name, len(data), flush=True)


def main():
    # Prefer existing portal tab
    tab = None
    for t in pages():
        if 'portal.mugobyte.com' in (t.get('url') or ''):
            tab = t
            break
    if not tab:
        # open new via /json/new
        tab = requests.get(f'{CDP}/json/new?https://portal.mugobyte.com/license', timeout=10).json()
    c = C(tab['webSocketDebuggerUrl'])
    c.call('Page.enable')
    c.call('Page.bringToFront')

    targets = [
        ('portal_license.png', 'https://portal.mugobyte.com/license'),
        ('portal_dashboard.png', 'https://portal.mugobyte.com/dashboard'),
        ('portal_login.png', 'https://portal.mugobyte.com/login'),
    ]
    for name, url in targets:
        c.call('Page.navigate', {'url': url})
        time.sleep(3.5)
        c.shot(OUT / name)

    # Try shop live dashboard (tunnel subdomain from web_config when known)
    shop = None
    for host in (
        'testshop.mugobyte.com',
        'demo.mugobyte.com',
        'live.mugobyte.com',
        'app.mugobyte.com',
    ):
        try:
            r = requests.get(f'https://{host}/', timeout=4)
            if r.status_code < 500:
                shop = host
                break
        except Exception:
            pass
    if shop:
        c.call('Page.navigate', {'url': f'https://{shop}/'})
        time.sleep(5)
        c.shot(OUT / f'live_{shop.replace(".", "_")}.png')
        status = f'Captured live dashboard https://{shop}/\n'
        try:
            (OUT / 'live_dashboard_status.txt').write_text(status, encoding='utf-8')
        except PermissionError:
            (OUT / 'live_dashboard_status_new.txt').write_text(status, encoding='utf-8')
        print('LIVE', shop, flush=True)
    else:
        msg = (
            'No public shop host responded. Live dashboard is tunnel-served per shop; '
            'polish code under web/dashboard-ui. Portal screenshots captured.\n'
        )
        try:
            (OUT / 'live_dashboard_status.txt').write_text(msg, encoding='utf-8')
        except PermissionError:
            (OUT / 'live_dashboard_status_new.txt').write_text(msg, encoding='utf-8')
        print('NO_LIVE_SHOP', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
