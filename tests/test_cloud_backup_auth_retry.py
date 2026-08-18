from unittest.mock import Mock

import pytest

from backend.cloud_backup.supabase_client import SupabaseClient, SupabaseError


def _client() -> SupabaseClient:
    return SupabaseClient(config={
        'supabase_url': 'https://example.invalid',
        'anon_key': 'test-anon-key',
    })


def test_backup_client_refreshes_once_for_an_expired_session():
    client = _client()
    client.refresh_session = Mock()
    operation = Mock(side_effect=[SupabaseError('expired', 401), 'ok'])

    assert client.with_auth_retry(operation) == 'ok'
    assert operation.call_count == 2
    client.refresh_session.assert_called_once()


def test_backup_client_does_not_retry_a_cross_shop_forbidden_response():
    client = _client()
    client.refresh_session = Mock()
    operation = Mock(side_effect=SupabaseError('forbidden', 403))

    with pytest.raises(SupabaseError) as failure:
        client.with_auth_retry(operation)

    assert failure.value.status == 403
    assert operation.call_count == 1
    client.refresh_session.assert_not_called()
