# -*- coding: utf-8 -*-
"""One-shot: rename local + portal business to testshop and reprovision tunnel."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NEW_NAME = 'testshop'


def main() -> int:
    from mbt_paths import get_db_path, get_project_root, ensure_data_dirs
    ensure_data_dirs(get_project_root())

    db_path = get_db_path()
    print(f'DB: {db_path}')
    db = sqlite3.connect(db_path)
    db.execute(
        "INSERT INTO system_settings(key, value) VALUES('shop_name', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (NEW_NAME,),
    )
    db.commit()
    row = db.execute("SELECT value FROM system_settings WHERE key='shop_name'").fetchone()
    print(f'shop_name -> {row[0]!r}')

    ident_path = Path(get_project_root()) / 'config' / 'cloud_identity.json'
    if ident_path.is_file():
        ident = json.loads(ident_path.read_text(encoding='utf-8'))
        ident['business_name'] = NEW_NAME
        ident_path.write_text(json.dumps(ident, indent=2) + '\n', encoding='utf-8')
        print(f'cloud_identity business_name -> {NEW_NAME}')
        org_id = ident.get('org_id')
        biz_id = ident.get('business_id')
        user_id = ident.get('user_id')
    else:
        print('WARN: no cloud_identity.json')
        org_id = biz_id = user_id = None

    from backend.cloud.platform_service import service_update, service_select
    from backend.cloud.platform_service import slugify

    if org_id:
        service_update(
            'organizations',
            f'id=eq.{quote(str(org_id), safe="")}',
            {'name': NEW_NAME},
        )
        print(f'Portal org {org_id} name -> {NEW_NAME}')
    if biz_id:
        service_update(
            'businesses',
            f'id=eq.{quote(str(biz_id), safe="")}',
            {'name': NEW_NAME},
        )
        print(f'Portal business {biz_id} name -> {NEW_NAME}')

    from backend.cloudflare_setup import (
        shop_to_subdomain,
        full_domain,
        provision_shop_tunnel_via_api,
        load_web_config,
    )
    slug = shop_to_subdomain(NEW_NAME)
    domain = full_domain(slug)
    print(f'Tunnel slug: {slug} -> https://{domain}')

    # Re-provision remote tunnel (new hostname, new tunnel name mbt-pos-testshop)
    try:
        result = provision_shop_tunnel_via_api(NEW_NAME)
        print('Provision OK:', result.get('domain'), result.get('tunnel_name'))
    except Exception as e:
        print(f'Provision failed: {e}')
        print('Update web_config subdomain manually and re-run Cloudflare setup from Settings.')
        return 1

    cfg = load_web_config()
    print('web_config tunnel_domain:', cfg.get('tunnel_domain'))
    print('Done. Restart MBT POS (or restart cloudflared) so the new tunnel connects.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
