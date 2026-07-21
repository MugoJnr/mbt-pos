# MBT POS — Figma UI Modernization Source Pack

**Purpose:** Paste this into **Figma Make / Figma AI** (or use as the design brief) so Figma designs the modernization. Cursor will later implement those Figma frames into code.

**Product:** MBT POS by MugoByte Technologies
**Brand accent:** Gold on dark navy operational UI
**Current tip installer:** v2.3.88

**Rule for Figma:** Redesign presentation only. Do not invent new business rules. Preserve all workflows listed below.

---

## 1. Paste this into Figma AI (master prompt)

```
You are designing MBT POS — a premium Windows retail Point of Sale + Web Business Command Center for MugoByte Technologies (Kenya, KES currency).

Create a complete Figma design system + high-fidelity screens for:

A) Desktop POS (primary cashier app, touch-friendly, PyQt5 today)
B) Web Business Command Center (remote managers, React dashboard today)

Brand: "MBT" wordmark + gold accent. Feel: premium enterprise POS (not generic SaaS purple, not cream terracotta). Dense but elegant. Fast. Touch-friendly (min 44px targets on POS).

Design tokens (use these exactly as the starting palette — you may refine but keep gold identity):

DARK:
- App/Surface: #0B1220
- Card: #16213A
- Card2: #1B2943
- Sidebar: #0A101C
- Gold primary: #FBBF24
- Gold FG: #0B1220
- Text: #FFFFFF
- Text muted: #B4C2D6
- Border: #2A4060
- Success: #00D084
- Warn: #FFB000
- Error: #FF4D6D
- Info: #3B82F6

LIGHT:
- App: #F0F4FA
- Surface/Card: #FFFFFF
- Gold: #B87000
- Text: #0C1828
- Text2: #2E4460
- Border: #CDD8E8
- Success: #006B48
- Warn: #A05800
- Error: #B81C2C

Typography: Manrope (UI) + JetBrains Mono (numbers/receipts).
Radius: 6 / 8 / 12 / 16 / 20 px.
Spacing rhythm: 8 / 12 / 16 / 20 / 24 / 32.

Themes to design variants for:
1. Professional Dark (default)
2. Professional Light
3. MugoByte (gold-forward brand)
4. Retail (higher contrast product tiles)
5. Minimal
6. High Contrast (a11y)

Also show shop branding tokens: accent, logo slot, sidebar tint, header tint.

Screens to design (every state: default, loading skeleton, empty, error):

DESKTOP POS:
- Login
- Main shell (sidebar + topbar + content)
- Dashboard (KPIs, charts, recent sales, AI insights, health score)
- Point of Sale (product grid, categories, cart, payments, barcode, receipt preview)
- Inventory (table + product form + low stock)
- Debt / Credit
- Accounting
- Reports
- Internal Consumption
- Notes
- Settings (shop, printers, cloud backup, AI, audio, themes)
- Users / Admin
- Security / Audit
- License
- Diagnostics
- AI Ops / Copilot drawer + Full Workspace AI Operations Center
- Cloud Backup panel
- Dialogs: void, refund, discount, price override, stock adjust, expense approve

WEB COMMAND CENTER:
- Auth gate / login
- Executive Dashboard
- Live Monitoring
- Remote Approvals
- Inventory
- Debt
- Reports
- Notifications
- System Health
- Backup Center
- Branches
- AI Command Center
- Users & Access
- Settings
- Security / License / Diagnostics
- Mobile: bottom nav (Dashboard, Live, Approvals, Inventory, More)

Components library:
Buttons (primary gold, secondary, ghost, danger), inputs, selects, checkboxes, radios, switches, badges, tags, cards, KPI cards, tables (sticky header), dialogs, drawers, toasts, skeletons, charts (bar/line/area/donut), command palette, notification center, empty states.

Motion: subtle 150–250ms fades/slides; respect reduced-motion. Not playful.

Output:
1. Foundations page (tokens, type, icons)
2. Components page
3. Desktop POS flows
4. Web Command Center flows
5. Mobile web flows
6. Prototype links for POS checkout and dashboard navigation
```

---

## 2. Current design tokens (source of truth in code)

### Desktop — `desktop/utils/theme.py`

| Token | Dark | Light |
|-------|------|-------|
| app/surface | `#0B1220` | `#F0F4FA` |
| card | `#16213A` | `#FFFFFF` |
| sidebar | `#0A101C` | `#E2E8F2` |
| gold | `#FBBF24` | `#B87000` |
| text | `#FFFFFF` | `#0C1828` |
| text2 | `#B4C2D6` | `#2E4460` |
| ok | `#00D084` | `#006B48` |
| warn | `#FFB000` | `#A05800` |
| err | `#FF4D6D` | `#B81C2C` |
| border | `#2A4060` | `#CDD8E8` |

