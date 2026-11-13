"""Ask ChatGPT to rate all THREE checkout layouts. Gate: ≥98% each.

Usage: python scripts/cdp_chatgpt_checkout_gate.py [--iter N]
Expects images in _qa_checkout_pro_design/iter_N/{checkout_pro,product_explorer,retail_classic}.png
Clipboard: paste images one at a time OR attach via DOM.setFileInputFiles.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests
import websocket

CDP = 'http://127.0.0.1:9222'
ROOT = Path(__file__).resolve().parents[1]
PROMPT = """You are rating MBT POS checkout UI for production.

I am attaching THREE screenshots in order:
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

Be strict. 98% = ship-ready for all three. Focus density, clipping, badges, payment clarity, cart rows, hierarchy."""


def pages():
    return [t for t in requests.get(f'{CDP}/json/list', timeout=5).json() if t.get('type') == 'page']


def find_chatgpt():
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

    def ev(self, expr):
        r = self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
        if r.get('exceptionDetails'):
            raise RuntimeError(str(r['exceptionDetails'])[:400])
        return (r.get('result') or {}).get('value')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iter', default='11')
    args = ap.parse_args()
    it = str(args.iter).lstrip('iter_')
    folder = ROOT / '_qa_checkout_pro_design' / f'iter_{it}'
    out = ROOT / '_qa_full_system_polish' / f'desktop_iter{it}' / 'chatgpt_checkout_gate.txt'
    src_imgs = [
        folder / 'checkout_pro.png',
        folder / 'product_explorer.png',
        folder / 'retail_classic.png',
    ]
    for p in src_imgs:
        if not p.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(f'MISSING {p}\n', encoding='utf-8')
            print('MISSING', p)
            return 2

    # Unique copies — ChatGPT rejects re-uploading identical files
    import time as _time
    from PIL import Image, PngImagePlugin
    up = ROOT / '_qa_full_system_polish' / f'desktop_iter{it}' / 'chatgpt_upload'
    up.mkdir(parents=True, exist_ok=True)
    stamp = str(int(_time.time()))
    imgs = []
    for src, label in zip(src_imgs, ('pro', 'exp', 'classic')):
        dest = up / f'{label}_{stamp}.png'
        im = Image.open(src).convert('RGB')
        px = im.getpixel((0, 0))
        im.putpixel((0, 0), ((px[0] + 1) % 256, px[1], px[2]))
        meta = PngImagePlugin.PngInfo()
        meta.add_text('qa', f'iter{it}_{stamp}_{label}')
        im.save(dest, pnginfo=meta)
        imgs.append(dest)

    tab = find_chatgpt()
    if not tab:
        print('NO_CHATGPT')
        return 2
    print('TAB', tab.get('title'), flush=True)
    c = C(tab['webSocketDebuggerUrl'])
    c.call('Runtime.enable')
    c.call('DOM.enable')
    c.call('Page.bringToFront')

    # Prefer a fresh chat so prior empty assistant turns don't confuse polling
    try:
        c.call('Page.navigate', {'url': 'https://chatgpt.com/'})
        time.sleep(3.5)
    except Exception as e:
        print('nav warn', e, flush=True)

    prior = c.ev("document.querySelectorAll('[data-message-author-role=\"assistant\"]').length") or 0
    print('prior_assistants', prior, flush=True)

    # Attach all three files to every file input
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
    print('inputs', len(ids), 'files', len(paths), flush=True)
    for nid in ids:
        try:
            c.call('DOM.setFileInputFiles', {'nodeId': nid, 'files': paths})
        except Exception as e:
            print('set fail', e, flush=True)
    time.sleep(2.0)

    # Focus composer + type
    c.ev(r"""(() => {
      const el = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable="true"]');
      if (el) { el.focus(); el.click(); return true; }
      return false;
    })()""")
    c.ev('((msg) => { const el = document.querySelector("#prompt-textarea") || document.querySelector("div[contenteditable=true]"); if (!el) return false; el.focus(); document.execCommand("insertText", false, msg); el.dispatchEvent(new InputEvent("input", {bubbles:true})); return true; })(' + json.dumps(PROMPT) + ')')
    time.sleep(0.6)
    sent = c.ev(r"""(() => {
      const b = document.querySelector('button[data-testid="send-button"]') || document.querySelector('button[aria-label="Send prompt"]');
      if (b && !b.disabled) { b.click(); return true; }
      return false;
    })()""")
    print('send', sent, flush=True)

    end = time.time() + 220
    last = ''
    while time.time() < end:
        data = c.ev(r"""(() => {
          const arts = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
          const n = arts.length;
          // Prefer last non-empty assistant turn (empty bubbles appear when generation fails)
          let text = '';
          for (let i = arts.length - 1; i >= 0; i--) {
            const t = arts[i].innerText || '';
            if (t.trim()) { text = t; break; }
          }
          const streaming = !!document.querySelector('button[data-testid="stop-button"], button[aria-label="Stop streaming"]');
          const err = (document.body.innerText || '').includes('already uploaded this file');
          return {n, text, streaming, err};
        })()""") or {}
        text = data.get('text') or ''
        if data.get('err'):
            print('UPLOAD_REJECTED_DUPLICATE', flush=True)
        if data.get('n', 0) > prior and text and not data.get('streaming'):
            upper = text.upper()
            if ('CHECKOUT_PRO' in upper or 'PRODUCT_EXPLORER' in upper or 'RETAIL_CLASSIC' in upper) and '%' in text:
                time.sleep(1.5)
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
                print(text[:1200], flush=True)
                return 0
            # Accept numeric score blocks even without exact labels
            if text.count('%') >= 3 and len(text) > 200:
                time.sleep(1.0)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding='utf-8')
                print('WROTE_LOOSE', out, len(text), flush=True)
                print(text[:1200], flush=True)
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
