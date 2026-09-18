"""v3.0.99 — org UUID guard + device register conflict fallback."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.cloud.platform_service import (
    is_uuid,
    require_uuid_org_id,
    register_or_refresh_device,
)
from backend.cloud_backup.supabase_client import SupabaseError


def test_is_uuid_rejects_org_test_and_garbage():
    assert is_uuid('org-test') is False
    assert is_uuid('') is False
    assert is_uuid('not-a-uuid') is False
    assert is_uuid('bdd381de-dbde-43f6-973a-470ff524d91c') is True


def test_require_uuid_org_id_raises_on_placeholder():
    with pytest.raises(SupabaseError) as ei:
        require_uuid_org_id('org-test')
    assert 'org-test' in str(ei.value)
    assert ei.value.status == 400


def test_register_or_refresh_device_rejects_non_uuid_org():
    with pytest.raises(SupabaseError):
        register_or_refresh_device(
            'org-test',
            device_id='dev-1',
            business_id='bdd381de-dbde-43f6-973a-470ff524d91c',
            verify_org_access=False,
        )


def test_device_register_conflict_fallback_inserts_plain():
    org = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
    calls = {'insert': 0}

    def fake_insert(table, row, upsert=False, on_conflict=''):
        calls['insert'] += 1
        if upsert and on_conflict:
            raise SupabaseError(
                'Insert devices failed (400): ON CONFLICT specification '
                'target has no matching unique or exclusion constraint',
                400,
            )
        return {**row, 'id': 'row-1', 'approval_status': 'approved'}

    with patch('backend.cloud.platform_service._find_org_device', return_value=None), \
         patch('backend.cloud.platform_service.service_insert', side_effect=fake_insert), \
         patch('backend.cloud.platform_service._log_device_event'), \
         patch('backend.cloud.platform_service._device_is_revoked', return_value=False):
        row = register_or_refresh_device(
            org,
            device_id='MBT-PC-TEST',
            business_id='bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee',
            verify_org_access=False,
        )
    assert row.get('id') == 'row-1'
    assert calls['insert'] >= 2  # upsert attempt + plain insert
