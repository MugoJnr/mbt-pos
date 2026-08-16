"""E2E Phase 2-3: Register fresh portal user via UI + admin license assign."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
STATE_FILE = LOG_DIR / "_e2e_fresh_user_state.json"

from _cdp_gmail_auth import CDP, ensure_gmail, find_page, pages  # noqa: E402
from _open_auth_link import open_url  # noqa: E402
from _e2e_env import require_e2e_admin  # noqa: E402

ADMIN_EMAIL, ADMIN_PASSWORD = require_e2e_admin()

ts = datetime.now().strftime("%Y%m%d%H%M")
_local, _domain = ADMIN_EMAIL.split("@", 1)
NEW_EMAIL = f"{_local}+mbte2e{ts}@{_domain}"
NEW_PASSWORD = "MbtE2eFresh!2026"
NEW_BUSINESS = f"E2E Fresh Shop {ts}"
NEW_FIRST = "E2E"
NEW_LAST = "Tester"


def save_state(data: dict) -> None:
    cur = {}
    if STATE_FILE.exists():
        try:
            cur = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    cur.update(data)
    STATE_FILE.write_text(json.dumps(cur, indent=2), encoding="utf-8")


def wait_portal(sub: str, timeout: float = 30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for t in pages():
            u = t.get("url") or ""
            if "portal.mugobyte.com" in u and sub in u:
                return t
        time.sleep(0.5)
    return None


def register_fresh_user() -> dict:
    open_url("https://portal.mugobyte.com/register")
    time.sleep(4)
    tab = wait_portal("/register", 20) or wait_portal("portal.mugobyte.com", 10)
    if not tab:
        raise RuntimeError("No portal register tab")
    cdp = CDP(tab["webSocketDebuggerUrl"])
    try:
        cdp.call("Page.reload", {"ignoreCache": True})
        time.sleep(3)
        result = cdp.eval(
            f"""
(() => {{
  const set = (sel, val) => {{
    const el = document.querySelector(sel);
    if (!el) return false;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(el, val);
    el.dispatchEvent(new Event('input', {{bubbles:true}}));
    el.dispatchEvent(new Event('change', {{bubbles:true}}));
    return true;
  }};
  const ok = [
    set('#fn', {json.dumps(NEW_FIRST)}),
    set('#ln', {json.dumps(NEW_LAST)}),
    set('#biz', {json.dumps(NEW_BUSINESS)}),
    set('#email', {json.dumps(NEW_EMAIL)}),
    set('#phone', '+254700000001'),
    set('#pw', {json.dumps(NEW_PASSWORD)}),
  ];
  if (ok.some(x => !x)) return {{ok:false, step:'fill', fields: ok}};
  const btn = document.querySelector('button[type=submit]');
  if (!btn) return {{ok:false, step:'no-submit'}};
  btn.click();
  return {{ok:true, step:'submitted'}};
}})()
"""
        ).get("value") or {}
        print("REGISTER_SUBMIT", json.dumps(result))
        for i in range(25):
            time.sleep(1)
            info = cdp.eval(
                """
(() => ({
  href: location.href,
  body: (document.body && document.body.innerText || '').slice(0,500),
  token: sessionStorage.getItem('mbt_token') || '',
}))()
"""
            ).get("value") or {}
            href = info.get("href") or ""
            body = info.get("body") or ""
            print(f"REG{i}", href[:100])
            if "/verify-email" in href or "Check your inbox" in body:
                return {"ok": True, "email": NEW_EMAIL, "needs_verify": True}
            if "/dashboard" in href and info.get("token"):
                return {"ok": True, "email": NEW_EMAIL, "needs_verify": False}
            if "Registration failed" in body or "already registered" in body.lower():
                return {"ok": False, "error": body[:200]}
        return {"ok": False, "error": "register timeout", "last": info}
    finally:
        cdp.close()


def verify_via_action_link() -> dict:
    """Open Supabase confirmation link in browser (real callback UI)."""
    sys.path.insert(0, str(ROOT))
    from backend.cloud.platform_service import _auth_redirect  # noqa: E402
    from backend.cloud_backup.supabase_client import SupabaseClient  # noqa: E402

    client = SupabaseClient()
    data = client.generate_auth_link(
        email=NEW_EMAIL,
        link_type='magiclink',
        redirect_to=_auth_redirect(),
        password=NEW_PASSWORD,
    )
    action = (
        data.get('action_link')
        or (data.get('properties') or {}).get('action_link')
        or ''
    )
    if not action:
        return {'ok': False, 'error': 'no action_link', 'data': data}
    print('ACTION_LINK', action[:120])
    open_url(action)
    time.sleep(5)
    tab = wait_portal('portal.mugobyte.com', 20)
    if not tab:
        return {'ok': False, 'error': 'no callback tab'}
    cdp = CDP(tab['webSocketDebuggerUrl'])
    try:
        for i in range(25):
            time.sleep(1)
            info = cdp.eval(
                """
