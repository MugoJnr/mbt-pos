from datetime import datetime, timedelta, timezone

from backend.cloud import platform_service as service


def test_platform_admin_overview_joins_resources_and_counts(monkeypatch):
    rows = {
        "organizations": [
            {"id": "org-1", "name": "Main Shop", "status": "active"},
            {"id": "org-2", "name": "Second Shop", "status": "inactive"},
        ],
        "businesses": [
            {"id": "biz-1", "org_id": "org-1", "name": "Main Shop Business"},
        ],
        "devices": [
            {"id": "device-row", "business_id": "biz-1", "device_id": "PC-1", "is_active": True},
        ],
        "licenses": [
            {"id": "lic-1", "org_id": "org-1", "status": "active"},
            {"id": "lic-2", "org_id": "org-2", "status": "revoked"},
        ],
        "org_members": [
            {"org_id": "org-1", "user_id": "user-1", "is_active": True},
            {"org_id": "org-1", "user_id": "user-2", "is_active": False},
        ],
        "backups": [
            {"id": "backup-1", "business_id": "biz-1", "size_bytes": 100},
        ],
        "audit_logs": [],
        "license_history": [
            {"id": "history-1", "license_id": "lic-1", "action": "created"},
        ],
    }

    def select(table, _query):
        return [dict(row) for row in rows[table]]

    monkeypatch.setattr(service, "service_select_strict", select)
    result = service.list_platform_admin_overview()

    assert result["summary"] == {
        "organizations": 2,
        "businesses": 1,
        "licenses": 2,
        "active_licenses": 1,
        "devices": 1,
        "enabled_devices": 1,
        "members": 1,
        "backups": 1,
    }
    assert result["devices"][0]["org_id"] == "org-1"
    assert result["devices"][0]["org_name"] == "Main Shop"
    assert result["backups"][0]["org_name"] == "Main Shop"
    assert result["license_history"][0]["license_key"] is None
    assert result["license_history"][0]["org_id"] == "org-1"


def test_platform_user_normalization_marks_banned_users_inactive(monkeypatch):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    monkeypatch.setattr(
        service,
        "_auth_admin_request",
        lambda *_args, **_kwargs: {
            "users": [
                {
                    "id": "admin-id",
                    "email": "admin@example.com",
                    "app_metadata": {"platform_role": "platform_admin"},
                    "user_metadata": {"full_name": "Admin"},
                },
                {
                    "id": "banned-id",
                    "email": "banned@example.com",
                    "banned_until": future,
                    "app_metadata": {},
                    "user_metadata": {},
                },
            ],
        },
    )

    users = service.list_platform_users()

    assert users[0]["role"] == "platform_admin"
    assert users[0]["is_active"] is True
    assert users[1]["role"] == "member"
    assert users[1]["is_active"] is False


def test_platform_admin_overview_reports_partial_resource_failures(monkeypatch):
    def select(table, _query):
        if table == "devices":
            raise RuntimeError("devices query denied")
        return []

    monkeypatch.setattr(service, "service_select_strict", select)
    result = service.list_platform_admin_overview()

    assert result["devices"] == []
    assert result["errors"] == {"devices": "devices query denied"}
    assert result["summary"]["organizations"] == 0
