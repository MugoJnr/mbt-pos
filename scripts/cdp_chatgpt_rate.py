"""Paste clipboard image into ChatGPT, ask for UI score, save reply."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests
import websocket

CDP = 'http://127.0.0.1:9222'
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('_qa_checkout_pro_design/chatgpt_rate_iter1.txt')
PROMPT = """Rate this MBT POS Checkout Pro UI (screenshot just pasted) for production readiness.

Respond EXACTLY:

SCORE: <0-100>%

IMPROVED:
- ...

REMAINING PROBLEMS (prioritized, actionable):
1. ...

NEXT FIXES (top 5 concrete UI changes):
1. ...

Be strict. Focus on cashier speed, density, clipping, hierarchy, misclick risk, payment column width, cart row height, product card height, categories, yellow overuse, contextual price/discount editors."""


def pages():
    return [t for t in requests.get(f'{CDP}/json/list', timeout=5).json() if t.get('type') == 'page']


def find():
    for t in pages():
        if '6a5dc244' in (t.get('url') or ''):
            return t
    for t in pages():
        if 'chatgpt.com' in (t.get('url') or ''):
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

    def ev(self, expr, await_promise=False):
        r = self.call('Runtime.evaluate', {
            'expression': expr, 'returnByValue': True, 'awaitPromise': await_promise,
        })
        if r.get('exceptionDetails'):
            raise RuntimeError(str(r['exceptionDetails']))
        return (r.get('result') or {}).get('value')


def main():
    tab = find()
    if not tab:
        print('NO chatgpt tab')
        return 2
    print('TAB', tab['title'], flush=True)
    c = C(tab['webSocketDebuggerUrl'])
    c.call('Runtime.enable')
    c.call('Page.bringToFront')
    prior = c.ev("document.querySelectorAll('[data-message-author-role=\"assistant\"]').length") or 0
    print('prior assistants', prior, flush=True)

    # Focus composer
    c.ev(r"""
(() => {
  const el = document.querySelector('#prompt-textarea')
    || document.querySelector('div[contenteditable="true"]');
  if (el) { el.focus(); el.click(); return el.tagName; }
  return null;
})()
""")
    time.sleep(0.4)

    # Paste image (Ctrl+V) via Input events
    for vk, key, code in [(17, 'Control', 'ControlLeft'), (86, 'v', 'KeyV')]:
        pass
    c.call('Input.dispatchKeyEvent', {
        'type': 'keyDown', 'modifiers': 2, 'key': 'v', 'code': 'KeyV', 'windowsVirtualKeyCode': 86,
    })
    c.call('Input.dispatchKeyEvent', {
        'type': 'keyUp', 'modifiers': 2, 'key': 'v', 'code': 'KeyV', 'windowsVirtualKeyCode': 86,
    })
    print('pasted', flush=True)
    time.sleep(2.5)

    # Check for attachment preview
    att = c.ev(r"""
(() => {
  const imgs = document.querySelectorAll('[data-testid="file-thumbnail"], img[alt*="image"], div[class*="attachment"], button[aria-label*="Remove"]');
  return imgs.length;
})()
""")
    print('attachment markers', att, flush=True)

    ok = c.ev(r"""
((msg) => {
  const el = document.querySelector('#prompt-textarea')
    || document.querySelector('div[contenteditable="true"]');
  if (!el) return false;
  el.focus();
  const sel = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  sel.removeAllRanges();
  sel.addRange(range);
  document.execCommand('insertText', false, '\n\n' + msg);
  el.dispatchEvent(new InputEvent('input', {bubbles:true}));
  return true;
})(""" + json.dumps(PROMPT) + ')')
    print('typed', ok, flush=True)
    time.sleep(0.8)

    sent = c.ev(r"""
(() => {
  const btn = document.querySelector('button[data-testid="send-button"]')
    || document.querySelector('button[aria-label="Send prompt"]');
  if (btn && !btn.disabled) { btn.click(); return 'click'; }
  // Enter
  const el = document.querySelector('#prompt-textarea')
    || document.querySelector('div[contenteditable="true"]');
  if (el) {
    el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', bubbles:true, cancelable:true}));
    return 'enter';
  }
  return false;
})()
""")
    print('send', sent, flush=True)

    end = time.time() + 200
    last = ''
    while time.time() < end:
        data = c.ev(r"""
(() => {
  const arts = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
  const n = arts.length;
  const last = arts[n-1];
  const text = last ? (last.innerText || '') : '';
  const streaming = !!document.querySelector('button[data-testid="stop-button"], button[aria-label="Stop streaming"]');
  return {n, text, streaming, len: text.length};
})()
""") or {}
        text = data.get('text') or ''
        if data.get('n', 0) > prior and text and not data.get('streaming') and len(text) > 120:
            time.sleep(2)
            text = c.ev(r"""
(() => {
  const arts = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
  return arts.length ? (arts[arts.length-1].innerText || '') : '';
})()
""") or text
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(text, encoding='utf-8')
            print('WROTE', OUT, len(text), flush=True)
            print(text[:800], flush=True)
            return 0
        if text != last and text:
            last = text
            print(f'  .. {len(text)} streaming={data.get("streaming")}', flush=True)
        time.sleep(1.2)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(last or 'TIMEOUT', encoding='utf-8')
    print('TIMEOUT/partial', len(last), flush=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
