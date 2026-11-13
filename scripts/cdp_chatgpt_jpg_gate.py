"""ChatGPT checkout gate via unique JPEG file inputs (clipboard paste is flaky)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests
import websocket
from PIL import Image

CDP = 'http://127.0.0.1:9222'
ROOT = Path(__file__).resolve().parents[1]
PROMPT = """You are rating MBT POS checkout UI for production.

I attached THREE screenshots in order:
1) Checkout Pro
2) Product Explorer  
3) Retail Classic

Rate EACH layout separately.

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

Be strict. 98%=ship-ready for all three."""


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


def main():
    it = sys.argv[1] if len(sys.argv) > 1 else '20'
    folder = ROOT / '_qa_checkout_pro_design' / f'iter_{it}'
    out = ROOT / '_qa_full_system_polish' / f'desktop_iter{it}' / 'chatgpt_checkout_gate.txt'
    srcs = [folder / 'checkout_pro.png', folder / 'product_explorer.png', folder / 'retail_classic.png']
    for p in srcs:
        if not p.exists():
            print('MISSING', p)
            return 2

    up = ROOT / '_qa_full_system_polish' / f'desktop_iter{it}' / 'chatgpt_upload'
    up.mkdir(parents=True, exist_ok=True)
    stamp = str(int(time.time()))
    # Banner-stamped uniques — ChatGPT rejects near-duplicate screenshots
    sys.path.insert(0, str(ROOT / 'scripts'))
    from stamp_qa_images import stamp as stamp_img
    imgs = []
    for s, label in zip(srcs, ('PRO', 'EXPLORER', 'CLASSIC')):
        dest = up / f'{label.lower()}_{stamp}.jpg'
        stamp_img(s, dest, f'{label}-{stamp}')
        imgs.append(dest)
        print('jpg', dest.name, dest.stat().st_size, flush=True)

    tab = find()
    if not tab:
        print('NO_CHATGPT')
        return 2
    c = C(tab['webSocketDebuggerUrl'])
    c.call('Runtime.enable')
    c.call('DOM.enable')
    c.call('Page.bringToFront')
    c.call('Page.navigate', {'url': 'https://chatgpt.com/'})
    time.sleep(4.5)
    prior = c.ev("document.querySelectorAll('[data-message-author-role=\"assistant\"]').length") or 0

    c.ev("""(() => {
      let inp = document.querySelector('#mbt-up');
      if (!inp) {
        inp = document.createElement('input');
        inp.type = 'file'; inp.id = 'mbt-up'; inp.accept = 'image/*';
        inp.multiple = true; document.body.appendChild(inp);
      }
      return true;
    })()""")
    doc = c.call('DOM.getDocument', {'depth': 1})
    root = doc['root']['nodeId']
    ids = c.call('DOM.querySelectorAll', {'nodeId': root, 'selector': 'input[type=file]'}).get('nodeIds') or []
    paths = [str(p.resolve()) for p in imgs]
    print('inputs', len(ids), flush=True)
    for nid in ids:
        try:
            c.call('DOM.setFileInputFiles', {'nodeId': nid, 'files': paths})
        except Exception as e:
            print('set fail', e, flush=True)
    time.sleep(3.5)

    # Also click ChatGPT's + attach if present and re-set
    c.ev(r"""(() => {
      const b = document.querySelector('button[aria-label*="Attach"], button[aria-label*="Upload"], button[data-testid="composer-plus-btn"]');
      if (b) { b.click(); return true; }
      return false;
    })()""")
    time.sleep(0.8)
    doc = c.call('DOM.getDocument', {'depth': 1})
    root = doc['root']['nodeId']
    ids = c.call('DOM.querySelectorAll', {'nodeId': root, 'selector': 'input[type=file]'}).get('nodeIds') or []
    for nid in ids:
        try:
            c.call('DOM.setFileInputFiles', {'nodeId': nid, 'files': paths})
        except Exception:
            pass
    time.sleep(2.0)

    c.ev(r"""(() => {
      const el = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable="true"]');
      if (el) { el.focus(); el.click(); return true; }
      return false;
    })()""")
    c.ev('((msg) => { const el = document.querySelector("#prompt-textarea") || document.querySelector("div[contenteditable=true]"); if (!el) return false; el.focus(); document.execCommand("insertText", false, msg); el.dispatchEvent(new InputEvent("input", {bubbles:true})); return true; })(' + json.dumps(PROMPT) + ')')
    time.sleep(1.0)

    sent = c.ev(r"""(() => {
      const b = document.querySelector('button[data-testid="send-button"]') || document.querySelector('button[aria-label="Send prompt"]');
      if (b && !b.disabled) { b.click(); return 'click'; }
      const el = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable="true"]');
      if (el) {
        el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));
        return 'enter';
      }
      return 'fail';
    })()""")
    print('send', sent, 'prior', prior, flush=True)

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
