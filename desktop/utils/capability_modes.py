"""One activity has one method: direct, admin PIN, or request approval.

Tab access stays on the user. A missing tab hides the activity. A stored
mode is shared by the till and the web dashboard. When no mode is stored,
the shop keeps the behaviour it already has.
"""
from __future__ import annotations

import json

MODES = ('direct', 'admin_pin', 'request')

# Real permission keys, grouped by the navigation tab that owns them.
TAB_ACTIONS = {
    'dashboard': (),
    'sales': (
        'sales.create', 'sales.view_own', 'sales.view_all', 'sales.void', 'sales.refund',
        'sales.request_void', 'sales.request_backdate', 'sales.business_day',
        'sales.edit', 'sales.variance_handle', 'sales.variance_approve',
        'inventory.sales.override_fifo',
    ),
    'receipts': ('sales.view_own', 'sales.view_all'),
    'inventory': (
        'inventory.view', 'inventory.view_cost', 'inventory.create',
        'inventory.edit_info', 'inventory.direct_price', 'inventory.receive',
        'inventory.batch_price', 'inventory.delete', 'inventory.adjust_stock',
        'categories.create', 'categories.manage', 'categories.delete',
        'supplier.view', 'supplier.pay', 'supplier.request', 'supplier.manage',
        'restock.view', 'restock.create', 'restock.manage', 'restock.purchase',
    ),
    'consumption': (
        'consumption.create', 'consumption.edit', 'consumption.void',
        'consumption.request_void', 'consumption.view_report', 'consumption.export',
    ),
    'debt': (
        'debt.view', 'debt.view_own', 'debt.collect', 'debt.create',
        'debt.customer_manage', 'debt.cancel', 'debt.delete',
    ),
    'accounting': (
        'accounting.view', 'accounting.view_reports', 'accounting.create_expenses',
        'accounting.approve_expenses', 'accounting.export', 'accounting.create_journal',
        'accounting.reverse_journal', 'accounting.close_period',
        'accounting.edit_accounts', 'accounting.reconcile_cost',
    ),
    'reports': (
        'reports.view_basic', 'reports.view_all', 'reports.export',
        'reports.view_variance',
    ),
    'notes': ('notes.own', 'notes.view_all'),
    'settings': ('settings.view', 'settings.edit'),
    'admin': ('users.view', 'users.create', 'users.edit', 'users.delete'),
    'security': ('audit.view', 'audit.clear', 'security.override'),
    'license': ('license.manage',),
    'ai_ops': (
        'ai_ops.view', 'ai_ops.heal_safe', 'ai_ops.support',
        'ai_ops.analyze', 'ai_ops.developer',
    ),
}

# These already wait for an administrator when the mode has not been chosen.
IMPLICIT_REQUEST = {
    ('manager', 'inventory.create'),
    ('manager', 'inventory.edit_info'),
}

# Standing permission is not enough. A PIN is required unless a mode says otherwise.
IMPLICIT_PIN = {
    'sales.void',
    'sales.refund',
    'debt.delete',
}


def _parse_map(value) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value or '{}')
        except (TypeError, ValueError):
            return {}
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, mode in value.items():
        mode = str(mode or '').strip().lower()
        if mode in MODES:
            out[str(key).strip()] = mode
    return out


def tab_for(action: str) -> str:
    action = str(action or '').strip()
    for tab, actions in TAB_ACTIONS.items():
        if action in actions:
            return tab
    prefix = action.split('.', 1)[0]
    return {
        'sales': 'sales',
        'inventory': 'inventory',
        'categories': 'inventory',
        'supplier': 'inventory',
        'restock': 'inventory',
        'consumption': 'consumption',
        'debt': 'debt',
        'accounting': 'accounting',
        'reports': 'reports',
        'notes': 'notes',
        'users': 'admin',
        'settings': 'settings',
        'audit': 'security',
        'license': 'license',
        'security': 'security',
        'ai_ops': 'ai_ops',
    }.get(prefix, '')


