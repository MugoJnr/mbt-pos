"""Isolated HTTP checks. The parent test sets the data root before this process starts."""
from __future__ import annotations

import json
import os
import sys

def _refuse_live() -> None:
    if os.environ.get('MBT_TEST_INSTANCE') != '1':
        raise SystemExit('refusing to import MBT without MBT_TEST_INSTANCE')
    root = (os.environ.get('MBT_DATA_ROOT') or '').strip()
    if not root:
        raise SystemExit('refusing to import MBT without MBT_DATA_ROOT')
    profile = os.environ.get('USERPROFILE') or ''
    live = os.path.normcase(os.path.join(profile, 'AppData', 'Local', 'MugoByte', 'MBT POS'))
    got = os.path.normcase(os.path.abspath(root))
    if live and (got == live or got.startswith(live + os.sep)):
        raise SystemExit('refusing to use the live shop')
    programdata = os.environ.get('PROGRAMDATA') or ''
    live_pd = os.path.normcase(r'C:\ProgramData')
    pd = os.path.normcase(os.path.abspath(programdata)) if programdata else live_pd
    if pd == live_pd or pd.startswith(live_pd + os.sep):
        raise SystemExit('refusing to use the live licence store')


_refuse_live()

from backend.app import create_app, get_db, hash_pw


def main() -> int:
    app = create_app()
    client = app.test_client()
    with app.app_context():
        db = get_db()
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('shop_name', 'Recovery Unit Shop')"
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('shop_instance_id', 'shop-http')"
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) "
            "VALUES (?, ?, 'admin', 'Shop Admin', 1)",
            ('shopadmin', hash_pw('AdminPass-1')),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) "
            "VALUES (?, ?, 'superadmin', 'Recovery Owner', 1)",
            ('owner', hash_pw('OldShop-1')),
        )
        db.commit()

    def _login(username, password):
        response = client.post('/api/auth/login', json={'username': username, 'password': password})
        body = response.get_json() or {}
        return response.status_code, body.get('token') or ''

    admin_status, admin_token = _login('shopadmin', 'AdminPass-1')
    if admin_status != 200 or not admin_token:
        print('LOGIN_ADMIN', admin_status)
        return 1
    denied = client.post(
        '/api/cloud/mbt-pos/recovery/issue',
        json={'device_id': 'MBT-PC-UNITTEST', 'shop_id': 'shop-http', 'user_id': 2, 'confirm': True},
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    owner_status, owner_token = _login('owner', 'OldShop-1')
    if owner_status != 200:
        print('LOGIN_OWNER', owner_status)
        return 1
    denied_owner = client.post(
        '/api/cloud/mbt-pos/recovery/issue',
        json={'device_id': 'MBT-PC-UNITTEST', 'shop_id': 'shop-http', 'user_id': 2, 'confirm': True},
        headers={'Authorization': f'Bearer {owner_token}'},
    )

    import backend.cloud.platform_service as platform

    def _blocked(_email):
        raise RuntimeError('do not send')

    platform.cloud_forgot_password = _blocked
    forgot = client.post('/api/cloud/auth/forgot-password', json={'email': 'person@example.com'})
    forgot_body = forgot.get_json() or {}

    issued = None
    replay_code = None
    if os.environ.get('MBT_RECOVERY_TEST_AUTH') == '1':
        import re
        headers = {'Authorization': f"Bearer {os.environ['MBT_RECOVERY_TEST_TOKEN']}"}
        looked = client.get(
            '/api/cloud/mbt-pos/recovery/lookup?device_id=' + _device_id(),
            headers=headers,
        )
        profile = looked.get_json() or {}
        if looked.status_code != 200:
            print('LOOKUP', looked.status_code, json.dumps({k: profile.get(k) for k in ('error', 'device_id', 'shop_id')}))
            return 1
        admin = next(row for row in profile['superadmins'] if row.get('active') and row.get('username') == 'owner')
        created = client.post(
            '/api/cloud/mbt-pos/recovery/issue',
            json={
                'device_id': profile['device_id'],
                'shop_id': profile['shop_id'],
                'user_id': admin['id'],
                'confirm': True,
            },
            headers=headers,
        )
        created_body = created.get_json() or {}
        if created.status_code != 200 or not created_body.get('token'):
            print('ISSUE', created.status_code, created_body.get('error'))
            return 1
        token = created_body['token']
        format_ok = bool(re.fullmatch(
            r'[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}(?:-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}){2}',
            token or '',
        ))
        if (not format_ok) or ('MBT1.' in token) or any(ch in token for ch in '01ILO'):
            print('FORMAT')
            return 1
        first = client.post(
            '/api/auth/recovery/redeem',
            json={'token': token, 'new_password': 'NewShop-1', 'confirm_password': 'NewShop-1'},
        )
        if first.status_code != 200:
            print('REDEEM', first.status_code, (first.get_json() or {}).get('error'))
            return 1
        second = client.post(
            '/api/auth/recovery/redeem',
            json={'token': token, 'new_password': 'OtherShop-2', 'confirm_password': 'OtherShop-2'},
        )
        replay_code = second.status_code
        issued = {
            'token_id': created_body.get('token_id'),
            'username': created_body.get('username'),
            'format_ok': format_ok,
        }
        with app.app_context():
            row = get_db().execute(
                "SELECT role, is_active FROM users WHERE username='owner'"
            ).fetchone()
            if row['role'] != 'superadmin' or int(row['is_active']) != 1:
                print('ROLE_CHANGED')
                return 1

    print('RESULT ' + json.dumps({
        'admin_status': denied.status_code,
        'superadmin_status': denied_owner.status_code,
        'forgot_ok': forgot.status_code == 200 and bool(forgot_body.get('ok')) and 'reset' in str(forgot_body.get('message') or '').lower(),
        'issued': issued,
        'replay_code': replay_code,
    }))
    return 0 if denied.status_code == 403 and denied_owner.status_code == 403 else 1


def _device_id() -> str:
    from backend.cloud_backup.device_manager import get_or_create_device_id
    from urllib.parse import quote
    return quote(get_or_create_device_id(), safe='')


if __name__ == '__main__':
    sys.exit(main())
