# MBT POS — UI Redesign In Code (Desktop-First)

**Date:** 2026-07-18  
**Version tip:** **2.3.89** (in `version.json`; Setup not rebuilt yet)  
**Priority:** **Desktop POS first** (MainWindow + all 14 sidebar tabs), then web.  
**Rule:** Presentation only — no business-logic / API / auth / calculation / DB / route changes.

> Note: Earlier agent reports that said “desktop is theme-only / web-first” are **outdated**. The working tree now includes a full desktop tab rhythm pass (see git diff under `desktop/`).

---

## Desktop (primary)

### Shared chrome

| Area | Path | Change |
|------|------|--------|
| QSS / tokens | `desktop/utils/theme.py` | Stronger `#navBtn` active (gold tint + rail), `#pageTitle`, `#mbtCard`, scrollbars, POS toggles ≥44px |
| Widgets | `desktop/utils/widgets.py` | `PageChrome`, `ToolbarRow`; `page_layout` **20/18** + `GAP`; `PrimaryBtn` → `TOUCH_MIN` |
| POS components | `desktop/utils/pos_components.py` | Grid spacing on `GAP`; SummaryCard padding |
| Shell | `desktop/main.py` | Sidebar **240px**, logo/topbar padding via `PADDING` |

### Tabs (sidebar order)

| # | Tab | What changed |
|---|-----|----------------|
| 1 | Dashboard | Margins 20/18, KPI gaps |
| 2 | Point of Sale | Outer 20/18 + GAP; cart radius; cat/pay controls ≥44px |
| 3 | Inventory | `PageChrome` + layout rhythm |
| 4 | Internal Consumption | Form/history/report → 20/18 |
| 5 | Debt Management | Overview/sub-pages/dialogs → 20/18 |
| 6 | Accounting | Sub-panes → 20/18 |
| 7 | Reports | Default page_layout |
| 8 | Notes | Outer 20/18 |
| 9 | AI Operations | Default page_layout |
| 10 | Users & Access | Default page_layout |
| 11 | Settings | Default page_layout |
| 12 | Security | page_intro + margins |
| 13 | License | `PageChrome` |
| 14 | Diagnostics | `PageChrome` + actions |

Deep dialogs (debt/accounting) and settings sub-panels: margins/rhythm only — not full visual redesign.

---

## Web (secondary this pass)

Also updated earlier in the same tip: Command Center tokens (`#0B1220` / `#FBBF24`), shell, executive dashboard charts, touch web POS, shared page headers. `npm run build` succeeded.

---

## Gaps / next

1. Deeper visual redesign of dense desktop dialogs (still functional).  
2. Rebuild **Setup v2.3.89** so the installed EXE picks up desktop polish (frozen EXE ignores hot `.py`).  
3. Optional Figma URL for pixel-perfect follow-up.

---

## Verify

```bash
C:\MBT_Build\_python311\python.exe -m py_compile desktop/main.py desktop/utils/theme.py desktop/utils/widgets.py
# Run from source or rebuild installer to see desktop changes
```