def load_modes(user_id) -> dict:
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return {}
    try:
        from desktop.utils.api_client import _db
        db = _db()
        try:
            row = db.execute(
                "SELECT permission_modes, tab_permissions, role FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
        finally:
            db.close()
    except Exception:
        return {}
    if not row:
        return {}
    try:
        raw = row['permission_modes']
    except (KeyError, IndexError):
        raw = None
    return _parse_map(raw)


def resolve_mode(api, action: str) -> str:
    """direct, admin_pin, request, hidden, or legacy_deny."""
    from desktop.utils.security import (
        ROLE_SUPERADMIN, client_actor, has_permission, role_actions,
    )
    from roles import visible_tabs
    action = str(action or '').strip()
    actor = client_actor(api)
    role = str(actor.get('role') or '').strip().lower()
    if not role:
        return 'hidden'
    if role == ROLE_SUPERADMIN:
        return 'direct'
    modes = load_modes(getattr(api, '_user_id', None))
    tab = tab_for(action)
    stored_tabs = None
    try:
        user_id = int(getattr(api, '_user_id', None))
    except (TypeError, ValueError):
        user_id = None
    if user_id:
        try:
            from desktop.utils.api_client import _db
            db = _db()
            try:
                row = db.execute(
                    "SELECT tab_permissions FROM users WHERE id=?", (user_id,),
                ).fetchone()
            finally:
                db.close()
            if row is not None:
                raw_tabs = row['tab_permissions']
                if isinstance(raw_tabs, str):
                    raw_tabs = json.loads(raw_tabs or '[]')
                stored_tabs = raw_tabs if isinstance(raw_tabs, list) else []
        except Exception:
            stored_tabs = None
    if tab and stored_tabs is not None and tab not in visible_tabs(role, stored_tabs):
        return 'hidden'
    if action in modes:
        mode = modes[action]
    else:
        mode = role_default_mode(role, action)
    if mode:
        if mode == 'direct' and action in direct_locks() and action not in role_actions(role):
            return 'request'
        if role == 'viewer' and action not in role_actions('viewer') and mode == 'direct':
            return 'request'
        return mode
    if (role, action) in IMPLICIT_REQUEST:
        return 'request'
    if has_permission(actor, action):
        return 'admin_pin' if action in IMPLICIT_PIN else 'direct'
    return 'legacy_deny'


def require_pin(api, pin: str, pin_username: str, reason: str) -> dict | None:
    from desktop.utils.api_client import _db
    from desktop.utils.superadmin_pin import gate_personal_pin
    db = _db()
    try:
        name = pin_username or getattr(api, '_authoriser_username', '') or ''
        if hasattr(api, '_pin_authoriser_name'):
            name = api._pin_authoriser_name(pin_username)
        gate = gate_personal_pin(db, '' if pin is None else str(pin), name)
        if gate:
            try:
                db.commit()
            except Exception:
                pass
            return gate
        db.commit()
    finally:
        db.close()
    return None


def open_activity(api, action: str, data: dict | None = None, *, reason: str = '') -> dict:
    """None-like success is {'proceed': True}. Otherwise return this dict to the caller."""
    data = data or {}
    mode = resolve_mode(api, action)
    if mode == 'hidden':
        return {'error': 'That section is not on this account.', 'status': 403}
    if mode == 'legacy_deny':
        return {'error': 'You cannot do that.', 'status': 403}
    if mode == 'request':
        return {'proceed': False, 'queue': True, 'mode': mode}
    if mode == 'admin_pin':
        pin_error = require_pin(
            api, data.get('pin') or data.get('superadmin_pin'),
            data.get('pin_username') or '',
            reason or action,
        )
        if pin_error:
            return pin_error
    return {'proceed': True, 'mode': mode}


def saved_mode_decision(api, action: str, pin: str = '', pin_username: str = '', reason: str = '') -> dict:
    """Honor a saved personal mode or a saved role default.

    When nobody has saved a choice, return {'legacy': True} so the existing
    role check stays in force. A replay from Approval Centre proceeds once.
    """
    if getattr(api, '_capability_replay', False):
        return {'proceed': True, 'mode': 'direct', 'replay': True}
    from desktop.utils.security import client_actor
    actor = client_actor(api)
    role = str(actor.get('role') or '').strip().lower()
    modes = load_modes(getattr(api, '_user_id', None))
    chosen = action in modes or bool(role_default_mode(role, action))
    if not chosen:
        return {'legacy': True}
    mode = resolve_mode(api, action)
    if mode in ('hidden', 'legacy_deny'):
        return {
            'error': 'That section is not on this account.' if mode == 'hidden' else 'You cannot do that.',
            'status': 403,
            'executed': False,
        }
    if mode == 'request':
        return {'queue': True, 'mode': 'request', 'executed': False}
    if mode == 'admin_pin':
        pin_error = require_pin(api, pin, pin_username, reason or action)
        if pin_error:
            pin_error['executed'] = False
            return pin_error
        return {
            'proceed': True,
            'mode': 'admin_pin',
            'authoriser': pin_username or getattr(api, '_username', '') or '',
        }
    return {'proceed': True, 'mode': mode, 'authoriser': getattr(api, '_username', '') or ''}


def apply_mode_change(role: str, grants, denials, modes: dict, action: str, mode: str) -> dict:
    """Return updated grants, denials, and modes. Reject a direct locked action."""
    from desktop.utils.security import NOT_GRANTABLE, _known_actions, role_actions
    role = (role or '').strip().lower()
    action = str(action or '').strip()
    mode = str(mode or '').strip().lower()
    if action not in _known_actions():
        return {'error': 'That activity is not on this till.', 'status': 400}
    if mode not in MODES:
        return {'error': 'Choose Direct, Admin PIN, or Request approval.', 'status': 400}
    if role == 'superadmin':
        return {'error': 'Super Admin access follows that role.', 'status': 400}
    locks = direct_locks()
    if mode == 'direct' and action in locks and action not in role_actions(role):
        return {
            'error': locks[action] or 'Direct is locked for this activity. Choose Admin PIN or Request approval.',
            'status': 400,
        }
    if role == 'viewer' and mode == 'direct' and action not in role_actions('viewer'):
        return {
            'error': 'A viewer stays read-only. Choose Admin PIN or Request approval.',
            'status': 400,
        }
    grants = set(grants or ())
    denials = set(denials or ())
    modes = dict(modes or {})
    modes[action] = mode
    owned = role_actions(role)
    if mode in ('direct', 'admin_pin'):
        denials.discard(action)
        if action in owned:
            grants.discard(action)
        else:
            grants.add(action)
    else:
        grants.discard(action)
        if action in owned:
            denials.add(action)
        else:
            denials.discard(action)
    return {
        'permission_grants': sorted(grants),
        'permission_denials': sorted(denials),
        'permission_modes': modes,
    }


def screen_for(user: dict) -> dict:
    """Tabs and activities for the capability screen. Real actions only."""
    from desktop.utils.security import NOT_GRANTABLE, _ACTION_LABELS, _parse_actions, role_actions
    from roles import ALL_DESKTOP_TABS, TAB_PERMISSIONS_BY_ROLE, visible_tabs
    role = str((user or {}).get('role') or '').strip().lower()
    raw_tabs = user.get('tab_permissions')
    if isinstance(raw_tabs, str):
        try:
            raw_tabs = json.loads(raw_tabs or '[]')
        except (TypeError, ValueError):
            raw_tabs = []
    if not isinstance(raw_tabs, list):
        raw_tabs = list(TAB_PERMISSIONS_BY_ROLE.get(role) or [])
    tabs_on = set(visible_tabs(role, raw_tabs))
    modes = _parse_map(user.get('permission_modes'))
    grants = _parse_actions(user.get('permission_grants'))
    denials = _parse_actions(user.get('permission_denials'))
    owned = role_actions(role)
    sections = []
    for tab in ALL_DESKTOP_TABS:
        actions = TAB_ACTIONS.get(tab) or ()
        if not actions and tab not in ('dashboard', 'diagnostics'):
            continue
        items = []
        locks = direct_locks()
        for action in actions:
            personal = action in modes
            if personal:
                selected = modes[action]
            else:
                inherited = role_default_mode(role, action)
                if inherited:
                    selected = inherited
                elif (role, action) in IMPLICIT_REQUEST:
                    selected = 'request'
                elif action in (owned - denials) or action in grants:
                    selected = 'admin_pin' if action in IMPLICIT_PIN else 'direct'
                else:
                    selected = 'request'
            items.append({
                'key': action,
                'label': _ACTION_LABELS.get(action, action),
                'mode': selected,
                'override': personal,
                'locked_direct': action in locks or (role == 'viewer' and action not in owned),
                'lock_reason': locks.get(action, ''),
            })
        if not items and tab not in ('dashboard',):
            continue
        sections.append({
            'tab': tab,
            'enabled': tab in tabs_on or role == 'superadmin',
            'activities': items,
        })
    enabled = [item['tab'] for item in sections if item['enabled']]
    return {
        'role': role,
        'tabs': sections,
        'accessible_tabs': enabled,
        'hidden_tabs': [item['tab'] for item in sections if not item['enabled']],
        'direct': sum(1 for s in sections for a in s['activities'] if a['mode'] == 'direct'),
        'admin_pin': sum(1 for s in sections for a in s['activities'] if a['mode'] == 'admin_pin'),
        'request': sum(1 for s in sections for a in s['activities'] if a['mode'] == 'request'),
        'customized': bool(int((user or {}).get('capability_customized') or 0)),
    }


_SETTINGS = 'capability_role_defaults'
_LOCKS = 'capability_direct_locks'

# Starting policy. A Super Admin can change these rows. They are not hidden.
DEFAULT_LOCKS = {
    'inventory.adjust_stock': 'Stock quantity changes default to a request. A Super Admin can allow Direct from Security policy.',
    'categories.delete': 'Deleting a shop category is locked to a request or an Admin PIN until a Super Admin allows Direct.',
    'audit.clear': 'Clearing the audit log stays off Direct until a Super Admin allows it.',
    'license.manage': 'Licence changes stay off Direct for every role except Super Admin.',
    'security.override': 'Security overrides stay off Direct for every role except Super Admin.',
    'debt.delete': 'Deleting a debt stays off Direct until a Super Admin allows it.',
    'ai_ops.developer': 'Developer shop tools stay off Direct until a Super Admin allows them.',
    'sales.edit': 'Editing a posted sale stays off Direct until a Super Admin allows it.',
    'users.view': 'Opening the staff list stays off Direct until a Super Admin allows it.',
    'users.create': 'Creating staff stays off Direct until a Super Admin allows it.',
    'users.edit': 'Editing staff stays off Direct until a Super Admin allows it.',
    'users.delete': 'Disabling staff stays off Direct until a Super Admin allows it.',
    'settings.edit': 'Changing shop settings stays off Direct until a Super Admin allows it.',
    'accounting.edit_accounts': 'Editing the chart of accounts stays off Direct until a Super Admin allows it.',
    'accounting.close_period': 'Closing a period stays off Direct until a Super Admin allows it.',
    'accounting.reconcile_cost': 'Reconciling a missing cost stays off Direct until a Super Admin allows it.',
    'consumption.void': 'Voiding internal use stays off Direct until a Super Admin allows it.',
    'consumption.edit': 'Correcting internal use stays off Direct until a Super Admin allows it.',
}


def _setting(db, key: str):
    row = db.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    try:
        return row['value']
    except (KeyError, IndexError):
        return row[0]


def direct_locks() -> dict:
    """Actions whose Direct choice is locked, with the reason a shop owner can read."""
    try:
        from desktop.utils.api_client import _db
        db = _db()
        try:
            raw = _setting(db, _LOCKS)
        finally:
            db.close()
    except Exception:
        raw = None
    if not raw:
        return dict(DEFAULT_LOCKS)
    parsed = _parse_map_reasons(raw)
    return parsed if parsed else dict(DEFAULT_LOCKS)


def _parse_map_reasons(value) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value or '{}')
        except (TypeError, ValueError):
            return {}
    if not isinstance(value, dict):
        return {}
    return {str(key): str(text or '') for key, text in value.items() if str(key).strip()}


