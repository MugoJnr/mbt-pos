"""Paste 3 unique checkout screenshots into a fresh ChatGPT chat and gate-rate."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import requests
import websocket
from PIL import Image

CDP = 'http://127.0.0.1:9222'
ROOT = Path(__file__).resolve().parents[1]
CLIP = ROOT / 'scripts' / 'clip_image.ps1'
PROMPT = """You are rating MBT POS checkout UI for production.

THREE screenshots were just pasted in order:
1) Checkout Pro
2) Product Explorer
3) Retail Classic

Rate EACH layout separately for cashier UI/UX readiness.

Respond EXACTLY:

CHECKOUT_PRO: <0-100>%
PRODUCT_EXPLORER: <0-100>%
RETAIL_CLASSIC: <0-100>%
OVERALL_CHECKOUT: <0-100>%

IMPROVED:
- ...

REMAINING (must-fix before 98%):
1. ...

NEXT FIXES (top 5 concrete UI only):
1. ...

Be strict. 98% = ship-ready for all three."""


def pages():
    return [t for t in requests.get(f'{CDP}/json/list', timeout=5).json() if t.get('type') == 'page']


def find():
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


def clip(path: Path):
    r = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(CLIP), str(path)],
        capture_output=True, text=True, timeout=30)
    if 'CLIP_OK' not in (r.stdout or ''):
        raise RuntimeError(f'clip failed: {r.stdout} {r.stderr}')


def main():
    it = sys.argv[1] if len(sys.argv) > 1 else '19'
    folder = ROOT / '_qa_checkout_pro_design' / f'iter_{it}'
    out = ROOT / '_qa_full_system_polish' / f'desktop_iter{it}' / 'chatgpt_checkout_gate.txt'
    srcs = [folder / 'checkout_pro.png', folder / 'product_explorer.png', folder / 'retail_classic.png']
    for p in srcs:
        if not p.exists():
            print('MISSING', p)
            return 2

    # Unique stamped JPEGs (clipboard paste is flaky under CDP)
    sys.path.insert(0, str(ROOT / 'scripts'))
    from stamp_qa_images import stamp as stamp_img
    up = ROOT / '_qa_full_system_polish' / f'desktop_iter{it}' / 'chatgpt_upload'
    up.mkdir(parents=True, exist_ok=True)
    stamp = str(int(time.time()))
    jpgs = []
    for s, label in zip(srcs, ('PRO', 'EXPLORER', 'CLASSIC')):
        dest = up / f'{label.lower()}_{stamp}.jpg'
        stamp_img(s, dest, f'{label}-{stamp}')
        jpgs.append(dest)
        print('prepared', dest.name, dest.stat().st_size, flush=True)

    tab = find()
    if not tab:
        print('NO_CHATGPT')
        return 2
    c = C(tab['webSocketDebuggerUrl'])
    c.call('Runtime.enable')
    c.call('Page.bringToFront')
    c.call('Page.navigate', {'url': 'https://chatgpt.com/'})
    time.sleep(4.5)
    prior = c.ev("document.querySelectorAll('[data-message-author-role=\"assistant\"]').length") or 0
    print('prior', prior, flush=True)

    c.ev(r"""(() => {
      const el = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable="true"]');
      if (el) { el.focus(); el.click(); return true; }
      return false;
    })()""")
    time.sleep(0.5)

    for j in jpgs:
        clip(j)
        time.sleep(0.4)
        c.ev(r"""(() => {
          const el = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable="true"]');
          if (el) { el.focus(); el.click(); return true; }
          return false;
        })()""")
        time.sleep(0.2)
        c.paste()
        print('pasted', j.name, flush=True)
        time.sleep(2.8)

    att = 0
    for _ in range(8):
        att = c.ev(r"""(() => {
          const a = document.querySelectorAll('[data-testid="file-thumbnail"], button[aria-label*="Remove file"], button[aria-label*="Remove"], img[alt*="Uploaded"], [class*="file-thumbnail"]').length;
          return a;
        })()""") or 0
        print('attachments', att, flush=True)
        if att >= 2:
            break
        time.sleep(0.8)
    if att < 1:
        print('NO_ATTACHMENTS — abort send', flush=True)
        return 3

    c.ev('((msg) => { const el = document.querySelector("#prompt-textarea") || document.querySelector("div[contenteditable=true]"); if (!el) return false; el.focus(); document.execCommand("insertText", false, msg); el.dispatchEvent(new InputEvent("input", {bubbles:true})); return true; })(' + json.dumps(PROMPT) + ')')
    time.sleep(0.8)
    sent = c.ev(r"""(() => {
      const b = document.querySelector('button[data-testid="send-button"]') || document.querySelector('button[aria-label="Send prompt"]');
      if (b && !b.disabled) { b.click(); return 'click'; }
      const el = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable="true"]');
      if (el) {
        el.focus();
        el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));
        return 'enter';
      }
      return 'fail';
    })()""")
    print('send', sent, flush=True)

    end = time.time() + 240
    last = ''
    while time.time() < end:
        data = c.ev(r"""(() => {
          const arts = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
          let text = '';
          for (let i = arts.length - 1; i >= 0; i--) {
            const t = arts[i].innerText || '';
            if (t.trim()) { text = t; break; }
          }
          const streaming = !!document.querySelector('button[data-testid="stop-button"], button[aria-label="Stop streaming"]');
          return {n: arts.length, text, streaming};
        })()""") or {}
        text = data.get('text') or ''
        if data.get('n', 0) > prior and text and not data.get('streaming') and '%' in text and len(text) > 80:
            time.sleep(1.2)
            # refresh non-empty
            text = c.ev(r"""(() => {
              const arts = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
              for (let i = arts.length - 1; i >= 0; i--) {
                const t = arts[i].innerText || '';
                if (t.trim()) return t;
              }
              return '';
            })()""") or text
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding='utf-8')
            print('WROTE', out, len(text), flush=True)
            print(text[:1600], flush=True)
            return 0
        if text != last and text:
            last = text
            print(f'  ..{len(text)} stream={data.get("streaming")}', flush=True)
        time.sleep(1.2)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(last or 'TIMEOUT', encoding='utf-8')
    print('TIMEOUT', len(last or ''), flush=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
