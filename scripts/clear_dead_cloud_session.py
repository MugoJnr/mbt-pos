#!/usr/bin/env python3
"""One-shot clear of dead Supabase access/refresh tokens (Edmus-class).

Keeps business_id / email / device_id / org_id. Does NOT touch license files
or mbt_pos.db. After running, open Settings → Cloud Backup and sign in once.

Usage (on the shop PC):
  "%LOCALAPPDATA%\\MugoByte\\MBT POS" identity lives under config\\cloud_identity.json
  Or from source tree:
    C:\\MBT_Build\\_python311\\python.exe scripts\\clear_dead_cloud_session.py
"""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    from backend.cloud_backup.paths import (
        cloud_identity_path,
        invalidate_cloud_session,
        load_identity,
    )
    from backend.cloud.auth_gate import clear_auth_gate_on_login, reset_for_tests

    path = cloud_identity_path()
    before = load_identity()
    print(f'identity: {path}')
    print(f'before: business_id={before.get("business_id")!r} '
          f'email={before.get("email")!r} '
          f'has_access={bool(before.get("access_token"))} '
          f'has_refresh={bool(before.get("refresh_token"))} '
          f'auth_state={before.get("auth_state")!r}')

    invalidate_cloud_session(reason='manual_clear_dead_session')
    reset_for_tests()
    clear_auth_gate_on_login()

    after = load_identity()
    print(f'after:  business_id={after.get("business_id")!r} '
          f'email={after.get("email")!r} '
          f'has_access={bool(after.get("access_token"))} '
          f'has_refresh={bool(after.get("refresh_token"))} '
          f'auth_state={after.get("auth_state")!r} '
          f'auth_error={after.get("auth_error")!r}')
    print('OK — license untouched. Sign in once under Settings → Cloud Backup.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
