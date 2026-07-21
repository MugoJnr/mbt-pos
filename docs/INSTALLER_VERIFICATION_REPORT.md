# Installer Verification Report

**Date:** 2026-07-21
**Overall:** PASS (build + upgrade simulation); code signing pending

| Check | Status | Evidence |
|-------|--------|----------|
| Auto detect upgrade vs new | PASS | `installer.nsi` `.onInit` |
| No user Upgrade/New prompt | PASS | Mode derived from existing `MBT_POS.exe` |
| Backup DB | PASS | `$LOCALAPPDATA\...\backups\pre_upgrade\...` |
| Backup WAL/SHM | PASS | Explicit copy commands |
| Backup config | PASS | xcopy config tree |
| Backup license DB | PASS | Copies encrypted license DB |
| Preserve AppData on uninstall | PASS | Comment + design leave data intact |
| Upgrade simulation | PASS | TEMP sim: live+backup DB/settings/license intact after binary replace |
| Portal-first wizard on fresh | PASS (code) | `setup_wizard.py` requires Portal account + license |
| Code-signed installer | BLOCKED (External) | Trusted Windows code-signing certificate required |
| Built `MBT_POS_Setup.exe` this loop | PASS | Warning-free NSIS build, version 3.0.0 |

## Remediation

1. Sign `MBT_POS.exe` and `MBT_POS_Setup.exe`.
2. Publish the SHA-256 checksum to the Portal Download Center.
