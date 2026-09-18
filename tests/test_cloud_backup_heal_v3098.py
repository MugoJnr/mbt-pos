"""v3.0.98 — cloud fail-open + auto-backup heal.

Access-only sessions must never start a backup loop.
Full refreshable sessions re-enable backup when shop auto-backup is on.
Invalidate stays quiet; portal re-login turns enabled back on.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from backend.cloud import auth_gate
from backend.cloud_backup import paths as paths_mod
from backend.cloud_backup import sync_manager as sm
from backend.cloud_backup.device_manager import update_business_identity


@pytest.fixture(autouse=True)
def _reset_gate():
    auth_gate.reset_for_tests()
    yield
    auth_gate.reset_for_tests()


def _isolate(monkeypatch, tmp_path):
    identity_path = tmp_path / 'cloud_identity.json'
    config_path = tmp_path / 'cloud_config.json'
    monkeypatch.setattr(
        paths_mod, 'cloud_identity_path', lambda: str(identity_path))
    monkeypatch.setattr(
        paths_mod, 'cloud_config_path', lambda: str(config_path))
    paths_mod.reset_sanitize_guard_for_tests()
    return identity_path, config_path


def test_access_only_blocks_backup_loop(monkeypatch, tmp_path):
    identity_path, config_path = _isolate(monkeypatch, tmp_path)
    identity_path.write_text(json.dumps({
        'business_id': 'shop-edmus',
        'access_token': 'jwt-access-only',
        'refresh_token': '',
        'cloud_skipped': False,
    }), encoding='utf-8')
    config_path.write_text(json.dumps({
        'enabled': True,
        'supabase_url': 'https://mxfvbylmlynotvghnzqg.supabase.co',
        'anon_key': 'anon',
    }), encoding='utf-8')
    paths_mod.load_identity()

    mgr = sm.SyncManager.__new__(sm.SyncManager)
    mgr._last_error = ''
    mgr._last_status = ''
    monkeypatch.setattr(sm, '_shop_auto_backup_enabled', lambda: True)

    assert paths_mod.has_refreshable_session() is False
    assert mgr._session_ready_for_backup() is False
    assert auth_gate.cloud_sync_should_run() is False
    # Heal must not flip enabled on for access-only.
    mgr._ensure_cloud_backup_enabled()
    assert paths_mod.load_cloud_config().get('enabled') is True  # unchanged; session still not ready


def test_full_session_re_enables_backup(monkeypatch, tmp_path):
    identity_path, config_path = _isolate(monkeypatch, tmp_path)
    identity_path.write_text(json.dumps({
        'business_id': 'shop-1',
        'access_token': 'jwt-access',
        'refresh_token': 'jwt-refresh',
        'cloud_skipped': False,
    }), encoding='utf-8')
    config_path.write_text(json.dumps({
        'enabled': False,
        'supabase_url': 'https://mxfvbylmlynotvghnzqg.supabase.co',
        'anon_key': 'anon',
    }), encoding='utf-8')
    paths_mod.load_identity()

    mgr = sm.SyncManager.__new__(sm.SyncManager)
    mgr._last_error = ''
    mgr._last_status = ''
    monkeypatch.setattr(sm, '_shop_auto_backup_enabled', lambda: True)

    assert paths_mod.has_refreshable_session() is True
    assert mgr._session_ready_for_backup() is True
    assert paths_mod.load_cloud_config().get('enabled') is True


def test_invalidate_quiet_disables_backup(monkeypatch, tmp_path):
    identity_path, config_path = _isolate(monkeypatch, tmp_path)
    identity_path.write_text(json.dumps({
        'business_id': 'shop-1',
        'email': 'a@b.com',
        'access_token': 'a',
        'refresh_token': 'r',
    }), encoding='utf-8')
    config_path.write_text(json.dumps({
        'enabled': True,
        'supabase_url': 'https://example.supabase.co',
        'anon_key': 'anon',
    }), encoding='utf-8')
    paths_mod.load_identity()

    paths_mod.invalidate_cloud_session(reason='test_quiet')
    auth_gate.note_refresh_failure(
        'Invalid Refresh Token', status=401, terminal=True)

    assert paths_mod.load_cloud_config().get('enabled') is False
    assert paths_mod.is_logged_in() is False
    assert auth_gate.cloud_sync_should_run() is False
    assert auth_gate.should_show_platform_auth_toast() is True
    assert auth_gate.should_show_platform_auth_toast() is False  # once


def test_relogin_clears_reauth_and_enables(monkeypatch, tmp_path):
    identity_path, config_path = _isolate(monkeypatch, tmp_path)
    identity_path.write_text(json.dumps({
        'business_id': 'shop-1',
        'email': 'a@b.com',
        'access_token': '',
        'refresh_token': '',
        'auth_state': paths_mod.REAUTH_REQUIRED,
        'auth_error': 'invalid_refresh_token',
        'device_id': 'MBT-PC-TEST',
    }), encoding='utf-8')
    config_path.write_text(json.dumps({
        'enabled': False,
        'supabase_url': 'https://example.supabase.co',
        'anon_key': 'anon',
    }), encoding='utf-8')
    auth_gate.note_refresh_failure(
        'Invalid Refresh Token', status=401, terminal=True)
    assert auth_gate.is_terminal_auth_dead() is True

    with patch(
        'backend.cloud_backup.device_manager.platform'
    ) as plat:
        plat.node.return_value = 'TEST-PC'
        plat.platform.return_value = 'Windows'
        update_business_identity(
            business_id='shop-1',
            business_name='Shop',
            user_id='user-1',
            email='a@b.com',
            access_token='new-access',
            refresh_token='new-refresh',
        )

    ident = paths_mod.load_identity()
    assert ident.get('auth_state') in (None, '')
    assert paths_mod.has_refreshable_session() is True
    assert auth_gate.is_terminal_auth_dead() is False
    assert auth_gate.cloud_sync_should_run() is True

    # Mirror auth_service login_existing enabling backup after refresh check.
    cfg = paths_mod.load_cloud_config()
    cfg['enabled'] = True
    paths_mod.save_cloud_config(cfg)
    assert paths_mod.load_cloud_config().get('enabled') is True


def test_defaults_portal_anon_only():
    from backend.cloud_backup.defaults import (
        PRODUCTION_PROJECT_REF,
        production_cloud_defaults,
    )
    d = production_cloud_defaults()
    assert PRODUCTION_PROJECT_REF == 'mxfvbylmlynotvghnzqg'
    assert 'mxfvbylmlynotvghnzqg' in d['supabase_url']
    assert not (d.get('service_key') or '').strip()
    assert (d.get('anon_key') or '').startswith('eyJ')
    # Never ship service_role material in production defaults module source.
    import inspect
    from backend.cloud_backup import defaults as defaults_mod
    src = inspect.getsource(defaults_mod)
    assert 'service_role' not in src
    assert 'eyJ' in src  # anon present