Font: **Manrope** (`assets/fonts/`) · Radius: sm6 md8 lg12 xl16 2xl20 · Gap ~18 · Touch min 44px · Anim ~150ms

### Web — `web/dashboard-ui/src/styles.css`

Same gold system; dark default `#05080f` / `#080d18` family; Manrope + JetBrains Mono.

---

## 3. Screen inventory (must stay functional)

### Web routes (`web/dashboard-ui/src/routes/`)

| Route | File |
|-------|------|
| `/` Executive Dashboard | `index.tsx` |
| `/pos` | `pos.tsx` |
| `/inventory` | `inventory.tsx` |
| `/debt` | `debt.tsx` |
| `/reports` | `reports.tsx` |
| `/notes` | `notes.tsx` |
| `/users` | `users.tsx` |
| `/settings` | `settings.tsx` |
| `/security` | `security.tsx` |
| `/license` | `license.tsx` |
| `/diagnostics` | `diagnostics.tsx` |
| `/approvals` | `approvals.tsx` |
| `/live` | `live.tsx` |
| `/health` | `health.tsx` |
| `/notifications` | `notifications.tsx` |
| `/backup` | `backup.tsx` |
| `/branches` | `branches.tsx` |
| `/ai` | `ai.tsx` |

Shell: `web/dashboard-ui/src/components/app-shell.tsx`
Kit: `web/dashboard-ui/src/components/ui-kit.tsx`

### Desktop tabs (`desktop/tabs/`)

| Area | File |
|------|------|
| Dashboard | `dashboard_tab.py` |
| Sales / POS | `sales_tab.py` |
| Inventory | `inventory_tab.py` |
| Debt | `debt_tab.py` |
| Accounting | `accounting_tab.py` |
| Reports | `reports_tab.py` |
| Consumption | `consumption_tab.py` |
| Notes | `notes_tab.py` |
| Settings + Cloud Backup | `settings_tab.py`, `cloud_backup_panel.py` |
| Admin / Users | `admin_tab.py` |
| Security | `security_tab.py` |
| License | `license_tab.py` |
| Diagnostics | `diagnostics_tab.py` |
| AI Ops | `ai_ops_tab.py` |
| Audio | `audio_settings_panel.py` |

AI Copilot: `desktop/widgets/ai_assistant.py`, `desktop/widgets/ai_workspace.py`

---

## 4. Do not redesign away (functionality lock)

Keep working after UI change:

- Auth, roles, permissions
- Sales, voids, refunds, discounts, taxes, M-Pesa
- Inventory, barcode, printers, receipts
- Debt, accounting, reports, expenses
- Offline-first + cloud sync / Supabase backup
- Multi-branch / multi-shop readiness
- Web Command Center APIs
- AI Copilot (OpenRouter)

---

## 5. How to use this in Figma

1. Open [figma.com](https://www.figma.com) (already opened in your Eugene Chrome profile).
2. **New design file** → name: `MBT POS Enterprise UI`
3. Open **Figma Make / AI** (or FigJam AI) → paste **Section 1** master prompt.
4. Ask Figma to generate Foundations + Components first, then Desktop POS, then Web Command Center.
5. When frames are ready, share the **Figma file URL** with Cursor.
6. Cursor implements frames into desktop + web code without changing business logic.

---

## 6. Code pointers for engineers (after Figma approves)

| Layer | Path |
|-------|------|
| Desktop theme tokens | `desktop/utils/theme.py` |
| Web tokens | `web/dashboard-ui/src/styles.css` |
| Web shell | `web/dashboard-ui/src/components/app-shell.tsx` |
| Desktop main window | `desktop/main_window.py` (or equivalent MainWindow) |
| Design docs | `docs/COPILOT_WORKSPACE_REPORT.md`, `docs/COMMAND_CENTER_REPORT.md` |

---

*Generated for Figma-led modernization. Installer tip: MBT_POS_Setup_v2.3.88.exe*

---

## 7. In-code redesign note (2026-07-18)

A presentation-first redesign was implemented in code without waiting on Figma export.
See **`docs/UI_REDESIGN_IN_CODE.md`** for files touched, visual changes, and remaining gaps.
Suggested tip version after UI ship: **2.3.89** (Figma can still refine frames for a later pixel-perfect pass).

---

## 7. Token reconciliation (inventory 2026-07-18)

**Canonical commercial palette (use for redesign):** Desktop tokens from `desktop/utils/theme.py`.

| Token | Canonical | Avoid (old web drift) |
|-------|-----------|------------------------|
| gold | `#FBBF24` | `#f2a800` |
| app/surface | `#0B1220` | `#05080f` / `#080d18` |
| card | `#16213A` | `#0f1a2e` |

Web Command Center should be updated to match Desktop so Figma/code share one system.
Desktop = primary POS floor; Web = Command Center (cleaner Figma mapping source after token sync).