def save_direct_locks(actor_role: str, locks: dict) -> dict:
    from desktop.utils.security import ROLE_SUPERADMIN, _known_actions
    if (actor_role or '').strip().lower() != ROLE_SUPERADMIN:
        return {'error': 'Only a Super Admin can change which activities can be Direct.', 'status': 403}
    known = _known_actions()
    clean = {}
    for key, reason in (locks or {}).items():
        key = str(key or '').strip()
        if key not in known:
            continue
        clean[key] = str(reason or DEFAULT_LOCKS.get(key) or 'Direct is locked for this activity.').strip()
    from desktop.utils.api_client import _db
    db = _db()
    try:
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
            (_LOCKS, json.dumps(clean)),
        )
        from desktop.utils.api_client import _audit
        _audit(None, actor_role, 'CAPABILITY_LOCKS', 'security',
               'direct locks ' + ', '.join(sorted(clean)), conn=db)
        db.commit()
    finally:
        db.close()
    return {'success': True, 'locks': clean}


def role_default_mode(role: str, action: str) -> str:
    profile = load_role_defaults().get((role or '').strip().lower()) or {}
    mode = str((profile.get('modes') or {}).get(action) or '').strip().lower()
    return mode if mode in MODES else ''


def load_role_defaults() -> dict:
    try:
        from desktop.utils.api_client import _db
        db = _db()
        try:
            raw = _setting(db, _SETTINGS)
        finally:
            db.close()
    except Exception:
        raw = None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or '{}')
        except (TypeError, ValueError):
            raw = {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for role, profile in raw.items():
        if not isinstance(profile, dict):
            continue
        tabs = profile.get('tabs') if isinstance(profile.get('tabs'), list) else []
        modes = _parse_map(profile.get('modes'))
        out[str(role).strip().lower()] = {'tabs': [str(tab) for tab in tabs], 'modes': modes}
    return out


def suggested_role_profile(role: str) -> dict:
    """The starting profile shown before a Super Admin saves one."""
    from roles import default_tab_permissions
    role = (role or '').strip().lower()
    saved = load_role_defaults().get(role)
    if saved:
        return saved
    modes = {}
    if role == 'cashier':
        modes['inventory.adjust_stock'] = 'request'
        modes['sales.void'] = 'request'
    if role == 'manager':
        modes['inventory.create'] = 'request'
        modes['inventory.edit_info'] = 'request'
        modes['inventory.adjust_stock'] = 'request'
        modes['sales.void'] = 'admin_pin'
    if role == 'admin':
        modes['inventory.adjust_stock'] = 'request'
        modes['sales.void'] = 'admin_pin'
    if role == 'viewer':
        modes['inventory.adjust_stock'] = 'request'
    return {'tabs': list(default_tab_permissions(role)), 'modes': modes}


def save_role_default(actor_role: str, role: str, tabs, modes: dict) -> dict:
    from desktop.utils.security import ROLE_SUPERADMIN
    from roles import ROLE_DISPLAY, sanitize_tab_permissions
    if (actor_role or '').strip().lower() != ROLE_SUPERADMIN:
        return {'error': 'Only a Super Admin can change role defaults.', 'status': 403}
    role = (role or '').strip().lower()
    if role not in ROLE_DISPLAY or role == 'superadmin':
        return {'error': 'Choose Cashier, Viewer, Manager, or Admin.', 'status': 400}
    clean_modes = {}
    for action, mode in _parse_map(modes).items():
        checked = apply_mode_change(role, [], [], {}, action, mode)
        if checked.get('error'):
            return checked
        clean_modes[action] = mode
    profile = {
        'tabs': sanitize_tab_permissions(role, tabs or []),
        'modes': clean_modes,
    }
    current = load_role_defaults()
    current[role] = profile
    from desktop.utils.api_client import _db
    db = _db()
    try:
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
            (_SETTINGS, json.dumps(current)),
        )
        from desktop.utils.api_client import _audit
        _audit(None, actor_role, 'CAPABILITY_ROLE_DEFAULT', 'security',
               f"role={role} tabs={','.join(profile['tabs'])}", conn=db)
        db.commit()
    finally:
        db.close()
    return {'success': True, 'role': role, 'profile': profile}


