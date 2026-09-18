"""v3.0.99 — Cloud Backup Settings panel enable/tooltip when signed out."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip('PyQt5.QtWidgets')


@pytest.fixture(scope='module')
def qapp():
    from PyQt5.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv[:1])
    return app


def test_backup_now_disabled_with_signin_tooltip_when_logged_out(qapp, tmp_path, monkeypatch):
    from backend.cloud_backup import paths as paths_mod
    from desktop.tabs.cloud_backup_panel import CloudBackupPanel

    identity_path = tmp_path / 'cloud_identity.json'
    config_path = tmp_path / 'cloud_config.json'
    identity_path.write_text(json.dumps({
        'auth_state': 'reauth_required',
        'business_id': '',
        'access_token': '',
        'refresh_token': '',
    }), encoding='utf-8')
    config_path.write_text(json.dumps({
        'enabled': False,
        'supabase_url': 'https://mxfvbylmlynotvghnzqg.supabase.co',
        'anon_key': 'anon',
    }), encoding='utf-8')
    monkeypatch.setattr(paths_mod, 'cloud_identity_path', lambda: str(identity_path))
    monkeypatch.setattr(paths_mod, 'cloud_config_path', lambda: str(config_path))

    st = {
        'logged_in': False,
        'reauth_required': True,
        'configured': True,
        'enabled': False,
        'email': '',
        'business_name': '',
        'device_id': 'dev',
        'interval_minutes': 1440,
        'backup_keep_count': 7,
        'last_error': '',
        'queue_depth': 0,
        'pending_file_count': 0,
        'last_backup_size': 0,
        'last_backup_at': '',
    }
    with patch('backend.cloud_backup.sync_manager.SyncManager.instance') as inst:
        mgr = MagicMock()
        mgr.status.return_value = st
        inst.return_value = mgr
        panel = CloudBackupPanel()
        panel.refresh()
        assert panel.btn_backup.isEnabled() is False
        assert 'Sign in' in (panel.btn_backup.toolTip() or '')
        assert panel.btn_login.isEnabled() is True
        assert panel.btn_create.isEnabled() is True
        panel.close()
