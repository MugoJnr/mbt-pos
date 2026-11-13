"""Rate UI via CDP: --target chatgpt|gemini|claude --out FILE [--no-paste]"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests
import websocket

CDP = 'http://127.0.0.1:9222'
PROMPT = """This is the latest MBT POS Checkout Pro screenshot after density polish (compact cart rows, contextual price/discount via double-click, shorter product cards, compact category chips, wider payment column, less yellow).

Also consider: Retail Classic and Product Explorer share the same panels.

Respond EXACTLY:

SCORE: <0-100>%

IMPROVED:
- ...

REMAINING PROBLEMS (prioritized, actionable for a production cashier POS):
1. ...

NEXT FIXES (top 5 concrete UI changes only):
1. ...

Be strict but fair. Professional POS bar is 98%+. Focus visual/UX only."""


def pages():
    return [t for t in requests.get(f'{CDP}/json/list', timeout=5).json() if t.get('type') == 'page']


def find(target: str):
    if target == 'chatgpt':
        for t in pages():
            if '6a5dc244' in (t.get('url') or ''):
                return t
        for t in pages():
            if 'chatgpt.com' in (t.get('url') or ''):
                return t
    elif target == 'gemini':
        for t in pages():
            if 'gemini.google.com' in (t.get('url') or ''):
                return t
    else:
        for pref in ('claude.ai/chat', 'claude.ai/new', 'claude.ai'):
            for t in pages():
                u = t.get('url') or ''
                if pref in u and 'login' not in u.lower():
                    return t
        for t in pages():
            if 'claude.ai' in (t.get('url') or ''):
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
        r = self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
        if r.get('exceptionDetails'):
            raise RuntimeError(str(r['exceptionDetails'])[:400])
        return (r.get('result') or {}).get('value')

    def paste(self):
        self.call('Input.dispatchKeyEvent', {
            'type': 'keyDown', 'modifiers': 2, 'key': 'v', 'code': 'KeyV', 'windowsVirtualKeyCode': 86,
        })
        self.call('Input.dispatchKeyEvent', {
            'type': 'keyUp', 'modifiers': 2, 'key': 'v', 'code': 'KeyV', 'windowsVirtualKeyCode': 86,
        })


def focus_composer(c: C, target: str):
    if target == 'chatgpt':
        return c.ev(r"""
(() => {
  const el = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable="true"]');
  if (el) { el.focus(); el.click(); return true; }
  return false;
})()""")
    if target == 'gemini':
        return c.ev(r"""
(() => {
  const el = document.querySelector('div.ql-editor[contenteditable="true"]')
    || document.querySelector('rich-textarea div[contenteditable="true"]')
    || document.querySelector('div[contenteditable="true"]');
  if (el) { el.focus(); el.click(); return true; }
  return false;
})()""")
    return c.ev(r"""
(() => {
  const el = document.querySelector('div[contenteditable="true"]') || document.querySelector('p[data-placeholder]') || document.querySelector('textarea');
  if (el) { el.focus(); el.click(); return true; }
  return false;
})()""")


def type_prompt(c: C, target: str, text: str):
    return c.ev(r"""
