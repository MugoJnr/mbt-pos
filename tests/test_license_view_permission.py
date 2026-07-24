"""License status view permission for portal owners vs shop roles."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from flask import Flask, g


class LicenseViewPermissionTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.req = self.app.test_request_context()
        self.req.push()

    def tearDown(self):
        self.req.pop()
        self.ctx.pop()

    def test_shop_manager_allowed(self):
        from web import web_routes as wr

        g.current_user = {'id': 1, 'role': 'manager'}
        self.assertTrue(wr._can_view_license_details())

    def test_platform_admin_allowed(self):
        from web import web_routes as wr

        g.current_user = {'id': 'uuid', 'role': 'platform_admin'}
        self.assertTrue(wr._can_view_license_details())

    def test_jwt_member_with_org_owner_allowed(self):
        from web import web_routes as wr

        g.current_user = {'id': 'user-uuid', 'role': 'member'}
        with patch.object(wr, '_cloud_user_id', return_value='user-uuid'), patch(
            'backend.cloud.platform_service.list_organizations_for_user',
            return_value=[{'id': 'org-1', 'role': 'owner'}],
        ), patch(
            'backend.cloud.platform_service.require_org_access',
            return_value={'org_id': 'org-1', 'role': 'owner'},
        ):
            self.assertTrue(wr._can_view_license_details())

    def test_jwt_member_without_admin_org_denied(self):
        from web import web_routes as wr

        g.current_user = {'id': 'user-uuid', 'role': 'member'}

        def deny(*_a, **_k):
            raise PermissionError('Organization administrator access required')

        with patch.object(wr, '_cloud_user_id', return_value='user-uuid'), patch(
            'backend.cloud.platform_service.list_organizations_for_user',
            return_value=[{'id': 'org-1', 'role': 'cashier'}],
        ), patch(
            'backend.cloud.platform_service.require_org_access',
            side_effect=deny,
        ):
            self.assertFalse(wr._can_view_license_details())


if __name__ == '__main__':
    unittest.main()
