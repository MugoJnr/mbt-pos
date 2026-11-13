"""CDP helper: upload POS screenshot to ChatGPT/Gemini/Claude and extract UI rating.

Usage:
  python scripts/cdp_ui_rate.py --target chatgpt --image PATH --out PATH [--prompt TEXT]
  python scripts/cdp_ui_rate.py --target gemini --image PATH --out PATH
  python scripts/cdp_ui_rate.py --target claude --image PATH --out PATH
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import requests
import websocket

CDP = 'http://127.0.0.1:9222'

DEFAULT_PROMPT = """Rate this MBT POS checkout UI screenshot for production readiness.

Please respond with EXACTLY this structure:

SCORE: <integer 0-100>%

IMPROVED:
- bullet list of what looks better / already good

REMAINING PROBLEMS (prioritized, actionable):
1. ...
2. ...

NEXT FIXES (top 5 concrete UI changes):
1. ...

Be strict. Focus on cashier speed, density, clipping, hierarchy, misclick risk, payment column, cart rows, product cards, categories. Do not invent backend bugs."""


def list_pages():
    tabs = requests.get(f'{CDP}/json/list', timeout=5).json()
    return [t for t in tabs if t.get('type') == 'page']


def find_tab(substrs):
    pages = list_pages()
    for s in substrs:
        for t in pages:
            url = (t.get('url') or '').lower()
            title = (t.get('title') or '').lower()
            if s in url or s in title:
                return t
    return None


class CDPClient:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=30)
        self._id = 0

    def call(self, method, params=None, timeout=60):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self.ws.recv()
            msg = json.loads(raw)
            if msg.get('id') == mid:
                if 'error' in msg:
                    raise RuntimeError(f'{method}: {msg["error"]}')
                return msg.get('result') or {}
        raise TimeoutError(method)

    def eval(self, expression, await_promise=False):
        r = self.call('Runtime.evaluate', {
            'expression': expression,
            'returnByValue': True,
            'awaitPromise': await_promise,
        })
        if r.get('exceptionDetails'):
            raise RuntimeError(str(r['exceptionDetails']))
        return (r.get('result') or {}).get('value')

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def ensure_file_input(cdp: CDPClient):
    """Ensure a hidden file input exists and return its backend node id path via JS."""
    cdp.eval("""
(() => {
  let inp = document.querySelector('#mbt-cdp-file');
  if (!inp) {
    inp = document.createElement('input');
    inp.type = 'file';
    inp.id = 'mbt-cdp-file';
    inp.accept = 'image/*';
    inp.multiple = true;
    inp.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;';
    document.body.appendChild(inp);
  }
  return true;
})()
""")


def set_files(cdp: CDPClient, paths: list[str]):
    ensure_file_input(cdp)
    doc = cdp.call('DOM.getDocument', {'depth': 1})
    root = doc['root']['nodeId']
    node = cdp.call('DOM.querySelector', {'nodeId': root, 'selector': '#mbt-cdp-file'})
    nid = node.get('nodeId')
    if not nid:
        raise RuntimeError('file input not found')
    cdp.call('DOM.setFileInputFiles', {'nodeId': nid, 'files': paths})
    # Dispatch change so SPA picks it up if wired — for ChatGPT we also need native attach.
    cdp.eval("""
(() => {
  const inp = document.querySelector('#mbt-cdp-file');
  if (inp) inp.dispatchEvent(new Event('change', {bubbles:true}));
  return inp && inp.files && inp.files.length;
})()
""")
    return nid


def chatgpt_attach_via_composer(cdp: CDPClient, image_path: str):
    """Prefer ChatGPT's real file input near the composer."""
    # Click + attach if present, else inject into any file input
    found = cdp.eval(r"""
(() => {
  const inputs = Array.from(document.querySelectorAll('input[type=file]'));
  const usable = inputs.filter(i => !i.disabled);
  return usable.map(i => ({
    id: i.id || '',
    name: i.name || '',
    accept: i.accept || '',
    cls: i.className || '',
  }));
})()
""")
    print('file_inputs', found, flush=True)

    # Try Dom.setFileInputFiles on first usable composer input
    doc = cdp.call('DOM.getDocument', {'depth': -1, 'pierce': True})
    # querySelectorAll via JS backend ids is hard; use Runtime + DOM.describeNode
    # Simpler: create transfer by setting files on ALL file inputs
    root_id = doc['root']['nodeId']
    # Collect node ids via TreeWalker-like query
    res = cdp.call('DOM.querySelectorAll', {'nodeId': root_id, 'selector': 'input[type=file]'})
    node_ids = res.get('nodeIds') or []
    if not node_ids:
        set_files(cdp, [image_path])
        return False
    for nid in node_ids:
        try:
            cdp.call('DOM.setFileInputFiles', {'nodeId': nid, 'files': [image_path]})
        except Exception as e:
            print('setFiles fail', nid, e, flush=True)
    cdp.eval("""
(() => {
  document.querySelectorAll('input[type=file]').forEach(inp => {
    try { inp.dispatchEvent(new Event('change', {bubbles:true})); } catch(e) {}
  });
  return true;
})()
""")
    return True


