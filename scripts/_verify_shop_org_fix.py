"""Verify shop-path org resolve + activation without service_key."""
from __future__ import annotations

import copy
import sys
from unittest import mock

ROOT = __file__.rsplit("scripts", 1)[0].rstrip("\\/")
sys.path.insert(0, ROOT)

from backend.cloud_backup.paths import load_cloud_config, load_identity, save_identity
from backend.cloud_backup.supabase_client import SupabaseClient
from backend.cloud import platform_service as ps
from licensing.cloud_onboarding import _resolve_org_id


def _shop_client():
    cfg = dict(load_cloud_config())
    cfg["service_key"] = ""
    return SupabaseClient(config=cfg)


def main() -> int:
    # --- 1) Headers use user JWT when no service key ---
    client = _shop_client()
    with mock.patch.object(ps, "_svc", return_value=client):
        # Without login token → anon bearer
        ident = load_identity()
        saved = copy.deepcopy(ident)
        try:
            blank = dict(ident)
            blank["access_token"] = ""
            blank["access_token_protected"] = ""
            save_identity(blank)
            h = ps._service_headers(client)
            assert h["Authorization"].endswith(client.anon[:20]) or client.anon in h["Authorization"]
            print("PASS headers fall back to anon when logged out")

            # Fake token
            blank["access_token"] = "shop-user-jwt-token"
            save_identity(blank)
            h2 = ps._service_headers(client)
            assert "shop-user-jwt-token" in h2["Authorization"]
            print("PASS headers use identity JWT when no service_key")
        finally:
            save_identity(saved)

    # --- 2) ensure_org / resolve for EDMUS with JWT (real login optional) ---
    # Sign in as edmus if we can use password from env; otherwise dry-check helpers.
    print("has_service_role (dev machine):", ps.has_service_role())

    # Simulate shop: strip service key for resolve path after injecting a session
    # by signing in via auth API with anon (real credentials only if provided).
    import os
    email = (os.environ.get("MBT_TEST_EMAIL") or "").strip()
    password = (os.environ.get("MBT_TEST_PASSWORD") or "").strip()
    if email and password:
        cfg = dict(load_cloud_config())
        cfg["service_key"] = ""
        shop = SupabaseClient(config=cfg)
        with mock.patch.object(ps, "_svc", return_value=shop):
            # Also patch SupabaseClient() default used by auth
            with mock.patch(
                "backend.cloud_backup.auth_service.SupabaseClient",
                return_value=shop,
            ):
                from backend.cloud_backup.auth_service import login_existing
                from licensing import cloud_onboarding as co

                login = login_existing(email, password)
                print("login ok", login.get("ok"), "biz", login.get("business_id"))
                ident = load_identity()
                print("identity org_id", ident.get("org_id"), "user", ident.get("user_id"))
                # Force clear org_id to test resolve
                ident["org_id"] = ""
                save_identity(ident)
                oid = co._resolve_org_id(load_identity())
                print("resolved org", oid)
                assert oid, "FAIL: org resolve returned empty on shop path"
                print("PASS shop org resolve after login")
    else:
        print("SKIP live login (set MBT_TEST_EMAIL / MBT_TEST_PASSWORD)")

    # --- 3) Portal public activate endpoint exists in routes ---
    from web import web_routes
    src = open(web_routes.__file__, encoding="utf-8").read()
    assert "/api/public/licenses/activate" in src
    print("PASS public activate route defined")

    # --- 4) activate falls back to portal when no rows / no service ---
    with mock.patch.object(ps, "has_service_role", return_value=False):
        with mock.patch.object(ps, "service_select", return_value=[]):
            with mock.patch.object(
                ps,
                "_activate_license_via_portal",
                return_value={"ok": True, "message": "via portal", "license": {}, "activation": {}},
            ) as m:
                out = ps.activate_license_on_device("MBT-TRI-TEST", "DEV1", actor_email="a@b.c")
                assert out.get("ok") is True
                assert m.called
                print("PASS activate_license_on_device portals when shop has no key visibility")

    print("ALL CHECKS DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
