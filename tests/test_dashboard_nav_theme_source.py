"""Front-end source contracts for the audit's navigation, theme and guard fixes.

The SPAs have no JS test runner in this repo, so — as with the other UI gates
here — the compiled-source contract is asserted directly. Behaviour is proven
server-side in `test_access_audit_web_gates.py`.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / 'web' / 'dashboard-ui'
PORTAL = ROOT / 'web' / 'mugobyte-platform'


def _read(path: Path) -> str:
    assert path.is_file(), f'missing source file: {path}'
    return path.read_text(encoding='utf-8')


# ── 5. sidebar must not advertise modules the backend refuses ────────────────

def test_nav_items_are_gated_by_server_supplied_modules():
    shell = _read(DASHBOARD / 'src' / 'components' / 'app-shell.tsx')
    assert '"/nav/modules"' in shell, 'shell must ask the server for grants'
    assert 'function visibleNav' in shell
    # Unknown grants must hide gated entries rather than show everything.
    assert 'modules?.includes(item.module) ?? false' in shell

    nav_block = shell[shell.index('const NAV: NavItem[]'):shell.index('const MOBILE_NAV')]
    for route, module in (
        ('/users', 'users'),
        ('/settings', 'settings'),
        ('/security', 'security'),
        ('/license', 'license'),
        ('/diagnostics', 'diagnostics'),
        ('/backup', 'backup'),
        ('/reports', 'reports'),
        ('/debt', 'debt'),
        ('/notes', 'notes'),
        ('/ai', 'ai_ops'),
    ):
        entry = next(
            line for line in nav_block.splitlines() if f'to: "{route}"' in line)
        assert f'module: "{module}"' in entry, entry

    # Both the sidebar and the mobile bar render the filtered list.
    assert 'visibleNav(NAV, modules)' in shell
    assert 'visibleNav(MOBILE_NAV' in shell
    assert 'mobileNav.map' in shell


def test_nav_modules_endpoint_exists_server_side():
    routes = _read(ROOT / 'web' / 'web_routes.py')
    assert "@web.route('/api/nav/modules', methods=['GET'])" in routes
    assert 'def _allowed_modules(' in routes


# ── 11. light theme, OS preference and persistence ───────────────────────────

def test_theme_provider_supports_system_light_and_dark():
    theme = _read(DASHBOARD / 'src' / 'components' / 'theme.tsx')
    assert 'prefers-color-scheme: light' in theme
    assert 'MODE_ORDER: ThemeMode[] = ["system", "light", "dark"]' in theme
    assert 'localStorage.setItem(THEME_KEY, mode)' in theme
    # OS changes are followed live while the operator stays on "system".
    assert 'mq.addEventListener("change", onChange)' in theme
    assert 'mq.removeEventListener("change", onChange)' in theme
    assert 'root.style.colorScheme = theme' in theme


def test_theme_is_painted_before_react_mounts():
    html = _read(DASHBOARD / 'index.html')
    boot = html.index('mbt-theme')
    assert boot < html.index('<div id="root">'), 'theme must resolve pre-paint'
    assert 'prefers-color-scheme: light' in html
    assert 'classList.add(light ? "light" : "dark")' in html


def test_light_tokens_exist_for_every_surface():
    css = _read(DASHBOARD / 'src' / 'styles.css')
    assert re.search(r'(?m)^\s*(html\.light|\.light)\b', css), \
        'light palette tokens must be defined'


def test_settings_offers_a_three_way_mode_picker():
    settings = _read(DASHBOARD / 'src' / 'routes' / 'settings.tsx')
    for label in ('"System"', '"Light"', '"Dark"'):
        assert label in settings
    assert 'role="radiogroup"' in settings
    assert 'aria-label="Theme mode"' in settings


def test_theme_toggle_cycles_all_three_modes():
    shell = _read(DASHBOARD / 'src' / 'components' / 'app-shell.tsx')
    toggle = shell[shell.index('export function ThemeToggle'):]
    assert 'cycle' in toggle
    assert 'aria-label' in toggle


# ── 9. unauthenticated portal routes redirect instead of erroring ────────────

def test_portal_guards_redirect_rather_than_raise():
    admin = _read(PORTAL / 'src' / 'routes' / '_admin.tsx')
    app = _read(PORTAL / 'src' / 'routes' / '_app.tsx')
    for source in (admin, app):
        assert 'ensureAuthSession().catch(() => false)' in source, \
            'a rejected bootstrap must fall through to the sign-in redirect'
        assert 'redirect({ to: "/login"' in source or \
            'to: "/login"' in source
    # `location.search` is a parsed object; the return target comes from href.
    assert 'location.href' in admin
    assert '${location.pathname}${location.search' not in admin


def test_login_search_params_stay_optional():
    login = _read(PORTAL / 'src' / 'routes' / '_auth.login.tsx')
    assert '{ redirect?: string; next?: string }' in login


# ── 13. portal shows the true licence state ──────────────────────────────────

def test_admin_licence_badge_trusts_the_expiry_date():
    licenses = _read(PORTAL / 'src' / 'routes' / '_admin.admin.licenses.tsx')
    assert 'function isExpired(' in licenses
    assert 'const expired = isExpired(row.expires_at)' in licenses
    assert '{expired ? "expired" : row.status || "unknown"}' in licenses
