"""Exercise the isolated web consumption API. Does not print tokens."""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.request

BASE = 'http://127.0.0.1:8766'
DB = r'C:\MBT_Build\qa-isolated-consumption\data\mbt_pos.db'
OUT = r'C:\MBT_Build\mbt-pos-port\artifacts\internal_consumption_audit\backend'


def call(method, path, body=None, token=''):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {'raw': raw[:300]}
        return exc.code, payload


def stock(sku):
    con = sqlite3.connect(DB)
    row = con.execute('SELECT stock FROM products WHERE sku=?', (sku,)).fetchone()
    con.close()
    return None if row is None else float(row[0])


os.makedirs(OUT, exist_ok=True)
status, login = call('POST', '/api/auth/login', {
    'username': 'admin', 'password': 'ic-audit-only',
})
token = login.get('token') or ''
if not token:
    raise SystemExit('login failed ' + str(status))

code, departments = call('GET', '/api/departments', token=token)
dept_id = departments[0]['id']
code, products = call('GET', '/api/products', token=token)
by_sku = {p.get('sku'): p for p in products if isinstance(products, list)}
soap = by_sku['IC-AUDIT-SOAP-500']
refill = by_sku['IC-AUDIT-SOAP-REFILL']
before = {
    'IC-AUDIT-SOAP-500': stock('IC-AUDIT-SOAP-500'),
    'IC-AUDIT-SOAP-REFILL': stock('IC-AUDIT-SOAP-REFILL'),
}
payload = {
    'department_id': dept_id,
    'reason': 'Staff Consumption',
    'taken_by': 'Web Audit',
    'notes': 'IC-AUDIT web batch',
    'client_token': 'ic-audit-web-1',
    'items': [
        {'product_id': soap['id'], 'quantity': 1},
        {'product_id': refill['id'], 'quantity': 2},
    ],
}
created_code, created = call('POST', '/api/consumptions', payload, token)
retry_code, retry = call('POST', '/api/consumptions', payload, token)
short_code, short = call('POST', '/api/consumptions', {
    'department_id': dept_id,
    'reason': 'Cleaning',
    'items': [
        {'product_id': soap['id'], 'quantity': 1},
        {'product_id': by_sku['IC-AUDIT-ZERO']['id'], 'quantity': 1},
    ],
}, token)
listed_code, listed = call('GET', '/api/consumptions?start=2026-10-23&end=2026-10-23', token=token)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cashier = con.execute("SELECT id FROM users WHERE username='ic-cashier'").fetchone()
if not cashier:
    from desktop.utils.api_client import _hash_pw
    con.execute(
        "INSERT INTO users (username,password_hash,role,full_name,is_active) VALUES (?,?,?,?,1)",
        ('ic-cashier', _hash_pw('ic-audit-only'), 'cashier', 'IC Cashier'),
    )
    con.commit()
con.close()
c_code, c_login = call('POST', '/api/auth/login', {
    'username': 'ic-cashier', 'password': 'ic-audit-only',
})
denied_code, denied = call('POST', '/api/consumptions', payload, c_login.get('token') or '')
view_code, view = call('GET', '/api/consumptions?start=2026-10-23&end=2026-10-23', c_login.get('token') or '')

report = {
    'db': DB,
    'departments_status': code,
    'created_status': created_code,
    'created_ok': bool(created.get('success')),
    'created_ref': created.get('reference_no'),
    'retry_duplicate': bool(retry.get('duplicate')),
    'retry_same_id': retry.get('id') == created.get('id'),
    'short_status': short_code,
    'short_error': short.get('error'),
    'before': before,
    'after': {
        'IC-AUDIT-SOAP-500': stock('IC-AUDIT-SOAP-500'),
        'IC-AUDIT-SOAP-REFILL': stock('IC-AUDIT-SOAP-REFILL'),
    },
    'history_count': len(listed) if isinstance(listed, list) else listed,
    'cashier_create_status': denied_code,
    'cashier_view_status': view_code,
    'sales': sqlite3.connect(DB).execute('SELECT COUNT(*) FROM sales').fetchone()[0],
}
with open(os.path.join(OUT, 'web-api.json'), 'w', encoding='utf-8') as handle:
    json.dump(report, handle, indent=2)
print(json.dumps(report, indent=2))
