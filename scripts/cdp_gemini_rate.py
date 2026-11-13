"""Paste clipboard image into Gemini, ask for UI score, save reply."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests
import websocket

CDP = 'http://127.0.0.1:9222'
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('_qa_checkout_pro_design/gemini_rate_iter1.txt')
PROMPT = """Rate this MBT POS Checkout Pro UI screenshot for production readiness (cashier POS).

Respond EXACTLY:

SCORE: <0-100>%

IMPROVED:
- ...

REMAINING PROBLEMS (prioritized, actionable):
1. ...

NEXT FIXES (top 5 concrete UI changes):
1. ...

Be strict. Focus on cashier speed, density, clipping, hierarchy, misclick risk, payment column, cart rows, product cards, categories, yellow overuse, contextual editors."""


def pages():
    return [t for t in requests.get(f'{CDP}/json/list', timeout=5).json() if t.get('type') == 'page']


def find():
    for t in pages():
        if 'gemini.google.com' in (t.get('url') or ''):
            return t
    return None


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
        r = self.call('Runtime.evaluate', {
            'expression': expr, 'returnByValue': True,
        })
        if r.get('exceptionDetails'):
            raise RuntimeError(str(r['exceptionDetails']))
        return (r.get('result') or {}).get('value')


def main():
    tab = find()
    if not tab:
        print('NO gemini tab')
        return 2
    print('TAB', tab['title'], tab['url'], flush=True)
    c = C(tab['webSocketDebuggerUrl'])
    c.call('Runtime.enable')
    c.call('Page.bringToFront')
    # Start fresh chat if possible
    c.ev(r"""
(() => {
  const a = Array.from(document.querySelectorAll('a,button')).find(el =>
    /new chat|new conversation/i.test((el.innerText||'') + (el.getAttribute('aria-label')||'')));
  if (a) { a.click(); return true; }
  return false;
})()
""")
    time.sleep(1.5)

    before = c.ev(r"""
(() => (document.body && document.body.innerText) ? document.body.innerText.length : 0)()
""") or 0

    c.ev(r"""
(() => {
  const el = document.querySelector('div.ql-editor[contenteditable="true"]')
    || document.querySelector('rich-textarea div[contenteditable="true"]')
    || document.querySelector('div[contenteditable="true"]');
  if (el) { el.focus(); el.click(); return true; }
  return false;
})()
""")
    time.sleep(0.3)
    c.call('Input.dispatchKeyEvent', {
        'type': 'keyDown', 'modifiers': 2, 'key': 'v', 'code': 'KeyV', 'windowsVirtualKeyCode': 86,
    })
    c.call('Input.dispatchKeyEvent', {
        'type': 'keyUp', 'modifiers': 2, 'key': 'v', 'code': 'KeyV', 'windowsVirtualKeyCode': 86,
    })
    print('pasted', flush=True)
    time.sleep(2.5)

    ok = c.ev(r"""
((msg) => {
  const el = document.querySelector('div.ql-editor[contenteditable="true"]')
    || document.querySelector('rich-textarea div[contenteditable="true"]')
    || document.querySelector('div[contenteditable="true"]');
  if (!el) return false;
  el.focus();
  document.execCommand('insertText', false, '\n' + msg);
  el.dispatchEvent(new InputEvent('input', {bubbles:true}));
  return true;
})(""" + json.dumps(PROMPT) + ')')
    print('typed', ok, flush=True)
    time.sleep(0.6)

    sent = c.ev(r"""
(() => {
  const btn = document.querySelector('button.send-button')
    || document.querySelector('button[aria-label*="Send"]')
    || document.querySelector('button[aria-label*="send message" i]')
    || Array.from(document.querySelectorAll('button')).find(b =>
         /send/i.test(b.getAttribute('aria-label')||''));
  if (btn && !btn.disabled) { btn.click(); return 'click'; }
  return false;
})()
""")
    print('send', sent, flush=True)

    end = time.time() + 200
    last = ''
    stable = 0
    while time.time() < end:
        data = c.ev(r"""
(() => {
  const body = document.body ? document.body.innerText : '';
  // Prefer model response containers
  const cands = Array.from(document.querySelectorAll(
    'message-content, .model-response-text, .response-content, div[data-response], .markdown'));
  let best = '';
  for (const n of cands) {
    const t = (n.innerText || '').trim();
    if (t.length > best.length && t.length < 30000) best = t;
  }
  if (!best || best.length < 80) {
    // Heuristic: text after SCORE
    const idx = body.lastIndexOf('SCORE:');
    if (idx >= 0) best = body.slice(idx, idx + 8000);
  }
  const streaming = /stop response|stop generating/i.test(body.slice(-500))
    || !!document.querySelector('button[aria-label*="Stop"]');
  return {text: best, streaming, len: best.length};
})()
""") or {}
        t = data.get('text') or ''
        if 'SCORE' in t and not data.get('streaming'):
            if t == last:
                stable += 1
                if stable >= 3 and len(t) > 150:
                    OUT.parent.mkdir(parents=True, exist_ok=True)
                    OUT.write_text(t, encoding='utf-8')
                    print('WROTE', OUT, len(t), flush=True)
                    print(t[:900], flush=True)
                    return 0
            else:
                stable = 0
                last = t
                print(f'  .. {len(t)}', flush=True)
        elif t and t != last:
            last = t
            print(f'  .. {len(t)} streaming={data.get("streaming")}', flush=True)
        time.sleep(1.4)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(last or 'TIMEOUT', encoding='utf-8')
    print('TIMEOUT', len(last), flush=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
