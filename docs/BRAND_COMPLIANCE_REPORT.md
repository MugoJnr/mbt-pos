# Brand Compliance Report — MugoByte Ecosystem

**Date:** 2026-07-21
**Scope:** Desktop MBT POS, MugoByte Workspace (Portal), Live Dashboard, installer, emails, reports, Windows metadata
**Contract:** [`brand/brand_contract.json`](../brand/brand_contract.json)

## Verdict

Customer-facing branding is standardized to the official two-tier identity:

| Role | Canonical name |
|------|----------------|
| Company | **MugoByte Technologies** |
| Platform | **MugoByte Platform** |
| Workspace (Portal) | **MugoByte Workspace** |
| POS product | **MBT POS** |
| Shop ops UI | **Live Dashboard** |
| Portal host | **portal.mugobyte.com** |

**Automated gate:** `tests/test_brand_compliance.py` — **9 passed**.
**SPA builds:** Portal and Live Dashboard production builds succeeded after title/meta/asset updates.

## 1. Issues found (pre-fix)

| Area | Issue |
|------|--------|
| Naming | Public mix of MBT Cloud, MugoByte Portal, Web Dashboard, Command Center |
| Version | Desktop and packaging aligned to 3.0.0 |
| Email | Defaults `MBT Cloud <onboarding@resend.dev>` |
| PWA icons | 192/512 files were actually 256×256 MBT POS product art |
| Portal OG | Used POS monitor art instead of company/workspace card |
| Admin | Hardcoded fake KPIs (1,284 orgs, etc.) |
| Account | Fake Nairobi session rows |
| Auth | Boxes icon instead of company mark; titles missing/inconsistent |
| LICENSE | Telegram bot advertised as support channel |
| Installer | “MugoByte Portal” shortcut naming; generic NSIS descriptions |
| Splash | Text-only “MBT” mark (no logo asset) |
| EXE metadata | PyInstaller had icon only — no VSVersionInfo |
| Live login | “Command Center” / “MugoByte POS” |
| Docs/API | “MBT Cloud / Portal” titling |

## 2. Issues fixed

- Canonical contract + brand.ts sources for Portal and Live Dashboard
- Forbidden public strings removed from scanned production surfaces
- Email service branded shell + `MugoByte Platform <noreply@mugobyte.com>` defaults
- Fly secrets updated: `EMAIL_FROM`, `SITE_NAME=MugoByte Platform`
- Version aligned to **3.0.0** (`desktop/main.py`, `version.json`)
- Portal/Live `index.html`, manifests, Twitter/OG cards, correct PWA icon dimensions
- Company “M” mark PNGs + `og-card.png` generated for both SPAs
- Auth layout uses company mark; login title `Sign In | MugoByte`
- Admin KPIs → empty placeholders; Demo Business fallback removed; fake sessions removed
- LICENSE support → portal.mugobyte.com (no Telegram)
- Installer Start Menu: **MugoByte Workspace.lnk**; descriptions use MBT POS
- Splash loads `mbt_logo_hd.png` when available
- PyInstaller `file_version_info.txt` wired in `mbt_pos.spec`
- Live Dashboard login/home/AI renamed off Command Center
- Legacy HTML templates titled Live Dashboard
- Desktop Settings / cloud backup dialogs renamed off MBT Cloud

## 3. Assets replaced / added

| Asset | Location |
|-------|----------|
| Company mark ladder 16–512 | `web/*/public/brand/mark_*.png`, `assets/mugobyte_mark_*.png` |
| PWA 192 / 512 / Apple 180 | both SPA `public/` trees (correct pixel sizes) |
| OG / Twitter card 1200×630 | `web/*/public/brand/og-card.png` |
| POS product art retained | `assets/mbt_logo_hd.png`, `assets/mbt_icon.ico` (POS-only) |
| Favicon SVG (company M) | unchanged lettermark, now primary Workspace chrome mark |

## 4. Icons / chrome updated

- Portal `BrandLogo` wordmark uses company mark SVG
- Auth marketing panel uses company mark (click → `/dashboard`)
- Live Dashboard auth uses favicon SVG
- Installer shortcut names/descriptions updated

## 5. Windows metadata

| Item | Status |
|------|--------|
| NSIS Company/Product/Publisher | PASS (`MugoByte Technologies` / `MBT POS`) |
| NSIS HelpLink → portal.mugobyte.com | PASS |
| PyInstaller `VSVersionInfo` | PASS (source wired; full EXE Properties require rebuild via `BUILD.bat`) |
| Full signed installer rebuild | NOT RUN (code-signing still external) |

## 6. Browser metadata

| Surface | Title / app name | Status |
|---------|------------------|--------|
| Portal | `MugoByte Workspace \| MugoByte` | PASS |
| Live Dashboard | `Live Dashboard \| MugoByte` | PASS |
| Sign In | `Sign In \| MugoByte` | PASS |
| Create Account | `Create Account \| MugoByte` | PASS |
| Downloads | `Downloads \| MugoByte` | PASS |
| Admin | `Platform Administration \| MugoByte` | PASS |
| Manifests | Workspace / Live Dashboard | PASS |
| OG + Twitter | present with `/brand/og-card.png` | PASS |

## 7. Remaining branding issues

| Item | Why remaining |
|------|----------------|
| Full PyInstaller + NSIS rebuild | Not executed in this loop (OneDrive/toolchain); version resource is ready |
| Screenshots of every surface | Local portal.mugobyte.com may be CF-blocked from agent IP; code/build verified |
| Supabase Auth email templates | Hosted in Supabase dashboard — separate from Portal Resend branded shell |
| Internal module docstrings still saying “MBT Cloud” in some backend headers | Non-customer; optional cleanup |
| Credit notes / delivery notes / PO document templates | Not implemented as document types — N/A |
| Authenticode / EV signing | External certificate |

## 8. Verification evidence

```text
pytest tests/test_brand_compliance.py  → 9 passed
vite build (mugobyte-platform)         → success
vite build (dashboard-ui)              → success
fly secrets SITE_NAME / EMAIL_FROM     → deployed healthy
```

## Naming rules going forward

1. Never ship **MBT Cloud**, **Web Dashboard**, **Command Center**, or **MugoByte Portal** in customer UI.
2. Use **MBT POS** monitor art only on POS product surfaces; company/platform/workspace use the **M** mark.
3. Browser titles: `{Section} | MugoByte` (Portal) or `{Section} · Live Dashboard | MugoByte` (Live).
4. Keep `tests/test_brand_compliance.py` green in CI.
