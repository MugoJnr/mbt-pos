"""Upload image to Claude via CDP and request SCORE."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests
import websocket

CDP = 'http://127.0.0.1:9222'
IMG = Path(r'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\_qa_checkout_pro_design\iter_5\checkout_pro.png')
OUT = Path(r'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\_qa_full_system_polish\desktop_iter5\claude_rate.txt')
PROMPT = """Latest MBT POS Checkout Pro screenshot (iter5 density pass).

Rate for production cashier POS readiness.

Respond EXACTLY:
SCORE: <0-100>%
IMPROVED:
- ...
REMAINING PROBLEMS (prioritized, actionable):
1. ...
NEXT FIXES (top 5):
1. ...

Be strict. 98%+ means ship-ready. Focus clipping, empty-state ghosts, payment vs transaction clarity, discount consistency, density."""


def pages():
    return [t for t in requests.get(f'{CDP}/json/list', timeout=5).json() if t.get('type') == 'page']


class C:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, timeout=30)
        self.i = 0

    def call(self, method, params=None, timeout=90):
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

    def ev(self, expr):
        r = self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
        if r.get('exceptionDetails'):
            raise RuntimeError(str(r['exceptionDetails'])[:400])
        return (r.get('result') or {}).get('value')


def main():
    tab = None
    for t in pages():
        u = t.get('url') or ''
        if 'claude.ai/chat' in u:
            tab = t
            break
    if not tab:
        for t in pages():
            u = (t.get('url') or '').lower()
            if 'claude.ai' in u and 'login' not in u:
                tab = t
                break
    if not tab:
        OUT.write_text('NO_CLAUDE_TAB\n', encoding='utf-8')
        print('NO_CLAUDE_TAB')
        return 2
    print('TAB', tab.get('title'), flush=True)
    c = C(tab['webSocketDebuggerUrl'])
    c.call('Runtime.enable')
    c.call('DOM.enable')
    c.call('Page.bringToFront')

    img = str(IMG.resolve())
    c.ev("""
(() => {
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
})()""")
    doc = c.call('DOM.getDocument', {'depth': 1})
    root = doc['root']['nodeId']
    ids = c.call('DOM.querySelectorAll', {'nodeId': root, 'selector': 'input[type=file]'}).get('nodeIds') or []
    print('inputs', len(ids), flush=True)
    for nid in ids:
        try:
            c.call('DOM.setFileInputFiles', {'nodeId': nid, 'files': [img]})
        except Exception as e:
            print('set fail', e, flush=True)
    time.sleep(1.5)
    # Click attach / plus if needed then also try composer paste path
    c.ev(r"""
(() => {
  const el = document.querySelector('div[contenteditable="true"]')
    || document.querySelector('[data-testid="chat-input"]')
    || document.querySelector('p[data-placeholder]');
  if (el) { el.focus(); el.click(); return true; }
  return false;
})()""")
    ok = c.ev('((msg) => { const el = document.querySelector("div[contenteditable=true]"); if (!el) return false; el.focus(); document.execCommand("insertText", false, msg); return true; })(' + json.dumps(PROMPT) + ')')
    print('typed', ok, flush=True)
    time.sleep(0.6)
    sent = c.ev(r"""
(() => {
  const b = document.querySelector('button[aria-label="Send Message"]')
    || document.querySelector('button[aria-label*="Send"]');
  if (b && !b.disabled) { b.click(); return true; }
  return false;
})()""")
    print('send', sent, flush=True)
    end = time.time() + 200
    last = ''
    stable = 0
    while time.time() < end:
        data = c.ev(r"""
(() => {
  const body = document.body ? document.body.innerText : '';
  const idx = Math.max(body.lastIndexOf('SCORE:'), body.lastIndexOf('Score:'));
  let best = idx >= 0 ? body.slice(idx, idx + 8000) : '';
  const streaming = !!document.querySelector('[data-is-streaming="true"], button[aria-label*="Stop"]');
  return {best, streaming, len: best.length};
})()""") or {}
        t = data.get('best') or ''
        if 'SCORE' in t.upper() and '%' in t and not data.get('streaming'):
            if t == last:
                stable += 1
                if stable >= 3 and len(t) > 100:
                    break
            else:
                stable = 0
                last = t
                print('..', len(t), flush=True)
        elif t and t != last:
            last = t
            print('..', len(t), 'stream', data.get('streaming'), flush=True)
        time.sleep(1.2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(last or 'EMPTY', encoding='utf-8')
    print('WROTE', len(last or ''), flush=True)
    print((last or '')[:900], flush=True)
    return 0 if last and 'SCORE' in last.upper() else 1


if __name__ == '__main__':
    raise SystemExit(main())
