"""Tunnel identity resolution and cloudflared transport fallback.

Shop PCs accumulate conflicting tunnel artifacts (a connector token plus an
older credentials-file config.yml), and many shop networks drop QUIC/UDP or
IPv6. Both must be handled the same way on every install, so nothing here
touches the network or this machine's real Cloudflare state.
"""
from __future__ import annotations

import base64
import json

import pytest

from backend import cloudflare_setup as cf

TOKEN_TUNNEL = '11111111-2222-3333-4444-555555555555'
OTHER_TUNNEL = '99999999-8888-7777-6666-555555555555'


def _connector_token(tunnel_id: str, account: str = 'acct') -> str:
    payload = json.dumps({'a': account, 't': tunnel_id, 's': 'c2VjcmV0'})
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip('=')


@pytest.fixture
def cf_env(monkeypatch, tmp_path):
    """Isolate every path and config read the module performs."""
    app_dir = tmp_path / 'cloudflared'
    home_dir = tmp_path / 'home_cloudflared'
    backup_dir = tmp_path / 'config' / 'cloudflared_backup'
    for d in (app_dir, home_dir, backup_dir):
        d.mkdir(parents=True, exist_ok=True)

    state = {'cfg': {}, 'token': ''}

    monkeypatch.setattr(cf, 'get_cloudflared_dir', lambda: app_dir)
    monkeypatch.setattr(cf, 'get_legacy_cloudflared_dir', lambda: home_dir)
    monkeypatch.setattr(cf, '_project_root', lambda: tmp_path)
    monkeypatch.setattr(cf, 'load_web_config', lambda: dict(state['cfg']))
    monkeypatch.setattr(
        cf, 'save_web_config',
        lambda updates: state['cfg'].update(updates) or tmp_path)
    monkeypatch.setattr(cf, '_get_tunnel_run_token', lambda: state['token'])
    return state, app_dir, home_dir


def _write_config_yml(directory, tunnel_id: str, hostname: str) -> None:
    (directory / 'config.yml').write_text(
        f'tunnel: {tunnel_id}\n'
        f'credentials-file: {directory / (tunnel_id + ".json")}\n'
        'ingress:\n'
        f'  - hostname: {hostname}\n'
        '    service: http://127.0.0.1:5050\n'
        '  - service: http_status:404\n',
        encoding='utf-8',
    )


# ── Token decoding ───────────────────────────────────────────────────────────

def test_connector_token_reveals_its_tunnel_id():
    assert cf._tunnel_id_from_run_token(
        _connector_token(TOKEN_TUNNEL)) == TOKEN_TUNNEL


def test_legacy_cfut_prefix_decodes_the_same_payload():
    assert cf._tunnel_id_from_run_token(
        'cfut_' + _connector_token(TOKEN_TUNNEL)) == TOKEN_TUNNEL


@pytest.mark.parametrize('value', [
    '',
    '   ',
    'not-base64-at-all',
    base64.urlsafe_b64encode(b'{"a":"acct"}').decode(),      # no tunnel claim
    base64.urlsafe_b64encode(b'{"t":"not-a-uuid"}').decode(),
])
def test_undecodable_tokens_yield_no_tunnel_id(value):
    assert cf._tunnel_id_from_run_token(value) == ''


# ── Authority resolution ─────────────────────────────────────────────────────

def test_connector_token_supersedes_a_config_naming_another_tunnel(cf_env):
    state, app_dir, home_dir = cf_env
    state['token'] = _connector_token(TOKEN_TUNNEL)
    state['cfg'] = {'tunnel_id': OTHER_TUNNEL}
    _write_config_yml(app_dir, OTHER_TUNNEL, 'old-shop.example.com')

    result = cf.resolve_tunnel_authority()

    assert result['mode'] == 'token'
    assert result['tunnel_id'] == TOKEN_TUNNEL
    assert result['repaired'] is True
    assert not (app_dir / 'config.yml').exists()
    assert list(app_dir.glob('config.superseded-*.yml'))
    assert state['cfg']['tunnel_id'] == TOKEN_TUNNEL


