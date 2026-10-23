"""License reads must not spawn wmic when the cached device id already matches."""
import subprocess

import licensing.license_engine as le


def test_cached_license_does_not_run_wmic(monkeypatch):
    monkeypatch.setattr(le, '_read_raw_license_token', lambda: 'blob')
    monkeypatch.setattr(le, '_read_cached_device_id', lambda: 'a' * 40)
    monkeypatch.setattr(le, '_get_device_fingerprint', lambda: 'b' * 40)
    monkeypatch.setattr(le, '_cloud_identity_device_ids', lambda: [])
    calls = []

    def boom():
        calls.append('wmic')
        return 'c' * 40

    monkeypatch.setattr(le, '_get_legacy_wmic_fingerprint', boom)
    monkeypatch.setattr(
        le, '_license_blob_matches',
        lambda raw, did: 'inner' if did == 'a' * 40 else None,
    )
    inner, did = le._resolve_inner_license_token()
    assert inner == 'inner'
    assert did == 'a' * 40
    assert calls == []


def test_wmic_probe_is_hidden_and_cached(monkeypatch):
    seen = []

    def fake_check_output(*args, **kwargs):
        seen.append(kwargs)
        return b''

    monkeypatch.setattr(subprocess, 'check_output', fake_check_output)
    monkeypatch.setattr(le.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(le.platform, 'node', lambda: 'pc')
    monkeypatch.setattr(le.platform, 'processor', lambda: 'cpu')
    monkeypatch.setattr(le.platform, 'version', lambda: '10')
    previous = le._HW_PROBE_PARTS
    le._HW_PROBE_PARTS = None
    try:
        first = le._collect_hardware_probe_parts()
        second = le._collect_hardware_probe_parts()
    finally:
        le._HW_PROBE_PARTS = previous
    assert first == second
    assert len(seen) == 3
    assert all(call.get('creationflags') == 0x08000000 for call in seen)
