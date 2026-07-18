# MBT Copilot v2.3.86 — Implementation Report

## Confirmed product direction
MBT AI is an **Enterprise Business Copilot**, not a permanent chatbot sidebar.

### Four display modes
1. **Minimized** — floating `✦ Copilot` FAB (default for cashiers)
2. **Docked** — compact right drawer (Home / Chat / Workspace), resizable 340–640px
3. **Floating** — detachable tool window
4. **Full Workspace** ⭐ — flagship AI Operations Center overlaying the full app window; POS tabs stay loaded in memory; Exit restores exact prior screen

## What shipped
| Area | Implementation |
|------|----------------|
| Full Workspace | `desktop/widgets/ai_workspace.py` — sidebar nav, dashboard KPIs, workspace tabs, quick actions, chat, search |
| Docked Copilot | `desktop/widgets/ai_assistant.py` — Home dashboard, quick actions, context bar, ⛶ Full Workspace |
| Prefs | `desktop/utils/ai/copilot_prefs.py` — remembers width + mode |
| MainWindow | `enter_ai_full_workspace` / `exit_ai_full_workspace` — no POS unload |
| Theme | Enterprise light/dark Copilot palette (accent `#FBBF24` / `#D97706`) |

## Screenshot verification
Folder: `Desktop/QA_EVIDENCE_COPILOT/`
- `01_minimized_fab.png`
- `02_docked_home.png` / `03_docked_drawer.png`
- `04_full_workspace_dashboard.png`
- `05_full_workspace_chat.png`
- `06_back_to_pos.png`
- `07_full_workspace_light.png`

## Known limitations (next iterations)
- Charts/heatmaps not yet rendered (structured bullet cards + KPI tiles first)
- Split-view POS|AI side-by-side not yet separate from Full Workspace
- Voice STT/TTS architecture reserved; not wired
- One-click mutating POS actions still require module confirmation (permission-gated)

## Installer / Git
- Version **2.3.86**
- Setup: `MBT_POS_Setup_v2.3.86.exe` on Desktop + GitHub Latest release
