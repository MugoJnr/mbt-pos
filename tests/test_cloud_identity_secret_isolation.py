"""Cloud identity must never be usable — or destroyed — across data roots.

Every data root seals ``config/cloud_identity.json`` with its own
``config/.jwt_secret``. A process reading another root's identity therefore
decrypts nothing. These tests pin the two halves of the required behaviour:

* fail closed — an undecryptable identity is never treated as signed in, and
  no HTTP call or refresh attempt is made on its behalf;
* fail non-destructively — the sealed ciphertext survives, because restoring
  the original secret is the only route back to that session.

No network and no real tokens: the Fernet secret is swapped in-process.
"""
from __future__ import annotations

import json

import pytest

import mbt_paths
from backend.cloud_backup import device_manager as dm_mod
from backend.cloud_backup import paths as paths_mod
from backend.cloud_backup import supabase_client as sc

SECRET_A = 'root-a-secret-value-0123456789abcdefghijklmnop'
SECRET_B = 'root-b-secret-value-zyxwvutsrqponmlkjihgfedcba'


@pytest.fixture
def identity_file(monkeypatch, tmp_path):
    path = tmp_path / 'cloud_identity.json'
    monkeypatch.setattr(paths_mod, 'cloud_identity_path', lambda: str(path))
    return path


def _use_secret(monkeypatch, secret: str) -> None:
    monkeypatch.setattr(paths_mod, 'get_jwt_secret', lambda: secret)


def _client() -> sc.SupabaseClient:
    return sc.SupabaseClient({
        'supabase_url': 'https://example.supabase.co',
        'anon_key': 'anon',
        'bucket': 'mbt-backups',
    })


def _no_http(client, monkeypatch) -> list:
    """Make any HTTP verb on the client's session fail the test loudly."""
    calls: list = []

    def _boom(*a, **kw):
        calls.append(a[0] if a else kw.get('url'))
        raise AssertionError(f'unexpected network call: {calls[-1]}')

    for verb in ('get', 'post', 'patch', 'put'):
        monkeypatch.setattr(client._session, verb, _boom)
    return calls


# ── non-destructive fail-closed ───────────────────────────────────────────────

def test_foreign_root_identity_is_not_signed_in_and_survives(
    monkeypatch, identity_file,
):
    _use_secret(monkeypatch, SECRET_A)
    paths_mod.save_identity({
        'business_id': 'shop-1',
        'email': 'owner@example.com',
        'access_token': 'access-token-from-root-a',
        'refresh_token': 'refresh-token-from-root-a',
    })
    sealed = json.loads(identity_file.read_text(encoding='utf-8'))
    sealed_access = sealed['access_token_protected']
    sealed_refresh = sealed['refresh_token_protected']
    assert 'access-token-from-root-a' not in identity_file.read_text(
        encoding='utf-8')

    # Same file, other root's secret: nothing decrypts.
    _use_secret(monkeypatch, SECRET_B)
    foreign = paths_mod.load_identity()
    assert foreign['access_token'] == ''
    assert foreign['refresh_token'] == ''
    assert foreign['auth_state'] == paths_mod.REAUTH_REQUIRED
    assert paths_mod.is_logged_in() is False
    assert paths_mod.identity_needs_reauth() is True

    on_disk = json.loads(identity_file.read_text(encoding='utf-8'))
    assert on_disk['access_token_protected'] == sealed_access
    assert on_disk['refresh_token_protected'] == sealed_refresh

    # Back on the original root the session is intact and self-heals.
    _use_secret(monkeypatch, SECRET_A)
    restored = paths_mod.load_identity()
    assert restored['access_token'] == 'access-token-from-root-a'
    assert restored['refresh_token'] == 'refresh-token-from-root-a'
    assert 'auth_state' not in restored
    assert paths_mod.identity_needs_reauth() is False


def test_reauth_warning_and_status_carry_no_token_material(
    monkeypatch, identity_file, caplog,
):
    _use_secret(monkeypatch, SECRET_A)
    paths_mod.save_identity({
        'business_id': 'shop-1',
        'email': 'owner@example.com',
        'access_token': 'access-token-from-root-a',
        'refresh_token': 'refresh-token-from-root-a',
    })
    sealed = json.loads(identity_file.read_text(encoding='utf-8'))

    _use_secret(monkeypatch, SECRET_B)
    with caplog.at_level('DEBUG'):
        paths_mod.load_identity()
        status = paths_mod.cloud_auth_status()
    logged = caplog.text
    for secret in (SECRET_A, SECRET_B):
        assert secret not in logged
    for field in ('access_token_protected', 'refresh_token_protected'):
        assert sealed[field] not in logged
        assert sealed[field] not in json.dumps(status)
    assert 'access-token-from-root-a' not in logged
    assert status['reauth_required'] is True
    assert status['logged_in'] is False


def test_repeated_loads_do_not_rewrite_or_re_warn(monkeypatch, identity_file):
    _use_secret(monkeypatch, SECRET_A)
    paths_mod.save_identity({
        'business_id': 'shop-1',
        'access_token': 'access-token-from-root-a',
    })
    _use_secret(monkeypatch, SECRET_B)

    paths_mod.load_identity()
    first = identity_file.read_text(encoding='utf-8')

    writes: list = []
    real_save = paths_mod.save_json
    monkeypatch.setattr(
        paths_mod, 'save_json',
        lambda path, data: (writes.append(path), real_save(path, data))[1])
    for _ in range(5):
        paths_mod.load_identity()
    assert writes == []
    assert identity_file.read_text(encoding='utf-8') == first


