"""Attach stamped images on current ChatGPT tab and request checkout scores."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests
import websocket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from stamp_qa_images import stamp

CDP = 'http://127.0.0.1:9222'
PROMPT = """NEW screenshots attached (with colored QA borders — ignore borders).

Rate MBT POS checkout layouts in order: 1 Checkout Pro, 2 Product Explorer, 3 Retail Classic.

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

Be strict. 98%=ship-ready."""


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
    it = sys.argv[1] if len(sys.argv) > 1 else '20'
    folder = ROOT / '_qa_checkout_pro_design' / f'iter_{it}'
    out = ROOT / '_qa_full_system_polish' / f'desktop_iter{it}' / 'chatgpt_checkout_gate.txt'
    up = ROOT / '_qa_full_system_polish' / f'desktop_iter{it}' / 'chatgpt_upload'
    stamp_id = str(int(time.time()))
    imgs = []
    for name, label in (
        ('checkout_pro.png', 'PRO'),
        ('product_explorer.png', 'EXPLORER'),
        ('retail_classic.png', 'CLASSIC'),
    ):
        d = up / f'{label.lower()}_{stamp_id}_v2.jpg'
        stamp(folder / name, d, f'{label}-{stamp_id}-V2')
        imgs.append(d)
        print('jpg', d.name, d.stat().st_size, flush=True)

    tab = next((t for t in pages() if 'chatgpt.com' in (t.get('url') or '')), None)
    if not tab:
        print('NO_CHATGPT')
        return 2
    c = C(tab['webSocketDebuggerUrl'])
    c.call('Runtime.enable')
    c.call('DOM.enable')
    c.call('Page.bringToFront')
    print('url', c.ev('location.href'), flush=True)
    prior = c.ev("document.querySelectorAll('[data-message-author-role=\"assistant\"]').length") or 0
    print('prior', prior, flush=True)

    # Dismiss modal/toast (incl. duplicate-upload OK)
    def dismiss():
        return c.ev(r"""(() => {
          const b = [...document.querySelectorAll('button')].find(x => /^(OK|Got it|Dismiss)$/i.test((x.innerText||'').trim()));
          if (b) { b.click(); return true; }
          return false;
        })()""")

    dismiss()
    time.sleep(0.4)

    # Fresh chat reduces stale attachment / dup-hash state
    c.call('Page.navigate', {'url': 'https://chatgpt.com/'})
    time.sleep(3.5)
    dismiss()

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
    time.sleep(2.0)
    if dismiss():
        print('dismissed_toast_after_set', flush=True)
        time.sleep(0.5)

    # Wait until composer shows attachment thumbnails (files actually queued)
    thumbs = 0
    for _ in range(25):
        dismiss()
        thumbs = c.ev(r"""(() => {
          const t = document.body.innerText || '';
          if (/already uploaded|Max 0 uploads|Unable to upload/i.test(t)) {
            const b = [...document.querySelectorAll('button')].find(x => /^(OK|Got it|Dismiss)$/i.test((x.innerText||'').trim()));
            if (b) b.click();
          }
          return document.querySelectorAll(
            '[data-testid="file-thumbnail"], button[aria-label*="Remove file"], button[aria-label*="Remove"], img[alt*="Uploaded"], [class*="thumbnail"]'
          ).length;
        })()""") or 0
        print('thumbs', thumbs, flush=True)
        if thumbs >= 2:
            break
        time.sleep(0.6)

    st = c.ev(r"""(() => {
      const b = document.querySelector('button[data-testid="send-button"]') || document.querySelector('button[aria-label="Send prompt"]');
      return {
        disabled: b ? b.disabled : null,
        dup: (document.body.innerText||'').includes('already uploaded'),
        fileCounts: [...document.querySelectorAll('input[type=file]')].map(f => (f.files&&f.files.length)||0)
      };
    })()""")
    print('state', st, 'thumbs', thumbs, flush=True)
    if thumbs < 1:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f'NO_THUMBS state={st}\n', encoding='utf-8')
        print('NO_THUMBS', flush=True)
        return 3

    c.ev(r"""(() => {
      const el = document.querySelector('#prompt-textarea') || document.querySelector('div[contenteditable="true"]');
      if (el) { el.focus(); el.click(); return true; }
      return false;
    })()""")
    c.ev('((msg) => { const el = document.querySelector("#prompt-textarea") || document.querySelector("div[contenteditable=true]"); if (!el) return false; el.focus(); document.execCommand("insertText", false, msg); el.dispatchEvent(new InputEvent("input", {bubbles:true})); return true; })(' + json.dumps(PROMPT) + ')')
    time.sleep(1.0)

    # Wait until send enables (upload processing)
    for _ in range(20):
        disabled = c.ev(r"""(() => {
          const b = document.querySelector('button[data-testid="send-button"]') || document.querySelector('button[aria-label="Send prompt"]');
          return b ? b.disabled : true;
        })()""")
        print('sendDisabled', disabled, flush=True)
        if not disabled:
            break
        time.sleep(0.5)

    sent = c.ev(r"""(() => {
      const b = document.querySelector('button[data-testid="send-button"]') || document.querySelector('button[aria-label="Send prompt"]');
      if (b && !b.disabled) { b.click(); return 'click'; }
      return b ? ('disabled:' + b.disabled) : 'none';
    })()""")
    print('sent', sent, flush=True)
    if str(sent).startswith('disabled') or sent == 'none':
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f'SEND_BLOCKED {sent} state={st}\n', encoding='utf-8')
        return 3

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
