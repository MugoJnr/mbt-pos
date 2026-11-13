"""Force-send on Claude: image already attached, type prompt + Enter."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests
import websocket

CDP = 'http://127.0.0.1:9222'
OUT = Path(r'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\_qa_full_system_polish\desktop_iter10\claude_rate.txt')
IMG = Path(r'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\_qa_checkout_pro_design\iter_10\checkout_pro.png')
PROMPT = """Rate this latest Checkout Pro screenshot for production cashier POS.

SCORE: <0-100>%
IMPROVED: bullets
REMAINING PROBLEMS: prioritized actionable
NEXT FIXES: top 5

Strict. 98%+ = ship-ready. Check clipping, ghosts, payment/transaction clarity, discount total vs line discs, density."""


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
            raise RuntimeError(str(r['exceptionDetails'])[:300])
        return (r.get('result') or {}).get('value')


def main():
    tab = next(t for t in pages() if 'claude.ai/chat' in (t.get('url') or ''))
    print('TAB', tab['title'], flush=True)
    c = C(tab['webSocketDebuggerUrl'])
    c.call('Runtime.enable')
    c.call('DOM.enable')
    c.call('Page.bringToFront')
    # Ensure file attached
    c.ev("""(() => { let i=document.querySelector('#mbt-up'); if(!i){i=document.createElement('input'); i.type='file'; i.id='mbt-up'; i.accept='image/*'; document.body.appendChild(i);} return true; })()""")
    doc = c.call('DOM.getDocument', {'depth': 1})
    root = doc['root']['nodeId']
    for nid in (c.call('DOM.querySelectorAll', {'nodeId': root, 'selector': 'input[type=file]'}).get('nodeIds') or []):
        try:
            c.call('DOM.setFileInputFiles', {'nodeId': nid, 'files': [str(IMG.resolve())]})
        except Exception:
            pass
    time.sleep(1)
    prior_len = c.ev("document.body.innerText.length") or 0
    # Clear composer then type
    c.ev(r"""
(() => {
  const el = document.querySelector('div[contenteditable="true"]');
  if (!el) return false;
  el.focus();
  el.innerHTML = '';
  el.dispatchEvent(new InputEvent('input', {bubbles:true}));
  return true;
})()""")
    c.ev('((m)=>{const el=document.querySelector("div[contenteditable=true]"); if(!el) return false; el.focus(); document.execCommand("insertText", false, m); return true;})(' + json.dumps(PROMPT) + ')')
    time.sleep(0.5)
    # Find send: often appears as button with svg arrow near composer
    sent = c.ev(r"""
(() => {
  // Prefer explicit send
  let b = document.querySelector('button[aria-label="Send Message"]')
    || document.querySelector('button[aria-label="Send message"]')
    || document.querySelector('button[aria-label="Send"]');
  if (b && !b.disabled) { b.click(); return 'aria'; }
  // Heuristic: last enabled round button in the composer toolbar
  const tools = Array.from(document.querySelectorAll('fieldset button, form button, [class*="composer"] button, [class*="Composer"] button'));
  const cand = tools.reverse().find(x => !x.disabled && /send/i.test((x.getAttribute('aria-label')||'')+(x.innerText||'')));
  if (cand) { cand.click(); return 'tools'; }
  // Click the rightmost small square button near voice (send often replaces mic when text present)
  const all = Array.from(document.querySelectorAll('button')).filter(x => !x.disabled);
  const near = all.filter(x => {
    const al = (x.getAttribute('aria-label')||'');
    return al === '' && x.clientWidth >= 28 && x.clientWidth <= 48 && x.clientHeight >= 28 && x.clientHeight <= 48;
  }).slice(-3);
  for (const x of near) { x.click(); return 'near'; }
  return false;
})()""")
    print('send click', sent, flush=True)
    # Always also dispatch Enter on composer
    c.call('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13})
    c.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13})
    print('enter sent', flush=True)

    end = time.time() + 200
    last = ''
    stable = 0
    while time.time() < end:
        data = c.ev(r"""
(() => {
  const body = document.body ? document.body.innerText : '';
  // Prefer last assistant-looking block with SCORE
  const idx = body.lastIndexOf('SCORE:');
  let best = idx >= 0 ? body.slice(idx, idx + 9000) : '';
  // Ignore template echoes
  if (best.includes('<0-100>') || best.includes('SCORE: <')) best = '';
  const streaming = !!document.querySelector('[data-is-streaming="true"]');
  return {best, streaming, len: best.length, bodyLen: body.length};
})()""") or {}
        t = data.get('best') or ''
        if t and not data.get('streaming') and '%' in t:
            if t == last:
                stable += 1
                if stable >= 3 and len(t) > 120:
                    break
            else:
                stable = 0
                last = t
                print('..', len(t), flush=True)
        elif data.get('bodyLen', 0) > prior_len + 200:
            print('growing', data.get('bodyLen'), 'stream', data.get('streaming'), flush=True)
        time.sleep(1.2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(last or 'EMPTY', encoding='utf-8')
    print('WROTE', len(last or ''), flush=True)
    print((last or '')[:1000], flush=True)
    return 0 if last and 'SCORE' in last else 1


if __name__ == '__main__':
    raise SystemExit(main())