def chatgpt_type_and_send(cdp: CDPClient, text: str):
    # Focus composer (ProseMirror / contenteditable / textarea)
    focused = cdp.eval(r"""
(() => {
  const sel = [
    '#prompt-textarea',
    'div[contenteditable="true"]',
    'textarea[data-id]',
    'textarea',
  ];
  for (const s of sel) {
    const el = document.querySelector(s);
    if (el && el.offsetParent !== null) {
      el.focus();
      return s;
    }
  }
  return null;
})()
""")
    print('composer', focused, flush=True)
    # Insert text
    cdp.eval(r"""
((msg) => {
  const el = document.querySelector('#prompt-textarea')
    || document.querySelector('div[contenteditable="true"]')
    || document.querySelector('textarea');
  if (!el) return false;
  el.focus();
  if (el.tagName === 'TEXTAREA') {
    const proto = window.HTMLTextAreaElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(el, msg); else el.value = msg;
    el.dispatchEvent(new Event('input', {bubbles:true}));
  } else {
    // contenteditable
    el.textContent = '';
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, msg);
    el.dispatchEvent(new InputEvent('input', {bubbles:true, data: msg, inputType:'insertText'}));
  }
  return true;
})(""" + json.dumps(text) + ")")
    time.sleep(0.8)
    # Click send
    sent = cdp.eval(r"""
(() => {
  const btn = document.querySelector('button[data-testid="send-button"]')
    || document.querySelector('button[aria-label="Send prompt"]')
    || document.querySelector('button[aria-label*="Send"]')
    || Array.from(document.querySelectorAll('button')).find(b =>
         (b.getAttribute('aria-label')||'').toLowerCase().includes('send'));
  if (btn && !btn.disabled) { btn.click(); return true; }
  // fallback Enter
  const el = document.querySelector('#prompt-textarea')
    || document.querySelector('div[contenteditable="true"]');
  if (el) {
    el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', bubbles:true}));
    return 'enter';
  }
  return false;
})()
""")
    print('send', sent, flush=True)
    return bool(sent)


def wait_chatgpt_reply(cdp: CDPClient, prior_count: int, timeout=180):
    deadline = time.time() + timeout
    last = ''
    while time.time() < deadline:
        data = cdp.eval(r"""
(() => {
  const arts = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
  const n = arts.length;
  const last = arts[n-1];
  const text = last ? (last.innerText || '') : '';
  const streaming = !!document.querySelector('button[aria-label="Stop streaming"], button[data-testid="stop-button"]');
  return {n, text, streaming, len: text.length};
})()
""")
        if not data:
            time.sleep(1)
            continue
        text = data.get('text') or ''
        if data.get('n', 0) > prior_count and text and not data.get('streaming') and len(text) > 80:
            # settle
            time.sleep(1.5)
            data2 = cdp.eval(r"""
(() => {
  const arts = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
  const last = arts[arts.length-1];
  return last ? (last.innerText || '') : '';
})()
""")
            return data2 or text
        if text != last:
            last = text
            print(f'  ... reply {len(text)} chars streaming={data.get("streaming")}', flush=True)
        time.sleep(1.2)
    return last


def gemini_type_and_send(cdp: CDPClient, text: str, image_path: str):
    # Set files on gemini inputs
    chatgpt_attach_via_composer(cdp, image_path)
    time.sleep(1.0)
    # Gemini uses rich-textarea / contenteditable
    cdp.eval(r"""
((msg) => {
  const el = document.querySelector('div.ql-editor[contenteditable="true"]')
    || document.querySelector('rich-textarea div[contenteditable="true"]')
    || document.querySelector('div[contenteditable="true"]')
    || document.querySelector('textarea');
  if (!el) return false;
  el.focus();
  if (el.tagName === 'TEXTAREA') {
    el.value = msg;
    el.dispatchEvent(new Event('input', {bubbles:true}));
  } else {
    el.textContent = '';
    document.execCommand('insertText', false, msg);
    el.dispatchEvent(new InputEvent('input', {bubbles:true}));
  }
  return true;
})(""" + json.dumps(text) + ")")
    time.sleep(0.8)
    sent = cdp.eval(r"""
(() => {
  const btn = document.querySelector('button.send-button')
    || document.querySelector('button[aria-label*="Send"]')
    || document.querySelector('button[aria-label*="send"]')
    || Array.from(document.querySelectorAll('button')).find(b =>
         (b.getAttribute('aria-label')||'').toLowerCase().includes('send'));
  if (btn && !btn.disabled) { btn.click(); return true; }
  return false;
})()
""")
    print('gemini send', sent, flush=True)


