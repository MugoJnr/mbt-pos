"""Bootstrap all existing Supabase businesses into organizations + trial licenses."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.cloud.platform_service import (  # noqa: E402
    ensure_org_for_business,
    list_licenses_for_org,
    service_select,
)


def main():
    businesses = service_select('businesses', 'select=*&order=created_at.asc') or []
    print(f'Found {len(businesses)} businesses')
    results = []
    for biz in businesses:
        uid = biz.get('owner_user_id') or ''
        if not uid:
            print(f'  skip {biz.get("id")} — no owner_user_id')
            continue
        org = ensure_org_for_business(biz, uid)
        licenses = list_licenses_for_org(org['id'])
        results.append({
            'business_id': biz.get('id'),
            'business_name': biz.get('name'),
            'org_id': org.get('id'),
            'org_name': org.get('name'),
            'licenses': len(licenses),
            'license_keys': [l.get('license_key') for l in licenses[:3]],
        })
        print(f'  OK {biz.get("name")} -> org {org.get("id")} · {len(licenses)} license(s)')
    out = ROOT / '_bootstrap_cloud_result.json'
    out.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(f'Wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
