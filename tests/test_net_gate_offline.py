"""Offline probes must fail on a raw IP and then skip further probes."""
import backend.cloud.net_gate as ng


def test_offline_probe_is_cached(monkeypatch):
    calls = []

    def fail(*_args, **_kwargs):
        calls.append(1)
        raise OSError('offline')

    monkeypatch.setattr(ng.socket, 'create_connection', fail)
    previous = ng._NEG_UNTIL
    ng._NEG_UNTIL = 0.0
    try:
        assert ng.network_up(0.2) is False
        assert ng.network_up(0.2) is False
        assert len(calls) == 2
    finally:
        ng._NEG_UNTIL = previous
