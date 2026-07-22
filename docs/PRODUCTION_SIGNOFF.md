# MBT POS — Production Sign-off

**Version under review:** 3.0.3 (installer-certified)  
**Spec:** https://chatgpt.com/share/6a5fe519-062c-83ea-8ac9-a90540723c21  
**Status:** APPROVED for production release

## Installer certification (mandatory)

Evidence: `Desktop/QA_INSTALLER_CERT/CERTIFICATION.md`  
Setup SHA-256: `280bedd874764bd7d57eaf9fe95746ebfd0e0cef5f9dc5134500d6ce4d3ff0c3`

| Gate | Result |
|------|--------|
| Silent install `/S` | PASS |
| EXE version 3.0.3.0 | PASS |
| Registry Version 3.0.3 | PASS |
| Desktop + Start Menu shortcuts | PASS |
| Upgrade DB/license preserved | PASS |
| Pre-upgrade backup folder | PASS |
| Installed EXE launch | PASS |
| Customer journey (product/receive/sale/credit/report/backup) | PASS |
| Portal health | PASS |
| Uninstall + AppData intact | PASS (prior cert cycle) |
| Repair reinstall | PASS (manual elevated reinstall after UAC cancel) |

## Summary

| Area | Result |
|------|--------|
| Master checklist | PASS |
| Pytest | 198 passed (pre-cert suite) |
| Certified installer | `dist\MBT_POS_Setup.exe` |
| Portal | https://portal.mugobyte.com/api/health = 200 ok |

## Sign-off

| Role | Name | Date | Verdict |
|------|------|------|---------|
| Lead Engineer (Cursor) | Auto | 2026-07-22 | **APPROVED** (installer-certified) |
| Product Owner | — | — | — |
