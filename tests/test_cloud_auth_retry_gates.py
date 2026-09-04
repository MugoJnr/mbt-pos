"""Cloud session recovery: expired-JWT retry and unreadable protected tokens.

Storage rejects a stale access token with HTTP 400 (`"exp" claim timestamp
check failed`) instead of 401, which used to strand every upload. No network
is used here — the HTTP layer is stubbed.
"""
from __future__ import annotations

import json

import pytest

from backend.cloud_backup import paths as paths_mod
from backend.cloud_backup import supabase_client as sc

EXPIRED_MSG = '"exp" claim timestamp check failed'
FAKE_JWT = (
    'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0LXVzZXIiLCJleHAiOjF9'
    '.c2lnbmF0dXJlLXZhbHVl'
)


def _client() -> sc.SupabaseClient:
    return sc.SupabaseClient({
        'supabase_url': 'https://example.supabase.co',
        'anon_key': 'anon',
        'bucket': 'mbt-backups',
    })


class _Recorder:
    """Fails the first N attempts with `error`, then succeeds."""

    def __init__(self, error: Exception, failures: int = 1):
        self.error = error
        self.failures = failures
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return 'ok'


def test_expired_jwt_400_refreshes_once_and_succeeds(monkeypatch):
    client = _client()
    refreshes = []
    monkeypatch.setattr(
        client, 'refresh_session', lambda: refreshes.append(1))
    work = _Recorder(sc.SupabaseError(EXPIRED_MSG, status=400))

    assert client.with_auth_retry(work) == 'ok'
    assert work.calls == 2
    assert len(refreshes) == 1


def test_expired_jwt_retry_happens_at_most_once(monkeypatch):
    client = _client()
    refreshes = []
    monkeypatch.setattr(
        client, 'refresh_session', lambda: refreshes.append(1))
    work = _Recorder(sc.SupabaseError(EXPIRED_MSG, status=400), failures=5)

    with pytest.raises(sc.SupabaseError):
        client.with_auth_retry(work)
    assert work.calls == 2
    assert len(refreshes) == 1


def test_refresh_failure_propagates_without_further_attempts(monkeypatch):
    client = _client()

    def _boom():
        raise sc.SupabaseError('No refresh token')

    monkeypatch.setattr(client, 'refresh_session', _boom)
    work = _Recorder(sc.SupabaseError(EXPIRED_MSG, status=400), failures=5)

    with pytest.raises(sc.SupabaseError, match='No refresh token'):
        client.with_auth_retry(work)
    assert work.calls == 1


def test_ordinary_400_is_not_retried(monkeypatch):
    client = _client()
    refreshes = []
    monkeypatch.setattr(
        client, 'refresh_session', lambda: refreshes.append(1))
    work = _Recorder(
        sc.SupabaseError('Invalid bucket name', status=400), failures=5)

    with pytest.raises(sc.SupabaseError, match='Invalid bucket name'):
        client.with_auth_retry(work)
    assert work.calls == 1
    assert refreshes == []


@pytest.mark.parametrize('status', [401, 403])
def test_classic_auth_statuses_still_refresh_once(monkeypatch, status):
    client = _client()
    refreshes = []
    monkeypatch.setattr(
        client, 'refresh_session', lambda: refreshes.append(1))
    work = _Recorder(sc.SupabaseError('Unauthorized', status=status))

    assert client.with_auth_retry(work) == 'ok'
    assert work.calls == 2
    assert len(refreshes) == 1


def test_error_messages_never_carry_token_material():
    error = sc.SupabaseError(
        f'Storage upload failed for Bearer {FAKE_JWT}', status=400)
    assert FAKE_JWT not in str(error)
    assert '<redacted-token>' in str(error)
    assert sc.redact_tokens(f'apikey={FAKE_JWT}') == 'apikey=<redacted-token>'


def test_expired_session_detection_is_narrow():
    assert sc._looks_like_expired_session(
        sc.SupabaseError(EXPIRED_MSG, status=400))
    assert sc._looks_like_expired_session(
        sc.SupabaseError('JWT expired', status=400))
    assert not sc._looks_like_expired_session(
        sc.SupabaseError('Duplicate object name', status=400))


