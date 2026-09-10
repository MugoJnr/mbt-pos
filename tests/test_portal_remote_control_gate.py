"""Remote-control authorization must fail closed in both portal layers."""
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.cloud.platform_service import require_org_access


ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "web" / "mugobyte-platform" / "src"


@pytest.mark.parametrize("role", ["owner", "superadmin", "admin", "manager"])
def test_backend_allows_only_organization_administrators(role):
    membership = {"org_id": "org-1", "user_id": "user-1", "role": role}
    with patch(
        "backend.cloud.platform_service.get_org_membership",
        return_value=membership,
    ):
        assert require_org_access("user-1", "org-1", admin=True) == membership


@pytest.mark.parametrize("role", ["member", "cashier", "viewer", ""])
def test_backend_rejects_non_admin_organization_members(role):
    membership = {"org_id": "org-1", "user_id": "user-1", "role": role}
    with patch(
        "backend.cloud.platform_service.get_org_membership",
        return_value=membership,
    ):
        with pytest.raises(
            PermissionError,
            match="Organization administrator access required",
        ):
            require_org_access("user-1", "org-1", admin=True)


def test_portal_remote_control_uses_real_membership_and_fails_closed():
    route = (PORTAL / "routes" / "_app.remote-control.tsx").read_text(
        encoding="utf-8",
    )
    sidebar = (PORTAL / "components" / "layout" / "AppSidebar.tsx").read_text(
        encoding="utf-8",
    )
    platform = (PORTAL / "lib" / "platform.ts").read_text(encoding="utf-8")

    assert "canManageOrganization(activeOrganization, user?.role)" in route
    assert "|| Boolean(orgId)" not in route
    assert 'item.url !== "/remote-control" || canOperateRemotely' in sidebar
    assert 'role: "owner", is_primary: true' not in platform
    assert "return [];" in platform
