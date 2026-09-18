"""v3.0.94 — invalid refresh token fail-open (Edmus hang class)."""
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


def _client() -> sc.SupabaseClient:
    return sc.SupabaseClient({
        'supabase_url': 'https://example.supabase.co',
        'anon_key': 'anon',
        'bucket': 'mbt-backups',
    })


def _isolate_identity(monkeypatch, tmp_path):
    identity_path = tmp_path / 'cloud_identity.json'
    monkeypatch.setattr(
        paths_mod, 'cloud_identity_path', lambda: str(identity_path))
    return identity_path


def test_invalid_refresh_clears_tokens_and_sets_reauth(monkeypatch, tmp_path):
    identity_path = _isolate_identity(monkeypatch, tmp_path)
    identity_path.write_text(json.dumps({
        'business_id': 'shop-edmus',
        'email': 'edmus.cloud@gmail.com',
        'access_token': 'stale-access',
        'refresh_token': 'dead-refresh',
        'device_id': 'MBT-PC-52E6',
    }), encoding='utf-8')
    # Migrate plaintext → protected on first load
    paths_mod.load_identity()

    client = _client()
    monkeypatch.setattr(sc, '_require_network', lambda: None)
    from backend.cloud import auth_gate
    monkeypatch.setattr(auth_gate, 'assert_not_ui_thread', lambda _action: None)

    class _Resp:
        status_code = 400
        text = 'Invalid Refresh Token: Refresh Token Not Found'

        def json(self):
            return {
                'error': 'invalid_grant',
                'msg': 'Invalid Refresh Token: Refresh Token Not Found',
            }

    monkeypatch.setattr(client._session, 'post', lambda *a, **k: _Resp())

    with pytest.raises(sc.SupabaseAuthError):
        client.refresh_session()

    ident = paths_mod.load_identity()
    assert ident.get('access_token') == ''
    assert ident.get('refresh_token') == ''
    assert ident.get('access_token_protected') in ('', None)
    assert ident.get('refresh_token_protected') in ('', None)
    assert ident.get('auth_state') == paths_mod.REAUTH_REQUIRED
    assert ident.get('auth_error') == paths_mod.AUTH_ERROR_INVALID_REFRESH
    assert ident.get('business_id') == 'shop-edmus'
    assert ident.get('email') == 'edmus.cloud@gmail.com'
    assert ident.get('device_id') == 'MBT-PC-52E6'
    assert auth_gate.is_terminal_auth_dead() is True
    assert paths_mod.is_logged_in() is False
    assert auth_gate.cloud_sync_should_run() is False


def test_with_auth_retry_stops_after_terminal_refresh(monkeypatch, tmp_path):
    _isolate_identity(monkeypatch, tmp_path)
    paths_mod.save_identity({
        'business_id': 'shop-1',
        'access_token': 'expired',
        'refresh_token': 'dead',
    })
    client = _client()
    refreshes = []

    def _boom():
        refreshes.append(1)
        auth_gate.note_refresh_failure(
            'Invalid Refresh Token: Refresh Token Not Found',
            status=400,
            terminal=True,
        )
        raise sc.SupabaseAuthError('Invalid Refresh Token')

    monkeypatch.setattr(client, 'refresh_session', _boom)
    work = MagicMock(side_effect=sc.SupabaseError('Unauthorized', status=401))

    with pytest.raises(sc.SupabaseAuthError):
        client.with_auth_retry(work)
    assert len(refreshes) == 1

    # Second call must not refresh again
    with pytest.raises(sc.SupabaseAuthError):
        client.with_auth_retry(work)
    assert len(refreshes) == 1
    assert auth_gate.cloud_sync_should_run() is False


def test_refresh_cooldown_after_non_terminal_failure(monkeypatch, tmp_path):
    _isolate_identity(monkeypatch, tmp_path)
    paths_mod.save_identity({
        'business_id': 'shop-1',
        'access_token': 'a',
        'refresh_token': 'r',
    })
    assert auth_gate.allow_refresh_attempt() is True
    auth_gate.note_refresh_failure('timeout', status=503, terminal=False)
    assert auth_gate.allow_refresh_attempt() is False
    assert auth_gate.seconds_until_refresh_allowed() > 0
    assert auth_gate.is_terminal_auth_dead() is False


def test_toast_once_then_silence():
    assert auth_gate.should_show_platform_auth_toast() is True
    assert auth_gate.should_show_platform_auth_toast() is False
    assert auth_gate.should_show_platform_auth_toast() is False
    auth_gate.clear_auth_gate_on_login()
    # Re-login re-arms one toast for a future auth death
    assert auth_gate.should_show_platform_auth_toast() is True
    assert auth_gate.should_show_platform_auth_toast() is False


def test_platform_auth_message_detection():
    assert auth_gate.is_platform_auth_message(
        'Invalid Refresh Token: Refresh Token Not Found')
    assert auth_gate.is_platform_auth_message(
        'MugoByte Platform: session expired')
    assert not auth_gate.is_platform_auth_message('Printer offline')


def test_refresh_refused_on_ui_thread(monkeypatch, tmp_path):
    _isolate_identity(monkeypatch, tmp_path)
    paths_mod.save_identity({
        'business_id': 'shop-1',
        'access_token': 'a',
        'refresh_token': 'r',
    })
    client = _client()

    class _App:
        def thread(self):
            return 'ui-thread'

    class _FakeQtCore:
        class QThread:
            @staticmethod
            def currentThread():
                return 'ui-thread'

    class _FakeQtWidgets:
        class QApplication:
            @staticmethod
            def instance():
                return _App()

    import sys
    monkeypatch.setitem(sys.modules, 'PyQt5', MagicMock())
    monkeypatch.setitem(sys.modules, 'PyQt5.QtCore', _FakeQtCore)
    monkeypatch.setitem(sys.modules, 'PyQt5.QtWidgets', _FakeQtWidgets)

    with pytest.raises(RuntimeError, match='UI thread'):
        auth_gate.assert_not_ui_thread('refresh_session')

    with pytest.raises(RuntimeError, match='UI thread'):
        client.refresh_session()


def test_invalidate_helper_preserves_identity(monkeypatch, tmp_path):
    _isolate_identity(monkeypatch, tmp_path)
    paths_mod.save_identity({
        'business_id': 'shop-edmus',
        'email': 'edmus.cloud@gmail.com',
        'org_id': 'org-1',
        'device_id': 'MBT-PC-52E6',
        'access_token': 'a',
        'refresh_token': 'r',
    })
    paths_mod.invalidate_cloud_session(reason='manual_clear')
    ident = paths_mod.load_identity()
    assert ident['business_id'] == 'shop-edmus'
    assert ident['email'] == 'edmus.cloud@gmail.com'
    assert ident['device_id'] == 'MBT-PC-52E6'
    assert ident['access_token'] == ''
    assert ident['auth_state'] == paths_mod.REAUTH_REQUIRED
