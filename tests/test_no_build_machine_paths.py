"""Shipped code must not carry the build machine's identity.

Everything PyInstaller freezes runs on shop PCs that share nothing with the
machine that produced the installer: different user name, no OneDrive, no
build toolchain, a different shop hostname and tunnel. A literal from this
machine is dead weight at best and, when it is probed first, a wrong answer.
Build scripts, tests, QA harnesses and docs are exempt — they never ship.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Mirrors mbt_pos.spec: the packages and modules that enter the freeze.
# web/ ships only its top-level modules — the SPA subprojects contribute
# nothing but their built dist/, so their tooling is deliberately excluded.
SHIPPED_ROOTS = (
    'backend',
    'desktop',
    'diagnostics',
    'licensing',
    'printing',
)
SHIPPED_MODULES = (
    'launcher.py',
    'web_launcher.py',
    'mbt_paths.py',
    'roles.py',
    'runtime_security.py',
)
SKIP_DIRS = {'node_modules', '__pycache__', '.git', 'dist', 'build'}

FORBIDDEN = {
    'build toolchain path': re.compile(r'MBT_Build', re.I),
    'developer profile path': re.compile(r'[A-Za-z]:[\\/]+Users[\\/]+\w'),
    'OneDrive-relative path': re.compile(r'OneDrive', re.I),
    'test shop hostname': re.compile(r'e2e-fresh-shop', re.I),
    'hard-coded tunnel UUID': re.compile(
        r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',
        re.I),
}


def _shipped_sources() -> list[Path]:
    files = [ROOT / name for name in SHIPPED_MODULES]
    files.extend(sorted((ROOT / 'web').glob('*.py')))
    for package in SHIPPED_ROOTS:
        for path in (ROOT / package).rglob('*.py'):
            if SKIP_DIRS.isdisjoint(path.parts):
                files.append(path)
    return [f for f in files if f.is_file()]


@pytest.mark.parametrize('label,pattern', sorted(FORBIDDEN.items()))
def test_shipped_sources_are_free_of_build_machine_values(label, pattern):
    offenders = []
    for path in _shipped_sources():
        text = path.read_text(encoding='utf-8', errors='replace')
        for number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                rel = path.relative_to(ROOT).as_posix()
                offenders.append(f'{rel}:{number}: {line.strip()[:120]}')
    assert not offenders, (
        f'{label} found in shipped code:\n' + '\n'.join(offenders))


def test_the_scan_actually_covers_the_freeze():
    """A silently empty file list would make every assertion above vacuous."""
    sources = _shipped_sources()
    names = {p.relative_to(ROOT).as_posix() for p in sources}
    assert len(sources) > 100
    assert 'web_launcher.py' in names
    assert 'backend/cloudflare_setup.py' in names
    assert 'desktop/main.py' in names


def _spec_namespace() -> dict:
    """Execute the spec's helper definitions without running PyInstaller."""
    source = (ROOT / 'mbt_pos.spec').read_text(encoding='utf-8')
    header = source[:source.index('a = Analysis(')]
    namespace = {'SPECPATH': str(ROOT)}
    exec(compile(header, 'mbt_pos.spec', 'exec'), namespace)
    return namespace


def test_installer_ships_the_built_spa_but_not_its_toolchain():
    datas = _spec_namespace()['_web_runtime_datas']()
    shipped = {
        Path(src).relative_to(ROOT).as_posix() for src, _dest in datas
    }
    assert 'web/web_routes.py' in shipped
    assert 'web/templates/dashboard.html' in shipped
    assert 'web/mugobyte-platform/dist/index.html' in shipped
    assert 'web/dashboard-ui/dist/index.html' in shipped

    # Front-end tooling, developer scratch files and unbuilt sources are the
    # things a shop PC can neither run nor benefit from.
    banned_names = {
        'package.json', 'package-lock.json', 'bun.lock', 'bunfig.toml',
        'tsconfig.json', 'vite.config.ts', 'eslint.config.js',
        'components.json', 'README.md', 'AGENTS.md', 'MANIFEST.json',
        '.prettierrc', '.prettierignore', '.gitignore',
    }
    for rel in shipped:
        name = rel.rsplit('/', 1)[-1]
        assert name not in banned_names, f'{rel} must not ship'
        assert not name.startswith('_') or rel.endswith('__init__.py'), \
            f'developer scratch file {rel} must not ship'
        assert '/public/' not in rel, f'unbuilt source asset {rel} must not ship'
        assert '/src/' not in rel, f'unbuilt SPA source {rel} must not ship'
        assert '/.lovable/' not in rel, f'editor metadata {rel} must not ship'
        assert not rel.endswith('.map'), f'source map {rel} must not ship'


def test_the_scan_would_catch_a_reintroduced_path(tmp_path):
    sample = r"    for c in [r'C:\MBT_Build\_python311\python.exe']:"
    assert FORBIDDEN['build toolchain path'].search(sample)
    assert FORBIDDEN['developer profile path'].search(
        r'"C:\Users\someone\Desktop\MBT POS"')
    assert not FORBIDDEN['developer profile path'].search(
        "os.path.join(os.path.expanduser('~'), 'Desktop')")