def initial_user_access(role: str) -> dict:
    """Tabs and modes copied onto a new account. Empty modes keep today's behaviour."""
    from roles import default_tab_permissions
    profile = load_role_defaults().get((role or '').strip().lower())
    if not profile:
        return {
            'tab_permissions': default_tab_permissions(role),
            'permission_modes': {},
            'permission_grants': [],
            'permission_denials': [],
        }
    grants, denials, modes = [], [], {}
    for action, mode in (profile.get('modes') or {}).items():
        step = apply_mode_change(role, grants, denials, modes, action, mode)
        if step.get('error'):
            continue
        grants, denials, modes = step['permission_grants'], step['permission_denials'], step['permission_modes']
    return {
        'tab_permissions': profile.get('tabs') or default_tab_permissions(role),
        'permission_modes': modes,
        'permission_grants': grants,
        'permission_denials': denials,
    }


def apply_role_default(actor_role: str, role: str, user_ids, *, replace: bool, confirm: bool) -> dict:
    """Copy a saved role profile. Preserve skips people who were customized."""
    from desktop.utils.security import ROLE_SUPERADMIN
    if (actor_role or '').strip().lower() != ROLE_SUPERADMIN:
        return {'error': 'Only a Super Admin can apply role defaults.', 'status': 403}
    if replace and not confirm:
        return {
            'error': 'Replacing individual settings needs confirmation.',
            'status': 400,
        }
    profile = load_role_defaults().get((role or '').strip().lower())
    if not profile:
        return {'error': 'Save the role default before applying it.', 'status': 400}
    ids = []
    for item in user_ids or []:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {'error': 'Choose at least one person.', 'status': 400}
    from desktop.utils.api_client import _db
    db = _db()
    updated, skipped = [], []
    try:
        for uid in ids:
            row = db.execute(
                "SELECT id, role, capability_customized FROM users WHERE id=?",
                (uid,),
            ).fetchone()
            if not row or str(row['role'] or '').strip().lower() != role:
                skipped.append(uid)
                continue
            if int(row['capability_customized'] or 0) and not replace:
                skipped.append(uid)
                continue
            access = initial_user_access(role)
            db.execute(
                "UPDATE users SET tab_permissions=?, permission_modes=?, permission_grants=?, "
                "permission_denials=?, capability_customized=? WHERE id=?",
                (
                    json.dumps(access['tab_permissions']),
                    json.dumps(access['permission_modes']),
                    json.dumps(access['permission_grants']),
                    json.dumps(access['permission_denials']),
                    0,
                    uid,
                ),
            )
            updated.append(uid)
        db.commit()
    finally:
        db.close()
    return {'success': True, 'updated': updated, 'skipped': skipped}