(() => ({
  href: location.href,
  token: sessionStorage.getItem('mbt_token') || localStorage.getItem('mbt_token') || '',
  email: (() => { try { return JSON.parse(sessionStorage.getItem('mbt_user')||'null')?.email } catch(e){return null} })(),
  body: (document.body && document.body.innerText || '').slice(0,200),
}))()
"""
            ).get('value') or {}
            print('VERIFY', i, info.get('href', '')[:100], 'email=', info.get('email'))
            if info.get('email', '').lower() == NEW_EMAIL.lower() and info.get('token'):
                if '/dashboard' in (info.get('href') or '') or 'Workspace' in (info.get('body') or ''):
                    return {'ok': True, 'email': info.get('email'), 'href': info.get('href')}
        return {'ok': False, 'error': 'verify callback timeout', 'last': info}
    finally:
        cdp.close()


def admin_login_and_assign() -> dict:
    open_url('https://portal.mugobyte.com/login?redirect=/admin/licenses')
    time.sleep(4)
    tab = wait_portal('portal.mugobyte.com', 15)
    if not tab:
        return {'ok': False, 'error': 'no admin login tab'}
    cdp = CDP(tab['webSocketDebuggerUrl'])
    try:
        cdp.call('Network.enable', {})
        cdp.call('Network.clearBrowserCookies', {})
        cdp.eval("sessionStorage.clear(); localStorage.clear();")
        cdp.call('Page.navigate', {'url': 'https://portal.mugobyte.com/login?redirect=/admin/licenses'})
        time.sleep(3)
        cdp.call('Page.reload', {'ignoreCache': True})
        time.sleep(3)
        fill = cdp.eval(
            f"""
(async () => {{
  const r = await fetch('/api/cloud/auth/login', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    credentials: 'same-origin',
    body: JSON.stringify({{email: {json.dumps(ADMIN_EMAIL)}, password: {json.dumps(ADMIN_PASSWORD)}}}),
  }});
  const data = await r.json().catch(() => ({{}}));
  if (!r.ok || !data.token) {{
    return {{ok:false, status:r.status, error:data.error || data}};
  }}
  sessionStorage.setItem('mbt_token', data.token);
  sessionStorage.setItem('mbt_user', JSON.stringify(data.user || {{}}));
  sessionStorage.setItem('mbt_provider', data.provider || 'supabase');
  if (data.organizations && data.organizations[0]) {{
    sessionStorage.setItem('mbt_org_id', data.organizations[0].id);
  }}
  return {{ok:true, role:(data.user||{{}}).role, email:(data.user||{{}}).email}};
}})()
"""
        ).get('value') or {}
        print('ADMIN_LOGIN', json.dumps(fill)[:300])
        cdp.call('Page.navigate', {'url': 'https://portal.mugobyte.com/admin/licenses'})
        time.sleep(4)
        info = {}
        for i in range(15):
            time.sleep(1)
            info = cdp.eval(
                """
(() => ({
  href: location.href,
  role: (() => { try { return JSON.parse(sessionStorage.getItem('mbt_user')||'null')?.role } catch(e){return null} })(),
  email: (() => { try { return JSON.parse(sessionStorage.getItem('mbt_user')||'null')?.email } catch(e){return null} })(),
  token: sessionStorage.getItem('mbt_token') || '',
  body: (document.body && document.body.innerText || '').slice(0,200),
}))()
"""
            ).get('value') or {}
            print(f'ADMIN{i}', info.get('email'), info.get('role'), (info.get('href') or '')[:80])
            if info.get('email') == ADMIN_EMAIL and info.get('role') == 'platform_admin' and info.get('token'):
                break
        if info.get('role') != 'platform_admin':
            return {'ok': False, 'error': 'admin login failed', 'info': info}
        cdp.call("Page.navigate", {"url": "https://portal.mugobyte.com/admin/licenses"})
        time.sleep(4)
        # Create license via API in browser context (still authenticated admin UI session)
        lic = cdp.eval(
            f"""
(async () => {{
  const token = sessionStorage.getItem('mbt_token') || '';
  const orgId = sessionStorage.getItem('mbt_org_id') || '';
  const create = await fetch('/api/cloud/licenses', {{
    method: 'POST',
    headers: {{'Content-Type':'application/json', Authorization: 'Bearer '+token}},
    credentials: 'same-origin',
    body: JSON.stringify({{
      plan: 'trial',
      notes: 'E2E fresh user {ts}',
      org_id: orgId || undefined,
      assigned_email: {json.dumps(NEW_EMAIL)},
      product_id: 'mbt-pos',
    }}),
  }});
  const created = await create.json().catch(() => ({{}}));
  if (!create.ok || !created.license) {{
    return {{ok:false, step:'create', status:create.status, created}};
  }}
  const licId = created.license.id || created.license.license_id;
  const assign = await fetch('/api/cloud/licenses/' + licId + '/assign', {{
    method: 'POST',
    headers: {{'Content-Type':'application/json', Authorization: 'Bearer '+token}},
    credentials: 'same-origin',
    body: JSON.stringify({{assigned_email: {json.dumps(NEW_EMAIL)}}}),
  }});
  const assigned = await assign.json().catch(() => ({{}}));
  return {{
    ok: assign.ok,
    license_key: created.license.license_key || created.license.key,
    license_id: licId,
    assign_status: assign.status,
    assigned,
  }};
}})()
"""
        ).get("value") or {}
        print("LICENSE", json.dumps(lic)[:800])
        return lic
    finally:
        cdp.close()


def main() -> int:
    print("=== E2E Fresh User Portal ===")
    print("NEW_EMAIL", NEW_EMAIL)
    save_state({
        "email": NEW_EMAIL,
        "password": NEW_PASSWORD,
        "business": NEW_BUSINESS,
        "started": datetime.now().isoformat(),
    })

    reg = register_fresh_user()
    print("REG_RESULT", json.dumps(reg))
    if not reg.get("ok"):
        save_state({"register": reg, "failed": True})
        return 1

    if reg.get("needs_verify"):
        verify = verify_via_action_link()
        print("VERIFY_RESULT", json.dumps(verify))
        if not verify.get("ok"):
            save_state({"verify": verify, "failed": True})
            return 1

    lic = admin_login_and_assign()
    print("LICENSE_RESULT", json.dumps(lic))
    save_state({
        "register": reg,
        "license": lic,
        "completed_phases": ["2", "3"],
        "failed": not lic.get("ok"),
    })
    return 0 if lic.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
