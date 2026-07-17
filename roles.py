"""
MBT POS — shared role definitions (desktop + web API).
MugoByte Technologies
"""
ROLE_CASHIER = 'cashier'
ROLE_VIEWER = 'viewer'
ROLE_MANAGER = 'manager'
ROLE_ADMIN = 'admin'
ROLE_SUPERADMIN = 'superadmin'

ALL_DESKTOP_TABS = [
    'dashboard', 'sales', 'inventory', 'consumption', 'debt', 'reports', 'notes',
    'settings', 'admin', 'license', 'diagnostics', 'security',
]

TAB_PERMISSIONS_BY_ROLE = {
    ROLE_SUPERADMIN: list(ALL_DESKTOP_TABS),
    ROLE_ADMIN: [
        'dashboard', 'sales', 'inventory', 'consumption', 'debt', 'reports', 'notes',
        'settings', 'admin', 'diagnostics',
    ],
    ROLE_MANAGER: [
        'dashboard', 'sales', 'inventory', 'consumption', 'debt', 'reports',
        'notes', 'settings',
    ],
    ROLE_CASHIER: ['dashboard', 'sales'],
    ROLE_VIEWER: ['dashboard', 'reports'],
}

ROLE_DISPLAY = {
    ROLE_SUPERADMIN: 'Super Admin (shop owner)',
    ROLE_ADMIN: 'Admin (manager)',
    ROLE_MANAGER: 'Manager',
    ROLE_CASHIER: 'Cashier',
    ROLE_VIEWER: 'Viewer',
}


def default_tab_permissions(role: str) -> list:
    return list(TAB_PERMISSIONS_BY_ROLE.get(
        (role or '').strip().lower(),
        TAB_PERMISSIONS_BY_ROLE[ROLE_CASHIER],
    ))


def is_superadmin_role(role: str) -> bool:
    return (role or '').strip().lower() == ROLE_SUPERADMIN


def is_shop_admin_role(role: str) -> bool:
    return (role or '').strip().lower() in (ROLE_ADMIN, ROLE_SUPERADMIN)


def can_assign_role(actor_role: str, target_role: str) -> bool:
    actor = (actor_role or '').strip().lower()
    target = (target_role or '').strip().lower()
    if actor == ROLE_SUPERADMIN:
        return True
    if actor == ROLE_ADMIN:
        return target != ROLE_SUPERADMIN
    return False


def sanitize_tab_permissions(role: str, perms) -> list:
    """Strip owner-only tabs unless role is superadmin."""
    role = (role or '').strip().lower()
    out = list(perms or [])
    if role != ROLE_SUPERADMIN:
        out = [p for p in out if p not in ('security', 'license')]
    return out


def role_display_name(role: str) -> str:
    return ROLE_DISPLAY.get((role or '').strip().lower(), role or 'User')
