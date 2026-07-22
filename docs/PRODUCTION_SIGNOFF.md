# MBT POS — Production Sign-off

**Version under review:** 3.0.4 (installer-certified)  
**Status:** APPROVED for production release

## Installer certification (mandatory)

Setup SHA-256: `0ea59d338a60fbb7b2a38d158c65b032c6ee175f848f735727ee6f99e74b14e3`  
Release: https://github.com/MugoJnr/mbt-pos/releases/tag/v3.0.4

| Gate | Result |
|------|--------|
| Silent install `/S` | PASS |
| EXE version 3.0.4.0 | PASS |
| Registry Version 3.0.4 | PASS |
| Upgrade DB/license preserved | PASS |
| Customer journey | PASS |
| UI walkthrough | PASS fails=0 |
| Portal health | PASS |
| Pytest | 198 passed |

## Summary

| Area | Result |
|------|--------|
| Certified installer | `dist\MBT_POS_Setup.exe` |
| Git tag | `v3.0.4` @ `aee8b5f` |
| Portal | https://portal.mugobyte.com — deployed, health 200 |
| Live Dashboard | Requires Desktop POS + Cloudflare tunnel running on shop PC (CF 1033 when tunnel down) |

## Sign-off

| Role | Name | Date | Verdict |
|------|------|------|---------|
| Lead Engineer (Cursor) | Auto | 2026-07-22 | **APPROVED** (installer-certified) |
| Product Owner | — | — | — |