def test_upload_retries_expired_session_before_service_fallback(
    monkeypatch, tmp_path,
):
    payload = tmp_path / 'backup.mbtenc'
    payload.write_bytes(b'encrypted')
    client = _client()
    monkeypatch.setattr(client, 'access_token', lambda: 'stale-token')
    monkeypatch.setattr(client, 'refresh_session', lambda: None)

    attempts = {'n': 0}

    class _Response:
        def __init__(self, status):
            self.status_code = status
            self.text = ''

        def json(self):
            return {'message': EXPIRED_MSG} if self.status_code >= 400 else {}

    def _post(url, headers=None, data=None, timeout=None):
        attempts['n'] += 1
        return _Response(400 if attempts['n'] == 1 else 200)

    monkeypatch.setattr(client._session, 'post', _post)
    assert client.upload_file('shop/backup.mbtenc', str(payload)) == \
        'shop/backup.mbtenc'
    assert attempts['n'] == 2


# ── unreadable DPAPI-protected identity ──────────────────────────────────────

def _isolate_identity(monkeypatch, tmp_path):
    identity_path = tmp_path / 'cloud_identity.json'
    monkeypatch.setattr(
        paths_mod, 'cloud_identity_path', lambda: str(identity_path))
    return identity_path


def test_unreadable_protected_tokens_demand_reauth_without_destroying_them(
    monkeypatch, tmp_path, caplog,
):
    identity_path = _isolate_identity(monkeypatch, tmp_path)
    foreign_access = 'gAAAAABmZm9yZWlnbi1jaXBoZXJ0ZXh0'
    foreign_refresh = 'gAAAAABmZm9yZWlnbi1yZWZyZXNo'
    identity_path.write_text(json.dumps({
        'business_id': 'shop-1',
        'email': 'owner@example.com',
        # Ciphertext sealed by another install — undecryptable here.
        'access_token_protected': foreign_access,
        'refresh_token_protected': foreign_refresh,
    }), encoding='utf-8')

    with caplog.at_level('WARNING'):
        first = paths_mod.load_identity()
    assert first['access_token'] == ''
    assert first['refresh_token'] == ''
    assert first['auth_state'] == paths_mod.REAUTH_REQUIRED
    assert first['auth_error'] == 'protected_token_unreadable'
    first_warnings = len(caplog.records)
    assert first_warnings >= 1

    # The sealed values survive: restoring the original config/.jwt_secret is
    # the only way back to the session. A second load stays quiet instead of
    # churning a warning on every status poll.
    stored = json.loads(identity_path.read_text(encoding='utf-8'))
    assert stored['access_token_protected'] == foreign_access
    assert stored['refresh_token_protected'] == foreign_refresh
    assert stored['auth_unreadable_id']
    caplog.clear()
    with caplog.at_level('WARNING'):
        second = paths_mod.load_identity()
    assert caplog.records == []
    assert second['auth_state'] == paths_mod.REAUTH_REQUIRED

    assert paths_mod.is_logged_in() is False
    status = paths_mod.cloud_auth_status()
    assert status['reauth_required'] is True
    assert status['logged_in'] is False
    assert 'Sign in again' in status['message']
    # Status text must describe the problem, never the token.
    assert 'gAAAAAB' not in json.dumps(status)


def test_successful_sign_in_clears_the_reauth_flag(monkeypatch, tmp_path):
    identity_path = _isolate_identity(monkeypatch, tmp_path)
    identity_path.write_text(json.dumps({
        'business_id': 'shop-1',
        'access_token_protected': 'gAAAAABmYnJva2Vu',
        'auth_state': paths_mod.REAUTH_REQUIRED,
    }), encoding='utf-8')
    paths_mod.load_identity()

    paths_mod.save_identity({
        'business_id': 'shop-1',
        'access_token': 'fresh-access',
        'refresh_token': 'fresh-refresh',
        'auth_state': paths_mod.REAUTH_REQUIRED,
    })
    reloaded = paths_mod.load_identity()
    assert reloaded['access_token'] == 'fresh-access'
    assert 'auth_state' not in reloaded
    assert paths_mod.cloud_auth_status()['reauth_required'] is False


def test_sync_status_surfaces_reauth_requirement(monkeypatch, tmp_path):
    from backend.cloud_backup import sync_manager as sm_mod

    _isolate_identity(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sm_mod, 'offline_queue_path', lambda: str(tmp_path / 'queue.json'))
    monkeypatch.setattr(
        sm_mod, 'backup_state_path', lambda: str(tmp_path / 'state.json'))
    monkeypatch.setattr(sm_mod, 'is_cloud_configured', lambda: True)
    monkeypatch.setattr(sm_mod, 'is_logged_in', lambda: False)
    monkeypatch.setattr(sm_mod, 'load_identity', lambda: {
        'business_id': 'shop-1',
        'auth_state': paths_mod.REAUTH_REQUIRED,
    })

    status = sm_mod.SyncManager().status()
    assert status['reauth_required'] is True
    assert status['logged_in'] is False
