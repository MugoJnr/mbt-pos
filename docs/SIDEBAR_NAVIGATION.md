# Collapsible / resizable left navigation

Shipping in v3.0.75 on every shop PC.

## What the user gets

- **Expanded** — the existing icon + label nav, unchanged click, keyboard and
  permission behaviour.
- **Collapsed** — a 64px icon-only rail. Every permitted section is still one
  click away, each icon carries the section name as a tooltip, and the active
  section keeps the gold `:checked` rail.
- **Resizable** — a `QSplitter` between the sidebar and the content pane. Drag
  the handle to any width between 200px and 340px (further limited to 32% of the
  window, so the nav can never eat the POS).
- **Control** — a chevron button in the sidebar header, always visible in both
  modes. Tooltip reads *Collapse navigation* / *Expand navigation*.
  Keyboard shortcut: `Ctrl+B`.

Collapsing is pure chrome. The current tab, an open cart and any half-typed form
survive it: nothing is destroyed or rebuilt.

## Where the preference is stored

`QSettings` — organisation `MugoByte`, application `MBT POS`, group `ui/sidebar`,
keys `ui_sidebar_collapsed` and `ui_sidebar_width` (see
`desktop/utils/sidebar_prefs.py`).

Not `system_settings` / `api.update_settings`, for two reasons:

1. `update_settings` is permission gated. A cashier or viewer could not save
   their own sidebar preference, and they must be able to.
2. `system_settings` is shop-wide and syncs. One till collapsing its sidebar
   would move the sidebar on every other till.

QSettings keeps the preference per Windows user, permission free and offline
safe. Every other shop preference continues to use `system_settings`; only UI
chrome lives in QSettings.

## Widths (logical pixels)

| Constant | Value | Meaning |
| --- | --- | --- |
| `COLLAPSED_WIDTH` | 64 | icon-only rail |
| `EXPANDED_MIN` | 200 | narrowest draggable width |
| `EXPANDED_MAX` | 340 | widest draggable width |
| `DEFAULT_WIDTH` | 240 | first run on a roomy screen |
| `COMPACT_WIDTH` | 208 | first run on a cramped screen |
| `MAX_WINDOW_FRACTION` | 0.32 | hard cap relative to window width |

First-run defaults follow the screen: available width ≤ 1024 boots collapsed,
≤ 1366 boots expanded at the compact width, anything larger boots at 240.
A width saved on a 4K panel is clamped — not rejected — when the same profile
later opens on a 1024×768 till.

Sizes are logical pixels, so Qt scales them for the active device pixel ratio.
Verified at DPR 1.0, 1.25 and 1.5.

## Implementation notes

- `MainWindow._apply_sidebar_state` is the single place that turns
  `(_sidebar_collapsed, _sidebar_width)` into geometry. It wraps the chrome swap
  and `QSplitter.setSizes` in one `setUpdatesEnabled(False)` block, so there is
  no flash or white frame.
- `splitterMoved` never calls `setSizes` — the sidebar's own min/max already
  clamp the drag, which is what keeps the resize loop-free. Writes are debounced
  through a parented single-shot `QTimer` (450ms).
- Signals are wired once in `_connect_sidebar`, guarded by `_sidebar_connected`.
- Labels are elided against the width Qt *actually* granted (the POS pane can
  push back at 1024×768), driven by a sidebar resize event rather than a poll.
- Sidebar width is deliberately **not** set in QSS. `#sidebar` in
  `desktop/utils/theme.py` carries paint only; a `min-width`/`max-width` there
  would fight the splitter.
- Role gating is untouched: the same `_nav` dictionary is built from
  `tab_permissions` before either mode is applied, so collapsing can never
  reveal a hidden tab.

## Evidence and tests

- `tests/test_sidebar_collapse.py` — 28 tests covering clamping, persistence
  round-trip, collapse/expand, elision, small screens, cashier gating and
  single-shot signal wiring.
- `_qa_sidebar_evidence.py` — builds the real `MainWindow` against an isolated
  data root and writes screenshots plus measurements to
  `_qa_v3075_evidence/sidebar/`. Set `MBT_QA_DPR=1.25` to re-capture at another
  device pixel ratio.