def test_matching_token_and_config_are_left_alone(cf_env):
    state, app_dir, _ = cf_env
    state['token'] = _connector_token(TOKEN_TUNNEL)
    state['cfg'] = {'tunnel_id': TOKEN_TUNNEL}
    _write_config_yml(app_dir, TOKEN_TUNNEL, 'shop.example.com')

    result = cf.resolve_tunnel_authority()

    assert result == {
        'mode': 'token',
        'tunnel_id': TOKEN_TUNNEL,
        'repaired': False,
        'token_tunnel_id': TOKEN_TUNNEL,
        'config_tunnel_id': TOKEN_TUNNEL,
    }
    assert (app_dir / 'config.yml').is_file()


def test_without_a_token_the_config_file_owns_the_identity(cf_env):
    state, app_dir, _ = cf_env
    state['cfg'] = {'tunnel_id': OTHER_TUNNEL}
    _write_config_yml(app_dir, TOKEN_TUNNEL, 'shop.example.com')

    result = cf.resolve_tunnel_authority()

    assert result['mode'] == 'config'
    assert result['tunnel_id'] == TOKEN_TUNNEL
    assert result['repaired'] is True
    assert state['cfg']['tunnel_id'] == TOKEN_TUNNEL
    assert (app_dir / 'config.yml').is_file()


def test_unconfigured_pc_reports_no_tunnel(cf_env):
    assert cf.resolve_tunnel_authority()['mode'] == 'none'


# ── Transport ladder ─────────────────────────────────────────────────────────

def test_ladder_degrades_from_quic_to_ipv4_http2():
    assert cf._TRANSPORT_LADDER == ('auto', 'http2', 'http2-ipv4')
    assert cf._transport_flags('auto') == []
    assert cf._transport_flags('http2') == ['--protocol', 'http2']
    assert cf._transport_flags('http2-ipv4') == [
        '--protocol', 'http2', '--edge-ip-version', '4']


def test_transport_flags_precede_the_run_subcommand():
    args = ['cloudflared.exe', 'tunnel', 'run', '--token', 'T']
    assert cf._with_transport_flags(args, 'http2-ipv4') == [
        'cloudflared.exe', 'tunnel',
        '--protocol', 'http2', '--edge-ip-version', '4',
        'run', '--token', 'T',
    ]


def test_transport_flags_also_apply_to_credentials_file_launches():
    args = ['cloudflared.exe', 'tunnel', '--config', 'c.yml', 'run']
    assert cf._with_transport_flags(args, 'http2') == [
        'cloudflared.exe', 'tunnel', '--protocol', 'http2',
        '--config', 'c.yml', 'run',
    ]


def test_auto_transport_adds_nothing():
    args = ['cloudflared.exe', 'tunnel', 'run', '--token', 'T']
    assert cf._with_transport_flags(args, 'auto') == args


def test_remembered_transport_must_be_a_known_rung(cf_env):
    state, _, _ = cf_env
    state['cfg'] = {'cloudflared_transport': 'http2'}
    assert cf._preferred_transport() == 'http2'
    state['cfg'] = {'cloudflared_transport': 'telepathy'}
    assert cf._preferred_transport() == 'auto'
    state['cfg'] = {}
    assert cf._preferred_transport() == 'auto'


def test_registration_is_read_from_the_connector_log(tmp_path):
    log = tmp_path / 'cloudflared.log'
    log.write_text('old session noise\n', encoding='utf-8')
    offset = log.stat().st_size
    assert cf.CloudflareTunnelService._registered_since(log, offset) is False
    with open(log, 'a', encoding='utf-8') as fh:
        fh.write('INF Registered tunnel connection connIndex=0 protocol=http2\n')
    assert cf.CloudflareTunnelService._registered_since(log, offset) is True


def test_earlier_registrations_do_not_count_as_this_launch(tmp_path):
    log = tmp_path / 'cloudflared.log'
    log.write_text(
        'INF Registered tunnel connection connIndex=0 protocol=quic\n',
        encoding='utf-8')
    assert cf.CloudflareTunnelService._registered_since(
        log, log.stat().st_size) is False
