from pathlib import Path


def test_license_activation_seat_guard_serializes_concurrent_claims():
    migration = (
        Path(__file__).resolve().parents[1]
        / 'supabase' / 'migrations' / '20260818000000_license_activation_seat_guard.sql'
    ).read_text(encoding='utf-8').lower()

    assert 'for update' in migration
    assert 'count(distinct device_id)' in migration
    assert "new.is_active is not true" in migration
    assert 'before insert or update of license_id, device_id, is_active' in migration
    assert 'device limit reached' in migration


def test_admin_portal_does_not_present_cloud_fallback_as_locked_pos():
    source = (
        Path(__file__).resolve().parents[1]
        / 'web' / 'mugobyte-platform' / 'src' / 'routes' / '_admin.admin.licenses.tsx'
    ).read_text(encoding='utf-8')

    assert 'const hasDesktopStatus = lic.source === "license_engine";' in source
    assert 'Portal licensing' in source
    assert 'Cloud control plane' in source


def test_license_seat_reconciliation_preserves_history_and_only_deactivates_surplus():
    migration = (
        Path(__file__).resolve().parents[1]
        / 'supabase' / 'migrations' / '20260818000001_reconcile_license_activation_seats.sql'
    ).read_text(encoding='utf-8').lower()

    assert 'row_number() over' in migration
    assert 'last_validated_at desc nulls last' in migration
    assert 'set is_active = false' in migration
    assert 'delete from' not in migration
    assert 'count(distinct device_id)' in migration


def test_backup_portal_requires_a_business_and_does_not_offer_fake_download():
    source = (
        Path(__file__).resolve().parents[1]
        / 'web' / 'mugobyte-platform' / 'src' / 'routes' / '_app.backups.tsx'
    ).read_text(encoding='utf-8')

    assert 'const { orgId } = useAuth();' in source
    assert 'enabled: Boolean(orgId)' in source
    assert 'Select a business to view its backups' in source
    assert 'Restore in MBT POS' in source
    assert 'GET<BackupResponse>("/cloud/backups", { org_id: orgId })' in source
    assert '<Download' not in source
