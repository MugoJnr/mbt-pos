"""Publish the v3.0.71 app_updates row through an authenticated Supabase dashboard session.

Connects to the already-signed-in eugenemugo Chrome profile over CDP and issues the
insert through the dashboard's own pg-meta query endpoint, so no service-role key or
database password needs to be stored locally.
"""
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

PROJECT_REF = 'uynfglgttkaibyeglsrt'
CDP_URL = 'http://localhost:9222'

SQL = """
insert into public.app_updates (
  version, release_notes, download_url, checksum_sha256,
  file_size_bytes, is_mandatory, min_version, published_at, is_active
) values (
  '3.0.71',
  'MBT POS v3.0.71 production update: verified updater integrity, hardened recovery and credential packaging, reliable update helper, and responsive POS repairs.',
  'https://github.com/MugoJnr/mbt-pos/releases/download/v3.0.71/MBT_POS_Setup.exe',
  '9b9c29eb8c27ff43b1fc3e0516df3305c75f9962d86cff15d70285d9b95b368d',
  58783249,
  false,
  '3.0.70',
  now(),
  true
)
on conflict (version) do update set
  release_notes = excluded.release_notes,
  download_url = excluded.download_url,
  checksum_sha256 = excluded.checksum_sha256,
  file_size_bytes = excluded.file_size_bytes,
  is_mandatory = excluded.is_mandatory,
  min_version = excluded.min_version,
  published_at = excluded.published_at,
  is_active = excluded.is_active
returning version, download_url, checksum_sha256, file_size_bytes, is_active;
"""

VERIFY_SQL = """
select version, file_size_bytes, is_active, published_at
from public.app_updates
order by published_at desc
limit 5;
"""

JS = """
async ([ref, sql]) => {
  let token = '';
  try {
    token = JSON.parse(localStorage.getItem('supabase.dashboard.auth.token') || '{}')
      .access_token || '';
  } catch (err) {
    token = '';
  }
  if (!token) {
    return { ok: false, errors: [{ error: 'No dashboard access token in localStorage' }] };
  }
  const endpoints = [
    `https://api.supabase.com/platform/pg-meta/${ref}/query?key=`,
    `https://api.supabase.com/v1/projects/${ref}/database/query`,
  ];
  const errors = [];
  for (const url of endpoints) {
    try {
      const res = await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
          'x-connection-encrypted': 'true',
        },
        body: JSON.stringify({ query: sql }),
      });
      const text = await res.text();
      if (res.ok) {
        return { ok: true, url, body: text };
      }
      errors.push({ url, status: res.status, body: text.slice(0, 400) });
    } catch (err) {
      errors.push({ url, error: String(err) });
    }
  }
  return { ok: false, errors };
}
"""


def find_dashboard_page(browser):
    for context in browser.contexts:
        for page in context.pages:
            if 'supabase.com/dashboard' in (page.url or ''):
                return page
    return None


def run(page, sql: str) -> dict:
    return page.evaluate(JS, [PROJECT_REF, sql])


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_URL)
        page = find_dashboard_page(browser)
        if page is None:
            print('No authenticated Supabase dashboard tab found.', file=sys.stderr)
            return 2
        print('Using tab:', page.url)

        result = run(page, SQL)
        print('INSERT:', json.dumps(result, indent=2)[:2000])
        if not result.get('ok'):
            return 1

        verify = run(page, VERIFY_SQL)
        print('VERIFY:', json.dumps(verify, indent=2)[:2000])
        return 0 if verify.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
