"""v3.0.97 — cloud session health (Edmus hang class).

Access-only sessions must not count as logged in; missing refresh must
invalidate once and disable backup; SyncManager stays quiet.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from backend.cloud import auth_gate
from backend.cloud_backup import paths as paths_mod
from backend.cloud_backup import supabase_client as sc


@pytest.fixture(autouse=True)
def _reset_gate():
    auth_gate.reset_for_tests()
    yield
    auth_gate.reset_for_tests()


def _isolate_identity(monkeypatch, tmp_path):
    identity_path = tmp_path / 'cloud_identity.json'
    config_path = tmp_path / 'cloud_config.json'
    monkeypatch.setattr(
        paths_mod, 'cloud_identity_path', lambda: str(identity_path))
    monkeypatch.setattr(
        paths_mod, 'cloud_config_path', lambda: str(config_path))
    paths_mod.reset_sanitize_guard_for_tests()
    return identity_path, config_path


def test_access_only_not_logged_in(monkeypatch, tmp_path):
    """Edmus scenario: access token without refresh ⇒ not logged in."""
    identity_path, _ = _isolate_identity(monkeypatch, tmp_path)
    identity_path.write_text(json.dumps({
        'business_id': 'shop-edmus',
        'email': 'edmus.cloud@gmail.com',
        'access_token': 'jwt-access-only',
        'refresh_token': '',
        'cloud_skipped': False,
        'device_id': 'MBT-PC-52E6',
    }), encoding='utf-8')

    assert paths_mod.has_refreshable_session() is False
    assert paths_mod.is_logged_in() is False
    status = paths_mod.cloud_auth_status()
    assert status['logged_in'] is False
    assert auth_gate.cloud_sync_should_run() is False


def test_both_tokens_logged_in(monkeypatch, tmp_path):
    identity_path, _ = _isolate_identity(monkeypatch, tmp_path)
    identity_path.write_text(json.dumps({
        'business_id': 'shop-1',
        'access_token': 'jwt-access',
        'refresh_token': 'jwt-refresh',
        'cloud_skipped': False,
    }), encoding='utf-8')

    assert paths_mod.has_refreshable_session() is True
    assert paths_mod.is_logged_in() is True
    assert paths_mod.cloud_auth_status()['logged_in'] is True


def test_cloud_skipped_not_logged_in(monkeypatch, tmp_path):
    identity_path, _ = _isolate_identity(monkeypatch, tmp_path)
    identity_path.write_text(json.dumps({
        'business_id': 'shop-1',
        'access_token': 'a',
        'refresh_token': 'r',
        'cloud_skipped': True,
    }), encoding='utf-8')
    assert paths_mod.is_logged_in() is False


def test_invalidate_clears_tokens_and_disables_backup(monkeypatch, tmp_path):
    identity_path, config_path = _isolate_identity(monkeypatch, tmp_path)
    identity_path.write_text(json.dumps({
        'business_id': 'shop-edmus',
        'email': 'edmus.cloud@gmail.com',
        'access_token': 'a',
        'refresh_token': 'r',
        'device_id': 'MBT-PC-52E6',
    }), encoding='utf-8')
    config_path.write_text(json.dumps({
        'enabled': True,
        'supabase_url': 'https://example.supabase.co',
        'anon_key': 'anon',
    }), encoding='utf-8')
    paths_mod.load_identity()  # migrate plaintext → protected

    paths_mod.invalidate_cloud_session(reason='test_invalidate')

    ident = paths_mod.load_identity()
    assert ident.get('access_token') == ''
    assert ident.get('refresh_token') == ''
    assert ident.get('auth_state') == paths_mod.REAUTH_REQUIRED
    assert ident.get('business_id') == 'shop-edmus'
    assert ident.get('email') == 'edmus.cloud@gmail.com'
    cfg = paths_mod.load_cloud_config()
    assert cfg.get('enabled') is False
    assert paths_mod.is_logged_in() is False


def test_refresh_without_token_invalidates_once(monkeypatch, tmp_path):
    identity_path, config_path = _isolate_identity(monkeypatch, tmp_path)
    identity_path.write_text(json.dumps({
        'business_id': 'shop-edmus',
        'access_token': 'jwt-access-only',
        'refresh_token': '',
    }), encoding='utf-8')
    config_path.write_text(json.dumps({
        'enabled': True,
        'supabase_url': 'https://example.supabase.co',
        'anon_key': 'anon',
    }), encoding='utf-8')
    paths_mod.load_identity()

    client = sc.SupabaseClient({
        'supabase_url': 'https://example.supabase.co',
        'anon_key': 'anon',
        'bucket': 'mbt-backups',
    })
    post = MagicMock(side_effect=AssertionError('network must not be called'))
    monkeypatch.setattr(client._session, 'post', post)
    monkeypatch.setattr(sc, '_require_network', lambda: None)

    with pytest.raises(sc.SupabaseAuthError, match='No refresh token'):
        client.refresh_session()

    post.assert_not_called()
    assert auth_gate.is_terminal_auth_dead() is True
    ident = paths_mod.load_identity()
    assert ident.get('access_token') == ''
    assert ident.get('refresh_token') == ''
    assert ident.get('auth_state') == paths_mod.REAUTH_REQUIRED
    assert paths_mod.load_cloud_config().get('enabled') is False
    assert paths_mod.is_logged_in() is False

    # Second call must not hit the network either (gate / reauth short-circuit).
    with pytest.raises(sc.SupabaseAuthError):
        client.refresh_session()
    post.assert_not_called()


def test_auth_gate_single_cloud_sync_should_run():
    """Duplicate definition was a hang/spin risk — keep one with identity_blocks."""
    import inspect
    source = inspect.getsource(auth_gate)
    # Exactly one def cloud_sync_should_run
    assert source.count('def cloud_sync_should_run') == 1
    assert 'identity_blocks_cloud_sync' in inspect.getsource(
        auth_gate.cloud_sync_should_run)
