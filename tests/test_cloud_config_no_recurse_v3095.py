"""v3.0.95 — load_cloud_config must not recurse via stale-state sanitize.

Regression for the proven GIL-starvation hang:
load_cloud_config → ensure_production → sanitize → active_supabase_host → load_cloud_config
This loop is local-only (no network) and therefore hangs offline and online.
"""
from __future__ import annotations

import json
import sys
from unittest.mock import patch


def test_active_supabase_host_does_not_call_load_cloud_config(tmp_path, monkeypatch):
    from backend.cloud_backup import migrate_stale_state as m
    from backend.cloud_backup import paths as p

    cfg_path = tmp_path / 'cloud_config.json'
    cfg_path.write_text(json.dumps({
        'supabase_url': 'https://mxfvbylmlynotvghnzqg.supabase.co',
        'project_ref': 'mxfvbylmlynotvghnzqg',
        'anon_key': 'x',
    }), encoding='utf-8')
    monkeypatch.setattr(m, 'cloud_config_path', lambda: str(cfg_path))

    def _boom(*_a, **_k):
        raise AssertionError('load_cloud_config must not be called from active_supabase_host')

    monkeypatch.setattr(p, 'load_cloud_config', _boom)
    host = m.active_supabase_host()
    assert host == 'mxfvbylmlynotvghnzqg.supabase.co'


def test_load_cloud_config_no_infinite_recursion(tmp_path, monkeypatch):
    """Force the old recursion path to fail fast if it returns."""
    from backend.cloud_backup import paths as p

    root = tmp_path / 'data'
    cfg_dir = root / 'config'
    cfg_dir.mkdir(parents=True)
    (cfg_dir / 'cloud_config.json').write_text(json.dumps({
        'enabled': True,
        'supabase_url': 'https://mxfvbylmlynotvghnzqg.supabase.co',
        'project_ref': 'mxfvbylmlynotvghnzqg',
        'anon_key': 'test-anon',
        'backup_interval_minutes': 1440,
        'backup_keep_count': 7,
        'bucket': 'mbt-backups',
        'service_key': '',
    }), encoding='utf-8')
    (cfg_dir / 'cloud_offline_queue.json').write_text(
        json.dumps({'items': []}), encoding='utf-8'
    )
    (cfg_dir / 'cloud_backup_state.json').write_text('{}', encoding='utf-8')

    monkeypatch.setattr(p, 'config_dir', lambda: str(cfg_dir))
    monkeypatch.setattr('mbt_paths.ensure_data_dirs', lambda *_a, **_k: str(root))
    p.reset_sanitize_guard_for_tests()

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(200)
    try:
        cfg = p.load_cloud_config()
        cfg2 = p.load_cloud_config()
    finally:
        sys.setrecursionlimit(old_limit)

    assert 'mxfvbylmlynotvghnzqg' in (cfg.get('supabase_url') or '')
    assert cfg2.get('anon_key') == 'test-anon'


def test_ensure_sanitize_once_and_offline_safe(tmp_path, monkeypatch):
    """Sanitize from ensure must complete without network and without reentry."""
    from backend.cloud_backup import paths as p
    from backend.cloud_backup import migrate_stale_state as m

    cfg_dir = tmp_path / 'config'
    cfg_dir.mkdir()
    (cfg_dir / 'cloud_config.json').write_text(json.dumps({
        'supabase_url': 'https://mxfvbylmlynotvghnzqg.supabase.co',
        'project_ref': 'mxfvbylmlynotvghnzqg',
        'anon_key': 'x',
        'enabled': True,
        'backup_interval_minutes': 1440,
        'backup_keep_count': 7,
        'bucket': 'mbt-backups',
        'service_key': '',
    }), encoding='utf-8')
    (cfg_dir / 'cloud_offline_queue.json').write_text(
        json.dumps({'items': []}), encoding='utf-8'
    )
    (cfg_dir / 'cloud_backup_state.json').write_text('{}', encoding='utf-8')

    monkeypatch.setattr(p, 'config_dir', lambda: str(cfg_dir))
    monkeypatch.setattr(m, 'cloud_config_path', lambda: str(cfg_dir / 'cloud_config.json'))
    monkeypatch.setattr(m, 'offline_queue_path', lambda: str(cfg_dir / 'cloud_offline_queue.json'))
    monkeypatch.setattr(m, 'backup_state_path', lambda: str(cfg_dir / 'cloud_backup_state.json'))
    p.reset_sanitize_guard_for_tests()

    # Prove no network: any socket attempt fails the test.
    with patch('socket.socket') as sock:
        sock.side_effect = AssertionError('network forbidden in offline hang regression')
        cfg = p.ensure_production_cloud_config(persist=False)
        p.ensure_production_cloud_config(persist=False)
        cfg2 = p.load_cloud_config()
    assert cfg.get('supabase_url')
    assert cfg2.get('anon_key') == 'x'