((msg) => {
  const sels = [
    '#prompt-textarea',
    'div.ql-editor[contenteditable="true"]',
    'rich-textarea div[contenteditable="true"]',
    'div[contenteditable="true"]',
    'textarea',
  ];
  let el = null;
  for (const s of sels) { el = document.querySelector(s); if (el) break; }
  if (!el) return false;
  el.focus();
  if (el.tagName === 'TEXTAREA') {
    el.value = (el.value || '') + '\n' + msg;
    el.dispatchEvent(new Event('input', {bubbles:true}));
  } else {
    document.execCommand('insertText', false, '\n' + msg);
    el.dispatchEvent(new InputEvent('input', {bubbles:true}));
  }
  return true;
})(""" + json.dumps(text) + ')')


def send(c: C, target: str):
    return c.ev(r"""
(() => {
  const candidates = [
    'button[data-testid="send-button"]',
    'button[aria-label="Send prompt"]',
    'button.send-button',
    'button[aria-label*="Send Message"]',
    'button[aria-label*="Send message"]',
    'button[aria-label*="Send"]',
  ];
  for (const s of candidates) {
    const b = document.querySelector(s);
    if (b && !b.disabled) { b.click(); return s; }
  }
  const b2 = Array.from(document.querySelectorAll('button')).find(x =>
    /send/i.test((x.getAttribute('aria-label')||'') + (x.innerText||'')) && !x.disabled);
  if (b2) { b2.click(); return 'fallback'; }
  return false;
})()""")


def wait_chatgpt(c: C, prior: int, timeout=200):
    end = time.time() + timeout
    last = ''
    while time.time() < end:
        data = c.ev(r"""
(() => {
  const arts = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
  const n = arts.length;
  const text = n ? (arts[n-1].innerText || '') : '';
  const streaming = !!document.querySelector('button[data-testid="stop-button"], button[aria-label="Stop streaming"]');
  return {n, text, streaming};
})()""") or {}
        text = data.get('text') or ''
        if data.get('n', 0) > prior and text and not data.get('streaming') and len(text) > 120:
            time.sleep(1.5)
            return c.ev(r"""
(() => {
  const arts = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
  return arts.length ? (arts[arts.length-1].innerText || '') : '';
})()""") or text
        if text != last and text:
            last = text
            print(f'  ..{len(text)} stream={data.get("streaming")}', flush=True)
        time.sleep(1.1)
    return last


def wait_score_body(c: C, timeout=200):
    end = time.time() + timeout
    last = ''
    stable = 0
    while time.time() < end:
        data = c.ev(r"""
(() => {
  const body = document.body ? document.body.innerText : '';
  let best = '';
  const idx = Math.max(body.lastIndexOf('SCORE:'), body.lastIndexOf('Score:'));
  if (idx >= 0) best = body.slice(idx, idx + 9000);
  if (!best) {
    const nodes = Array.from(document.querySelectorAll(
      '[data-is-streaming], .font-claude-message, message-content, .model-response-text, .markdown, [data-message-author-role="assistant"]'));
    for (const n of nodes) {
      const t = (n.innerText || '').trim();
      if (t.length > best.length && t.length < 25000) best = t;
    }
  }
  const streaming = !!document.querySelector(
    'button[aria-label*="Stop"], button[data-testid="stop-button"], [data-is-streaming="true"]');
  return {text: best, streaming, len: best.length};
})()""") or {}
        t = data.get('text') or ''
        if 'SCORE' in t.upper() and not data.get('streaming'):
            if t == last:
                stable += 1
                if stable >= 3 and len(t) > 100:
                    return t
            else:
                stable = 0
                last = t
                print(f'  ..{len(t)}', flush=True)
        elif t and t != last:
            last = t
            print(f'  ..{len(t)} stream={data.get("streaming")}', flush=True)
        time.sleep(1.2)
    return last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', required=True, choices=['chatgpt', 'gemini', 'claude'])
    ap.add_argument('--out', required=True)
    ap.add_argument('--no-paste', action='store_true')
    args = ap.parse_args()
    out = Path(args.out)
    tab = find(args.target)
    if not tab:
        out.write_text(f'NO_TAB {args.target}\n', encoding='utf-8')
        print('NO_TAB', args.target)
        return 2
    print('TAB', tab.get('title'), tab.get('url')[:90], flush=True)
    c = C(tab['webSocketDebuggerUrl'])
    c.call('Runtime.enable')
    c.call('Page.bringToFront')
    url = (tab.get('url') or '').lower()
    if args.target == 'claude' and 'login' in url:
        out.write_text('CLAUDE_LOGIN_REQUIRED\n' + (tab.get('url') or ''), encoding='utf-8')
        print('CLAUDE_LOGIN_REQUIRED')
        return 3

    prior = 0
    if args.target == 'chatgpt':
        prior = c.ev("document.querySelectorAll('[data-message-author-role=\"assistant\"]').length") or 0

    focus_composer(c, args.target)
    time.sleep(0.3)
    if not args.no_paste:
        c.paste()
        print('pasted', flush=True)
        time.sleep(2.2)
    type_prompt(c, args.target, PROMPT)
    time.sleep(0.5)
    print('send', send(c, args.target), flush=True)

    if args.target == 'chatgpt':
        reply = wait_chatgpt(c, prior)
    else:
        reply = wait_score_body(c)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(reply or 'EMPTY', encoding='utf-8')
    print('WROTE', out, len(reply or ''), flush=True)
    print((reply or '')[:700], flush=True)
    return 0 if reply and 'SCORE' in (reply or '').upper() else 1


if __name__ == '__main__':
    raise SystemExit(main())
