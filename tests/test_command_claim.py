"""Remote command claim gate. No network and no shop database."""
import json
import os

import backend.cloud.command_center as commands
from backend.cloud.command_center import (
    CommandCenter,
    claim_pending_command,
    dispatch_remote_command,
    load_command_receipts,
    remember_command,
    updated_row_has_id,
)


def test_empty_update_is_not_a_claim():
    assert updated_row_has_id(None, 'cmd-1') is False
    assert updated_row_has_id([], 'cmd-1') is False
    assert updated_row_has_id([{'id': 'other'}], 'cmd-1') is False


def test_returned_row_is_a_claim():
    assert updated_row_has_id([{'id': 'cmd-1', 'status': 'running'}], 'cmd-1') is True
    assert updated_row_has_id({'id': 'cmd-1'}, 'cmd-1') is True


def test_receipt_is_durable_before_a_second_run(tmp_path):
    path = os.path.join(tmp_path, 'command_receipts.json')
    remember_command('revoke-1', path)
    assert 'revoke-1' in load_command_receipts(path)
    remember_command('revoke-1', path)
    with open(path, encoding='utf-8') as fh:
        assert json.load(fh).count('revoke-1') == 1


def _center(tmp_path, calls):
    center = CommandCenter(str(tmp_path / 'unused.db'))
    center.register_handler(
        'revoke_license',
        lambda params: calls.append('revoke') or (True, 'revoked', None),
    )
    center.report_result = lambda *args, **kwargs: calls.append('report')
    return center


def test_zero_row_claim_does_not_revoke(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(commands, 'claim_pending_command', lambda cmd_id: False)
    result = dispatch_remote_command(
        _center(tmp_path, calls),
        {'id': 'stale-revoke', 'command': 'revoke_license', 'params': {}},
        os.path.join(tmp_path, 'receipts.json'),
    )
    assert result == 'unclaimed'
    assert calls == []


def test_claimed_revoke_runs_once(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(commands, 'claim_pending_command', lambda cmd_id: True)
    path = os.path.join(tmp_path, 'receipts.json')
    center = _center(tmp_path, calls)
    cmd = {'id': 'real-revoke', 'command': 'revoke_license', 'params': {'reason': 'test'}}
    assert dispatch_remote_command(center, cmd, path) == 'executed'
    assert calls.count('revoke') == 1
    assert dispatch_remote_command(center, cmd, path) == 'skipped'
    assert calls.count('revoke') == 1


def test_failed_receipt_blocks_revoke(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(commands, 'claim_pending_command', lambda cmd_id: True)

    def boom(cmd_id, path=None):
        raise OSError('disk full')

    monkeypatch.setattr(commands, 'remember_command', boom)
    result = dispatch_remote_command(
        _center(tmp_path, calls),
        {'id': 'revoke-2', 'command': 'revoke_license'},
        os.path.join(tmp_path, 'receipts.json'),
    )
    assert result == 'receipt_failed'
    assert calls == []


def test_empty_cloud_body_is_not_a_claim(monkeypatch):
    monkeypatch.setattr(
        'backend.cloud.platform_service.service_update',
        lambda table, query, patch: [],
    )
    assert claim_pending_command('cmd-empty') is False
