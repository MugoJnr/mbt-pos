"""Cloud backup queue and tenant-policy regression gates."""
from __future__ import annotations

import json
from pathlib import Path

from backend.cloud_backup import sync_manager as sm_mod


def test_metadata_failure_keeps_uploaded_backup_retryable(tmp_path, monkeypatch):
    queue_path = tmp_path / 'queue.json'
    state_path = tmp_path / 'state.json'
    encrypted = tmp_path / 'pending_20260902_190000.mbtenc'
    encrypted.write_bytes(b'encrypted-backup')
    item = {
        'type': 'backup_meta',
        'local_enc_path': str(encrypted),
        'storage_path': 'business/device/latest.mbtenc',
        'meta': {'business_id': 'business'},
    }
    queue_path.write_text(json.dumps({'items': [item]}), encoding='utf-8')

    monkeypatch.setattr(sm_mod, 'offline_queue_path', lambda: str(queue_path))
    monkeypatch.setattr(sm_mod, 'backup_state_path', lambda: str(state_path))
    monkeypatch.setattr(sm_mod, 'is_logged_in', lambda: True)
    monkeypatch.setattr(sm_mod, 'is_cloud_configured', lambda: True)
    from backend.cloud import auth_gate
    monkeypatch.setattr(auth_gate, 'is_terminal_auth_dead', lambda: False)
    monkeypatch.setattr(auth_gate, 'cloud_sync_should_run', lambda: True)
    from backend.cloud import circuit_breaker
    class _AlwaysOpenForTest:
        def allow(self): return True
        def record_failure(self): pass
        def record_success(self): pass
    monkeypatch.setattr(circuit_breaker, 'get_breaker', lambda _name: _AlwaysOpenForTest())
    monkeypatch.setattr(
        sm_mod, 'load_identity', lambda: {'business_id': 'business'}
    )

    calls = {'uploads': 0, 'metadata': 0}

    class MetadataFails:
        def upload_file(self, *_args, **_kwargs):
            calls['uploads'] += 1

        def upsert_backup_meta(self, _meta):
            calls['metadata'] += 1
            raise RuntimeError('new row violates row-level security policy')

    monkeypatch.setattr(sm_mod, 'SupabaseClient', MetadataFails)
    manager = sm_mod.SyncManager()
    assert manager.flush_offline_queue() == 0
    queued = json.loads(queue_path.read_text(encoding='utf-8'))['items']
    assert queued[0]['uploaded'] is True
    assert 'not authorized' in queued[0]['last_error']
    assert encrypted.exists()

    class MetadataSucceeds:
        def upload_file(self, *_args, **_kwargs):
            calls['uploads'] += 1

        def upsert_backup_meta(self, _meta):
            calls['metadata'] += 1
            return {'id': 'backup-id'}

    monkeypatch.setattr(sm_mod, 'SupabaseClient', MetadataSucceeds)
    assert manager.flush_offline_queue() == 1
    assert calls == {'uploads': 1, 'metadata': 2}
    assert json.loads(queue_path.read_text(encoding='utf-8'))['items'] == []
    assert not encrypted.exists()


def test_queue_rejects_cross_shop_identity(tmp_path, monkeypatch):
    queue_path = tmp_path / 'queue.json'
    state_path = tmp_path / 'state.json'
    encrypted = tmp_path / 'pending.mbtenc'
    encrypted.write_bytes(b'encrypted-backup')
    queue_path.write_text(json.dumps({'items': [{
        'type': 'backup_meta',
        'local_enc_path': str(encrypted),
        'storage_path': 'old-business/device/latest.mbtenc',
        'meta': {'business_id': 'old-business'},
    }]}), encoding='utf-8')

    monkeypatch.setattr(sm_mod, 'offline_queue_path', lambda: str(queue_path))
    monkeypatch.setattr(sm_mod, 'backup_state_path', lambda: str(state_path))
    monkeypatch.setattr(sm_mod, 'is_logged_in', lambda: True)
    monkeypatch.setattr(sm_mod, 'is_cloud_configured', lambda: True)
    from backend.cloud import auth_gate, circuit_breaker
    monkeypatch.setattr(auth_gate, 'is_terminal_auth_dead', lambda: False)
    monkeypatch.setattr(auth_gate, 'cloud_sync_should_run', lambda: True)
    class _AlwaysOpenForTest:
        def allow(self): return True
        def record_failure(self): pass
        def record_success(self): pass
    monkeypatch.setattr(circuit_breaker, 'get_breaker', lambda _name: _AlwaysOpenForTest())
    monkeypatch.setattr(
        sm_mod, 'load_identity', lambda: {'business_id': 'new-business'}
    )

    assert sm_mod.SyncManager().flush_offline_queue() == 0
    queued = json.loads(queue_path.read_text(encoding='utf-8'))['items']
    assert 'another shop account' in queued[0]['last_error']
    assert encrypted.exists()


def test_shop_backup_migration_covers_table_and_storage_rls():
    migration = (
        Path(__file__).parents[1]
        / 'supabase' / 'migrations' / '20260902190000_shop_backup_rls.sql'
    ).read_text(encoding='utf-8')
    assert 'can_access_business' in migration
    assert 'public.is_org_member' in migration
    assert 'backups_shop_insert' in migration
    assert 'storage.objects for insert to authenticated' in migration
