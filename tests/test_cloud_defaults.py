"""Shop-like cloud config: fresh install must be configured without a hand-placed file."""
from __future__ import annotations

import json
import os
from pathlib import Path


def test_production_defaults_have_public_endpoints_only():
    from backend.cloud_backup.defaults import production_cloud_defaults

    cfg = production_cloud_defaults()
    assert cfg['supabase_url'].startswith('https://') and 'supabase.co' in cfg['supabase_url']
    assert cfg['anon_key'].startswith('eyJ')
    assert cfg.get('service_key') in ('', None)
    assert cfg.get('enabled') is True
    assert 'uynfglgttkaibyeglsrt' in cfg['supabase_url']


def test_shop_fresh_install_is_cloud_configured(tmp_path, monkeypatch):
    """Empty data root (like a new shop PC) must pass is_cloud_configured()."""
    monkeypatch.setenv('MBT_DATA_ROOT', str(tmp_path))
    monkeypatch.delenv('MBT_SUPABASE_URL', raising=False)
    monkeypatch.delenv('MBT_SUPABASE_ANON_KEY', raising=False)
    monkeypatch.delenv('MBT_SUPABASE_SERVICE_KEY', raising=False)

    from backend.cloud_backup import paths as cloud_paths
    from backend.cloud_backup.defaults import PRODUCTION_ANON_KEY, PRODUCTION_SUPABASE_URL

    assert not (tmp_path / 'config' / 'cloud_config.json').exists()

    assert cloud_paths.is_cloud_configured() is True
    cfg = cloud_paths.load_cloud_config()
    assert cfg['supabase_url'] == PRODUCTION_SUPABASE_URL.rstrip('/')
    assert cfg['anon_key'] == PRODUCTION_ANON_KEY
    assert not cfg.get('service_key')

    seeded = Path(cloud_paths.cloud_config_path())
    assert seeded.is_file()
    disk = json.loads(seeded.read_text(encoding='utf-8'))
    assert disk['supabase_url']
    assert disk['anon_key']
    assert disk.get('service_key', '') == ''


def test_env_overrides_production_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv('MBT_DATA_ROOT', str(tmp_path))
    monkeypatch.setenv('MBT_SUPABASE_URL', 'https://custom.example.supabase.co')
    monkeypatch.setenv('MBT_SUPABASE_ANON_KEY', 'custom-anon-key')

    from backend.cloud_backup import paths as cloud_paths

    cfg = cloud_paths.load_cloud_config()
    assert cfg['supabase_url'] == 'https://custom.example.supabase.co'
    assert cfg['anon_key'] == 'custom-anon-key'
    assert cloud_paths.is_cloud_configured() is True


def test_unconfigured_message_is_shop_friendly():
    from backend.cloud_backup.paths import cloud_unconfigured_message

    msg = cloud_unconfigured_message()
    assert 'portal.mugobyte.com' in msg
    assert 'Cloud is not configured on this PC' not in msg
