"""Prove shop-without-service-key can ensure org + list own licenses via user JWT."""
from __future__ import annotations

import sys
from unittest import mock

sys.path.insert(0, __file__.rsplit("scripts", 1)[0].rstrip("\\/"))

from backend.cloud_backup.paths import load_cloud_config, load_identity
from backend.cloud_backup.supabase_client import SupabaseClient
from backend.cloud import platform_service as ps
from backend.cloud_backup.auth_service import login_existing
from _e2e_env import require_e2e_testshop


def main() -> int:
    email, password = require_e2e_testshop()

    cfg = dict(load_cloud_config())
    cfg["service_key"] = ""
    shop = SupabaseClient(config=cfg)

    with mock.patch.object(ps, "_svc", return_value=shop):
        with mock.patch(
            "backend.cloud_backup.auth_service.SupabaseClient",
            return_value=shop,
        ):
            # Clear org_id before login to force ensure path
            from backend.cloud_backup.paths import save_identity
            ident = load_identity()
            ident["org_id"] = ""
            ident["access_token"] = ""
            ident["refresh_token"] = ""
            save_identity(ident)

            r = login_existing(email, password)
            assert r.get("ok"), r
            ident = load_identity()
            print("post-login org_id", ident.get("org_id"))
            assert ident.get("org_id"), "login did not persist org_id on shop path"

            # Direct JWT select of licenses for that org
            from urllib.parse import quote
            oid = ident["org_id"]
            rows = ps.service_select(
                "licenses",
                f"org_id=eq.{quote(oid, safe='')}&select=id,license_key,status,assigned_email&limit=5",
            )
            print("licenses visible via shop JWT", len(rows or []), rows[:1] if rows else None)
            assert rows, "owner should see own-org licenses via JWT"

            # Old bug: bare anon must NOT see them
            url = shop._url("/rest/v1/licenses") + f"?org_id=eq.{oid}&select=id&limit=1"
            anon_r = shop._session.get(url, headers=shop._headers(use_service=False), timeout=30)
            print("anon status", anon_r.status_code, "body", anon_r.text[:120])
            assert anon_r.status_code < 400
            assert anon_r.json() == [] or anon_r.json() is None or anon_r.json() == []
            print("PASS shop JWT org+license path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