def test_cloud_logout_really_removes_the_sealed_session(
    monkeypatch, identity_file,
):
    _use_secret(monkeypatch, SECRET_A)
    monkeypatch.setattr(dm_mod, 'load_identity', paths_mod.load_identity)
    monkeypatch.setattr(dm_mod, 'save_identity', paths_mod.save_identity)
    paths_mod.save_identity({
        'business_id': 'shop-1',
        'access_token': 'access-token-from-root-a',
        'refresh_token': 'refresh-token-from-root-a',
    })
    assert paths_mod.is_logged_in() is True

    dm_mod.clear_session_tokens()

    on_disk = json.loads(identity_file.read_text(encoding='utf-8'))
    assert on_disk['access_token_protected'] == ''
    assert on_disk['refresh_token_protected'] == ''
    assert paths_mod.is_logged_in() is False
    assert paths_mod.identity_needs_reauth() is False


# ── no retry storm on an unusable session ────────────────────────────────────

def test_refresh_session_fails_closed_without_calling_the_network(
    monkeypatch, identity_file,
):
    identity_file.write_text(json.dumps({
        'business_id': 'shop-1',
        'auth_state': paths_mod.REAUTH_REQUIRED,
        'auth_error': 'protected_token_unreadable',
        'refresh_token_protected': 'gAAAAABmZm9yZWlnbi1yZWZyZXNo',
    }), encoding='utf-8')
    client = _client()
    _no_http(client, monkeypatch)

    with pytest.raises(sc.SupabaseAuthError, match='sign in again'):
        client.refresh_session()


def test_auth_failure_on_unreadable_identity_stops_after_one_attempt(
    monkeypatch, identity_file,
):
    identity_file.write_text(json.dumps({
        'business_id': 'shop-1',
        'auth_state': paths_mod.REAUTH_REQUIRED,
        'auth_error': 'protected_token_unreadable',
    }), encoding='utf-8')
    client = _client()
    _no_http(client, monkeypatch)

    attempts: list = []

    def _work():
        attempts.append(1)
        raise sc.SupabaseError('Unauthorized', status=401)

    # The single refresh attempt fails locally, so the work is never retried
    # and nothing reaches the network.
    with pytest.raises(sc.SupabaseAuthError, match='sign in again'):
        client.with_auth_retry(_work)
    assert len(attempts) == 1


def test_requests_without_a_usable_token_never_leave_the_process(
    monkeypatch, identity_file, tmp_path,
):
    identity_file.write_text(json.dumps({
        'business_id': 'shop-1',
        'auth_state': paths_mod.REAUTH_REQUIRED,
    }), encoding='utf-8')
    client = _client()
    _no_http(client, monkeypatch)
    payload = tmp_path / 'backup.mbtenc'
    payload.write_bytes(b'encrypted')

    with pytest.raises(sc.SupabaseAuthError, match='Not signed in'):
        client.rest_select('backups', 'select=*')
    with pytest.raises(sc.SupabaseAuthError, match='Not signed in'):
        client.upload_file('shop/backup.mbtenc', str(payload))
    with pytest.raises(sc.SupabaseAuthError, match='Not signed in'):
        client.download_file('shop/backup.mbtenc', str(tmp_path / 'out.bin'))


# ── data-root migration must not transplant an unreadable identity ───────────

def test_migration_keeps_identity_when_secrets_match(tmp_path):
    src = tmp_path / 'legacy'
    dst = tmp_path / 'canonical'
    for d in (src, dst):
        d.mkdir()
    (src / mbt_paths.JWT_SECRET_NAME).write_text(SECRET_A, encoding='utf-8')
    (dst / mbt_paths.JWT_SECRET_NAME).write_text(SECRET_A, encoding='utf-8')

    assert mbt_paths._config_migration_exclusions(str(src), str(dst)) == ()


def test_migration_keeps_identity_when_destination_has_no_secret(tmp_path):
    src = tmp_path / 'legacy'
    dst = tmp_path / 'canonical'
    for d in (src, dst):
        d.mkdir()
    (src / mbt_paths.JWT_SECRET_NAME).write_text(SECRET_A, encoding='utf-8')

    # The destination adopts the legacy secret in the same copy, so the
    # sealed identity stays readable.
    assert mbt_paths._config_migration_exclusions(str(src), str(dst)) == ()


def test_migration_skips_identity_sealed_by_a_different_secret(tmp_path):
    src = tmp_path / 'legacy'
    dst = tmp_path / 'canonical'
    for d in (src, dst):
        d.mkdir()
    (src / mbt_paths.JWT_SECRET_NAME).write_text(SECRET_A, encoding='utf-8')
    (dst / mbt_paths.JWT_SECRET_NAME).write_text(SECRET_B, encoding='utf-8')
    (src / mbt_paths.CLOUD_IDENTITY_NAME).write_text('{}', encoding='utf-8')

    excluded = mbt_paths._config_migration_exclusions(str(src), str(dst))
    assert excluded == (mbt_paths.CLOUD_IDENTITY_NAME,)

    mbt_paths._copy_tree_files(str(src), str(dst), excluded=excluded)
    assert not (dst / mbt_paths.CLOUD_IDENTITY_NAME).exists()
    assert (dst / mbt_paths.JWT_SECRET_NAME).read_text(
        encoding='utf-8') == SECRET_B
