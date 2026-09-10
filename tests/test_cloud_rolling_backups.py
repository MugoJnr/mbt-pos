"""Rolling cloud backup release gates for desktop builds."""
from __future__ import annotations

import json
from pathlib import Path


def test_retired_project_and_five_minute_schedule_migrate(tmp_path, monkeypatch):
    monkeypatch.setenv('MBT_DATA_ROOT', str(tmp_path))
    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    path = config_dir / 'cloud_config.json'
    path.write_text(json.dumps({
        'supabase_url': 'https://uynfglgttkaibyeglsrt.supabase.co',
        'anon_key': 'old-anon',
        'project_ref': 'uynfglgttkaibyeglsrt',
        'project_name': 'mbt-pos',
        'enabled': True,
        'backup_interval_minutes': 5,
        'bucket': 'mbt-backups',
    }), encoding='utf-8')

    from backend.cloud_backup import paths
    from backend.cloud_backup.defaults import (
        PRODUCTION_ANON_KEY,
        PRODUCTION_PROJECT_REF,
        PRODUCTION_SUPABASE_URL,
    )

    cfg = paths.ensure_production_cloud_config()
    assert cfg['supabase_url'] == PRODUCTION_SUPABASE_URL
    assert cfg['anon_key'] == PRODUCTION_ANON_KEY
    assert cfg['project_ref'] == PRODUCTION_PROJECT_REF
    assert cfg['backup_interval_minutes'] == 1440
    assert cfg['backup_keep_count'] == 7

    persisted = json.loads(path.read_text(encoding='utf-8'))
    assert persisted == cfg
    assert 'uynfglgttkaibyeglsrt' not in persisted['supabase_url']


def test_subhour_schedule_is_forced_slow_on_current_project(tmp_path, monkeypatch):
    monkeypatch.setenv('MBT_DATA_ROOT', str(tmp_path))
    from backend.cloud_backup import paths
    from backend.cloud_backup.defaults import production_cloud_defaults

    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    current = production_cloud_defaults()
    current['backup_interval_minutes'] = 15
    (config_dir / 'cloud_config.json').write_text(
        json.dumps(current), encoding='utf-8'
    )

    cfg = paths.load_cloud_config()
    assert cfg['backup_interval_minutes'] == 1440
    assert cfg['backup_keep_count'] == 7


def test_sync_status_enforces_one_hour_floor(tmp_path, monkeypatch):
    from backend.cloud_backup import sync_manager as sm

    monkeypatch.setattr(sm, 'backup_state_path', lambda: str(tmp_path / 'state'))
    monkeypatch.setattr(sm, 'offline_queue_path', lambda: str(tmp_path / 'queue'))
    monkeypatch.setattr(sm, 'load_cloud_config', lambda: {
        'enabled': True,
        'backup_interval_minutes': 5,
        'backup_keep_count': 7,
    })
    monkeypatch.setattr(sm, 'load_identity', lambda: {})
    monkeypatch.setattr(sm, 'is_cloud_configured', lambda: True)
    monkeypatch.setattr(sm, 'is_logged_in', lambda: False)
    monkeypatch.setattr(sm, 'get_or_create_device_id', lambda: 'device-1')

    status = sm.SyncManager().status()
    assert status['interval_minutes'] == 60
    assert status['backup_keep_count'] == 7
    assert status['backup_style'] == 'rolling'


def test_legacy_timestamp_queue_is_retired_without_upload_or_payload_loss(
    tmp_path, monkeypatch,
):
    from backend.cloud_backup import sync_manager as sm

    queue_path = tmp_path / 'queue.json'
    state_path = tmp_path / 'state.json'
    legacy_payload = tmp_path / 'pending_legacy.mbtenc'
    legacy_payload.write_bytes(b'preserve-until-new-backup')
    queue_path.write_text(json.dumps({'items': [{
        'type': 'backup_meta',
        'local_enc_path': str(legacy_payload),
        'storage_path': 'business/device/20260902_193652.mbtenc',
        'meta': {'business_id': 'business'},
    }, {
        'type': 'backup_meta',
        'local_enc_path': str(tmp_path / 'pending_latest.mbtenc'),
        'storage_path': 'business/device/latest.mbtenc',
        'meta': {'business_id': 'business'},
    }]}), encoding='utf-8')
    monkeypatch.setattr(sm, 'offline_queue_path', lambda: str(queue_path))
    monkeypatch.setattr(sm, 'backup_state_path', lambda: str(state_path))
    monkeypatch.setattr(sm, 'is_logged_in', lambda: False)

    assert sm.SyncManager().flush_offline_queue() == 0
    remaining = json.loads(queue_path.read_text(encoding='utf-8'))['items']
    assert [item['storage_path'] for item in remaining] == [
        'business/device/latest.mbtenc'
    ]
    assert legacy_payload.exists()
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['legacy_queue_refs_retired'] == 1


