"""Brand compliance contract — public naming and asset identity."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "brand" / "brand_contract.json").read_text(encoding="utf-8"))

FORBIDDEN = [
    "MBT Cloud",
    "Web Dashboard",
    "Command Center",
    "MugoByte Portal",
    "onboarding@resend.dev",
    "Demo Business",
    "@mbt_admin1_bot",
]

# Paths scanned for customer-facing drift (not comments-only dirs like internal module docs).
SCAN_GLOBS = [
    "web/mugobyte-platform/src/**/*.{ts,tsx,html}",
    "web/dashboard-ui/src/**/*.{ts,tsx,html,css}",
    "web/mugobyte-platform/index.html",
    "web/dashboard-ui/index.html",
    "web/mugobyte-platform/public/site.webmanifest",
    "web/dashboard-ui/public/site.webmanifest",
    "desktop/**/*.py",
    "licensing/*.py",
    "printing/*.py",
    "backend/cloud/email_service.py",
    "LICENSE.txt",
    "version.json",
    "installer.nsi",
]

ALLOW_SUBSTRINGS = [
    "Telegram has been permanently removed",
    "forbidden_public",
    "brand_contract",
]


def _iter_files():
    seen = set()
    for pattern in SCAN_GLOBS:
        for p in ROOT.glob(pattern):
            if p.is_file() and p not in seen:
                if any(x in p.parts for x in ("node_modules", "dist", "__pycache__")):
                    continue
                seen.add(p)
                yield p


def test_brand_contract_names():
    assert CONTRACT["company"] == "MugoByte Technologies"
    assert CONTRACT["platform"] == "MugoByte Platform"
    assert CONTRACT["workspace"] == "MugoByte Workspace"
    assert CONTRACT["pos_product"] == "MBT POS"
    assert CONTRACT["live_dashboard"] == "Live Dashboard"
    assert CONTRACT["portal_host"] == "portal.mugobyte.com"


def test_app_version_matches_version_json():
    main = (ROOT / "desktop" / "main.py").read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', main)
    assert m, "APP_VERSION missing"
    # utf-8-sig tolerates accidental BOM from Windows editors
    vj = json.loads((ROOT / "version.json").read_text(encoding="utf-8-sig"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", vj["version"])
    assert m.group(1) == vj["version"]


def test_email_defaults_are_mugobyte_platform():
    src = (ROOT / "backend" / "cloud" / "email_service.py").read_text(encoding="utf-8")
    assert "MugoByte Platform <noreply@mugobyte.com>" in src
    assert "SITE_NAME" in src and "MugoByte Platform" in src
    assert "onboarding@resend.dev" not in src
    assert "MBT Cloud" not in src


def test_no_forbidden_public_branding_in_scanned_surfaces():
    violations = []
    for path in _iter_files():
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for bad in FORBIDDEN:
            if bad not in text:
                continue
            # Allow explicit allowlist phrases / contract self-reference
            if any(a in text for a in ALLOW_SUBSTRINGS) and bad in (
                "MBT Cloud",
                "Web Dashboard",
                "Command Center",
                "MugoByte Portal",
            ):
                # Still fail if the forbidden string appears outside brand_contract
                if path.name == "brand_contract.json":
                    continue
            # Strip comments for py/ts lightly
            lines = text.splitlines()
            for i, line in enumerate(lines, 1):
                if bad not in line:
                    continue
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("*"):
                    continue
                if "permanently removed" in line and "Telegram" in line:
                    continue
                if path.name == "brand_contract.json":
                    continue
                violations.append(f"{path.relative_to(ROOT)}:{i}: {bad} -> {stripped[:120]}")
    assert not violations, "Forbidden public branding found:\n" + "\n".join(violations[:40])


def test_portal_manifest_and_titles():
    html = (ROOT / "web" / "mugobyte-platform" / "index.html").read_text(encoding="utf-8")
    assert "MugoByte Workspace | MugoByte" in html
    assert 'application-name" content="MugoByte Workspace"' in html
    assert "/brand/og-card.png" in html
    manifest = json.loads(
        (ROOT / "web" / "mugobyte-platform" / "public" / "site.webmanifest").read_text(encoding="utf-8")
    )
    assert manifest["name"] == "MugoByte Workspace"


def test_live_dashboard_manifest_and_titles():
    html = (ROOT / "web" / "dashboard-ui" / "index.html").read_text(encoding="utf-8")
    assert "Live Dashboard | MugoByte" in html
    manifest = json.loads(
        (ROOT / "web" / "dashboard-ui" / "public" / "site.webmanifest").read_text(encoding="utf-8")
    )
    assert manifest["name"] == "Live Dashboard"


def test_pwa_icon_sizes():
    from PIL import Image

    for spa in ("mugobyte-platform", "dashboard-ui"):
        base = ROOT / "web" / spa / "public"
        for name, expected in (
            ("android-chrome-192x192.png", (192, 192)),
            ("android-chrome-512x512.png", (512, 512)),
            ("apple-touch-icon.png", (180, 180)),
        ):
            img = Image.open(base / name)
            assert img.size == expected, f"{spa}/{name} size {img.size} != {expected}"


def test_license_has_no_telegram_support():
    lic = (ROOT / "LICENSE.txt").read_text(encoding="utf-8")
    assert "Telegram" not in lic
    assert "portal.mugobyte.com" in lic


def test_installer_workspace_shortcut():
    nsi = (ROOT / "installer.nsi").read_text(encoding="utf-8")
    assert "MugoByte Workspace.lnk" in nsi
    assert "Publisher" in nsi and "MugoByte Technologies" in nsi
    assert "MugoByte Portal.lnk" not in nsi
