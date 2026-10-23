"""A timed-out cloud call must not wedge the next call."""
from __future__ import annotations

import time

import requests

from backend.cloud.reliability_log import _scrub, note, recent_lines
from backend.cloud_backup.supabase_client import SupabaseClient


class _Resp:
    status_code = 200
    content = b''
    text = ''

    def json(self):
        return []


def test_scrub_drops_tokens():
    text = _scrub('Authorization Bearer eyJabc.def password=secret ok')
    assert 'eyJabc' not in text
    assert 'secret' not in text
    assert 'ok' in text


def test_timeout_releases_the_next_session(monkeypatch, tmp_path):
    monkeypatch.setenv('MBT_DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(
        'backend.cloud.net_gate.network_up', lambda *args, **kwargs: True,
    )
    monkeypatch.setattr('backend.cloud.net_gate.bounded_timeout', lambda *args, **kwargs: 2.0)

    calls = {'n': 0}

    def fake_request(self, method, url, **kwargs):
        calls['n'] += 1
        if calls['n'] == 1:
            time.sleep(4)
        return _Resp()

    monkeypatch.setattr(requests.Session, 'request', fake_request)
    client = SupabaseClient({
        'supabase_url': 'https://example.supabase.co',
        'anon_key': 'public-anon',
        'service_key': '',
        'bucket': 'mbt-backups',
    })
    first = client._session
    started = time.perf_counter()
    try:
        first.get('https://example.supabase.co/rest/v1/remote_commands', timeout=2)
        raised = False
    except requests.ConnectionError:
        raised = True
    elapsed = time.perf_counter() - started
    assert raised
    assert elapsed < 3.5
    assert first._abandoned is True
    second = client._session
    assert second is not first
    started = time.perf_counter()
    second.get('https://example.supabase.co/rest/v1/remote_commands', timeout=2)
    assert time.perf_counter() - started < 1.0
    note('net', 'supabase', 12, 'ok', 'eyJshould-not-stick')
    blob = '\n'.join(recent_lines(10))
    assert 'eyJshould-not-stick' not in blob
