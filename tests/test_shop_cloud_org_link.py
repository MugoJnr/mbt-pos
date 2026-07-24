"""Shop installs must not use bare anon for org/license REST when signed in."""
from __future__ import annotations

from backend.cloud import platform_service as ps
from backend.cloud_backup.paths import load_identity, save_identity
from backend.cloud_backup.supabase_client import SupabaseClient


def test_service_headers_use_user_jwt_without_service_key(monkeypatch):
    client = SupabaseClient(config={
        'supabase_url': 'https://example.supabase.co',
        'anon_key': 'anon-test-key',
        'service_key': '',
        'enabled': True,
    })
    monkeypatch.setattr(ps, '_svc', lambda: client)

    ident = load_identity()
    saved = dict(ident)
    try:
        ident['access_token'] = 'user-jwt-abc'
        save_identity(ident)
        headers = ps._service_headers(client)
        assert headers['apikey'] == 'anon-test-key'
        assert headers['Authorization'] == 'Bearer user-jwt-abc'
    finally:
        save_identity(saved)


def test_service_headers_prefer_service_role(monkeypatch):
    client = SupabaseClient(config={
        'supabase_url': 'https://example.supabase.co',
        'anon_key': 'anon-test-key',
        'service_key': 'service-test-key',
        'enabled': True,
    })
    monkeypatch.setattr(ps, '_svc', lambda: client)
    headers = ps._service_headers(client)
    assert headers['Authorization'] == 'Bearer service-test-key'


def test_activate_falls_back_to_portal_without_visibility(monkeypatch):
    monkeypatch.setattr(ps, 'has_service_role', lambda: False)
    monkeypatch.setattr(ps, 'service_select', lambda *a, **k: [])
    monkeypatch.setattr(
        ps,
        '_activate_license_via_portal',
        lambda *a, **k: {'ok': True, 'message': 'portal', 'license': {}, 'activation': {}},
    )
    out = ps.activate_license_on_device('MBT-TRI-TEST', 'DEV', actor_email='a@b.c')
    assert out['ok'] is True
    assert out['message'] == 'portal'
