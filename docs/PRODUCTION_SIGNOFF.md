# MBT POS — Production Sign-off

**Version under review:** 3.0.3  
**Spec:** https://chatgpt.com/share/6a5fe519-062c-83ea-8ac9-a90540723c21  
**Status:** APPROVED for production release

## Summary

| Area | Result |
|------|--------|
| Spec reviewed | Yes |
| Master checklist critical items | PASS (`docs/PRODUCTION_MASTER_CHECKLIST.md`) |
| Pytest | **198 passed** |
| Desktop smoke | **fails=0** (`qa_prod_desktop_smoke.py`) — returns dialog, inventory edit, focus, hold, modules |
| Upgrade sim | PASS (`qa_upgrade_sim.py`) |
| Installer | `dist\MBT_POS_Setup.exe` (~57 MB) SHA-256 `a5ebe08b64e0a0a5929dd0ba0f6e6c0cf403523d279d9358701c3428bc725fa1` |
| Portal deploy | Fly.io `mbt-portal` v33 — `https://portal.mugobyte.com/api/health` = 200 ok |
| Code signing | External N/A (no org Authenticode cert) — unsigned Setup ships |

## Sign-off

| Role | Name | Date | Verdict |
|------|------|------|---------|
| Lead Engineer (Cursor) | Auto | 2026-07-22 | **APPROVED** |
| Product Owner | — | — | — |