def test_backup_uses_latest_and_daily_slots_only(tmp_path, monkeypatch):
    from backend.cloud_backup import sync_manager as sm

    zip_path = tmp_path / 'snapshot.zip'
    zip_path.write_bytes(b'snapshot')
    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    queue_path = config_dir / 'queue.json'
    state_path = config_dir / 'state.json'
    uploads = []
    metadata = []

    monkeypatch.setattr(
        sm, 'create_sqlite_snapshot', lambda: (str(zip_path), None)
    )

    def fake_encrypt(_src, dest, _key):
        Path(dest).write_bytes(b'encrypted')
        return len(b'encrypted')

    monkeypatch.setattr(sm, 'encrypt_file', fake_encrypt)
    monkeypatch.setattr(sm, 'sha256_file', lambda _path: 'content-hash')
    monkeypatch.setattr(
        sm, 'ensure_identity_key_material',
        lambda ident, password='': (b'key', ident),
    )
    monkeypatch.setattr(sm, 'is_cloud_configured', lambda: True)
    monkeypatch.setattr(sm, 'is_logged_in', lambda: True)
    monkeypatch.setattr(sm, 'load_identity', lambda: {
        'business_id': 'business-1',
        'user_id': '',
        'email': 'owner@example.com',
    })
    monkeypatch.setattr(sm, 'save_identity', lambda _ident: None)
    monkeypatch.setattr(sm, 'get_device_info', lambda: {
        'device_id': 'device-1',
        'hostname': 'SHOP-PC',
        'platform': 'Windows',
    })
    monkeypatch.setattr(sm, 'backup_state_path', lambda: str(state_path))
    monkeypatch.setattr(sm, 'offline_queue_path', lambda: str(queue_path))
    monkeypatch.setattr(sm, 'load_cloud_config', lambda: {
        'backup_keep_count': 7,
    })

    class Client:
        def upload_file(self, object_path, *_args, **_kwargs):
            uploads.append(object_path)
            return object_path

        def upsert_backup_meta(self, meta):
            metadata.append(dict(meta))
            return {'id': f'meta-{len(metadata)}'}

        def log_sync(self, _entry):
            return None

        def register_device(self, *_args, **_kwargs):
            return {}

        def rest_select(self, *_args, **_kwargs):
            return []

        def delete_files(self, _paths):
            raise AssertionError('nothing should be pruned')

        def rest_delete(self, *_args):
            raise AssertionError('nothing should be pruned')

    monkeypatch.setattr(sm, 'SupabaseClient', Client)

    result = sm.SyncManager().run_backup(reason='manual')
    assert result['ok'] is True
    assert uploads[0] == 'business-1/device-1/latest.mbtenc'
    assert uploads[1].startswith('business-1/device-1/daily/')
    assert uploads[1].endswith('.mbtenc')
    assert len(uploads) == 2
    assert all('/20' not in path.split('/device-1/', 1)[-1]
               for path in uploads[:1])
    assert {m['storage_path'] for m in metadata} == set(uploads)
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['last_storage_path'].endswith('/latest.mbtenc')
    assert state['backup_style'] == 'rolling'
    assert json.loads(queue_path.read_text(encoding='utf-8'))['items'] == []


def test_prune_removes_legacy_and_keeps_seven_daily(monkeypatch):
    from backend.cloud_backup import sync_manager as sm

    monkeypatch.setattr(
        sm, 'load_cloud_config', lambda: {'backup_keep_count': 7}
    )
    rows = [{
        'id': 'latest',
        'storage_path': 'business/device/latest.mbtenc',
        'created_at': '2026-09-10T00:00:00Z',
    }, {
        'id': 'legacy',
        'storage_path': 'business/device/20260909_120000.mbtenc',
        'created_at': '2026-09-09T12:00:00Z',
    }]
    for index in range(9):
        rows.append({
            'id': f'daily-{index}',
            'storage_path': f'business/device/daily/202609{10-index:02d}.mbtenc',
            'created_at': f'2026-09-{10-index:02d}T00:00:00Z',
        })

    class Client:
        deleted_files = []
        deleted_rows = []

        def rest_select(self, *_args, **_kwargs):
            return rows

        def delete_files(self, paths):
            self.deleted_files.extend(paths)
            return len(paths)

        def rest_delete(self, _table, query):
            self.deleted_rows.append(query)

    client = Client()
    removed = sm.SyncManager()._prune_old_backups(
        client, 'business', 'device'
    )
    assert removed == 3
    assert 'business/device/20260909_120000.mbtenc' in client.deleted_files
    assert len([p for p in client.deleted_files if '/daily/' in p]) == 2
    assert len(client.deleted_rows) == 3


def test_cloud_backup_panel_uses_hours_and_rolling_copy():
    source = (
        Path(__file__).parents[1]
        / 'desktop' / 'tabs' / 'cloud_backup_panel.py'
    ).read_text(encoding='utf-8')
    assert "self.interval.setSuffix(' hours')" in source
    assert "cfg['backup_interval_minutes'] = hours * 60" in source
    assert 'rolling backup' in source.lower()
