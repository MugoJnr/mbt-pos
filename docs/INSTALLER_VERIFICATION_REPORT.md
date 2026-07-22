# Installer Verification Report

**Date:** 2026-07-21 (re-checked 2026-07-22, script restored same day)  
**Overall:** PARTIAL for production claim — build + checked-in TEMP upgrade simulation; clean-PC UAT and code signing pending

| Check | Status | Evidence |
|-------|--------|----------|
| Auto detect upgrade vs new | PASS | `installer.nsi` `.onInit` |
| No user Upgrade/New prompt | PASS | Mode derived from existing `MBT_POS.exe` |
| Backup DB | PASS | `$LOCALAPPDATA\...\backups\pre_upgrade\...` |
| Backup WAL/SHM | PASS | Explicit copy commands |
| Backup config | PASS | xcopy config tree |
| Backup license DB | PASS | Copies encrypted license DB |
| Preserve AppData on uninstall | PASS | Comment + design leave data intact |
| Upgrade simulation | PARTIAL (script) | `scripts/qa_upgrade_sim.py` + `tests/test_upgrade_sim_gate.py`: TEMP-only fabricate DB/WAL/SHM/config/license → pre_upgrade backup → dry-run binary replace → assert live+backup intact. **Not clean-PC UAT.** Never writes real AppData (optional `--peek-live` is READ-ONLY). |
| Portal-first wizard on fresh | PASS (code) | `setup_wizard.py` requires Portal account + license |
| Clean-PC launch UAT | OPEN | Not claimed |
| Code-signed installer | BLOCKED (External) | Trusted Windows code-signing certificate required |
| Built `MBT_POS_Setup.exe` this loop | PASS (prior) | Warning-free NSIS build documented for 3.0.0+ |

## Remediation

1. Sign `MBT_POS.exe` and `MBT_POS_Setup.exe`.
2. Publish the SHA-256 checksum to the Portal Download Center.
3. Run clean-PC install UAT on a fresh Windows machine (script evidence above is TEMP-only PARTIAL — does not replace machine UAT). Code signing remains external.

## Upgrade sim how-to

```text
py -3 scripts/qa_upgrade_sim.py
py -3 scripts/qa_upgrade_sim.py --json
py -3 scripts/qa_upgrade_sim.py --peek-live   # READ-ONLY inventory of live markers
py -3 -m pytest tests/test_upgrade_sim_gate.py -q
```