def wait_gemini_reply(cdp: CDPClient, timeout=180):
    deadline = time.time() + timeout
    last = ''
    stable = 0
    while time.time() < deadline:
        text = cdp.eval(r"""
(() => {
  const nodes = Array.from(document.querySelectorAll('message-content, .model-response-text, .response-content, div[data-response]'));
  // fallback: last large markdown-ish block
  let best = '';
  for (const n of nodes) {
    const t = (n.innerText || '').trim();
    if (t.length > best.length) best = t;
  }
  if (!best) {
    const all = Array.from(document.querySelectorAll('div'));
    for (const n of all.slice(-40)) {
      const t = (n.innerText || '').trim();
      if (t.includes('SCORE') || t.includes('Score') || t.length > 400) {
        if (t.length > best.length && t.length < 20000) best = t;
      }
    }
  }
  const streaming = !!document.querySelector('button[aria-label*="Stop"], button.stop');
  return {text: best, streaming, len: best.length};
})()
""") or {}
        t = text.get('text') or ''
        if t and not text.get('streaming'):
            if t == last:
                stable += 1
                if stable >= 3 and len(t) > 100:
                    return t
            else:
                stable = 0
                last = t
                print(f'  ... gemini {len(t)} chars', flush=True)
        time.sleep(1.5)
    return last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', choices=['chatgpt', 'gemini', 'claude'], required=True)
    ap.add_argument('--image', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--prompt', default=DEFAULT_PROMPT)
    ap.add_argument('--url', default='')
    args = ap.parse_args()

    image = str(Path(args.image).resolve())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.target == 'chatgpt':
        tab = find_tab(['chatgpt.com/c/', 'chatgpt.com'])
        prefer = find_tab(['license and report', '6a5dc244'])
        tab = prefer or tab
    elif args.target == 'gemini':
        tab = find_tab(['gemini.google.com'])
    else:
        tab = find_tab(['claude.ai/new', 'claude.ai/chat', 'claude.ai'])

    if not tab:
        print('NO_TAB', args.target)
        out.write_text(f'NO_TAB for {args.target}\n', encoding='utf-8')
        return 2

    print('TAB', tab.get('title'), tab.get('url'), flush=True)
    ws = tab.get('webSocketDebuggerUrl')
    cdp = CDPClient(ws)
    try:
        cdp.call('Runtime.enable')
        cdp.call('DOM.enable')
        cdp.call('Page.bringToFront')

        if args.url:
            cdp.call('Page.navigate', {'url': args.url})
            time.sleep(3)

        if args.target == 'chatgpt':
            prior = cdp.eval(r"""
(() => document.querySelectorAll('[data-message-author-role="assistant"]').length)()
""") or 0
            chatgpt_attach_via_composer(cdp, image)
            time.sleep(1.5)
            # Check if attachment preview appeared; if not, still send text referencing prior context
            prompt = args.prompt + "\n\n(Image attached: latest Checkout Pro screenshot after UI density polish.)"
            chatgpt_type_and_send(cdp, prompt)
            reply = wait_chatgpt_reply(cdp, prior_count=prior)
        elif args.target == 'gemini':
            gemini_type_and_send(cdp, args.prompt + "\n\n(Image attached.)", image)
            reply = wait_gemini_reply(cdp)
        else:
            # Claude — may be login wall
            title = cdp.eval('document.title')
            url = cdp.eval('location.href')
            body = cdp.eval('document.body && document.body.innerText.slice(0,500)')
            if 'login' in (url or '').lower() or 'Sign in' in (title or ''):
                reply = f'CLAUDE_NOT_LOGGED_IN\nurl={url}\ntitle={title}\n{body}'
            else:
                chatgpt_attach_via_composer(cdp, image)
                time.sleep(1)
                cdp.eval(r"""
((msg) => {
  const el = document.querySelector('div[contenteditable="true"]') || document.querySelector('textarea');
  if (!el) return false;
  el.focus();
  document.execCommand('insertText', false, msg);
  return true;
})(""" + json.dumps(args.prompt) + ")")
                time.sleep(0.5)
                cdp.eval(r"""
(() => {
  const btn = document.querySelector('button[aria-label="Send Message"]')
    || Array.from(document.querySelectorAll('button')).find(b => (b.getAttribute('aria-label')||'').toLowerCase().includes('send'));
  if (btn) btn.click();
  return !!btn;
})()
""")
                time.sleep(20)
                reply = cdp.eval(r"""
(() => {
  const msgs = Array.from(document.querySelectorAll('[data-is-streaming], .font-claude-message, div[class*="assistant"]'));
  let best='';
  for (const m of msgs) {
    const t=(m.innerText||'').trim();
    if (t.length>best.length) best=t;
  }
  return best || document.body.innerText.slice(-3000);
})()
""") or 'NO_REPLY'

        out.write_text(reply or 'EMPTY', encoding='utf-8')
        print('WROTE', out, 'chars', len(reply or ''), flush=True)
        return 0
    finally:
        cdp.close()


if __name__ == '__main__':
    raise SystemExit(main())
