# Performance Report — MBT Platform v3.0

**Date:** 2026-07-21
**Overall:** PASS (baseline recorded; further route-level lazy loading optional)

## Portal SPA (`web/mugobyte-platform`)

| Metric | Before | After | Status |
|--------|--------|-------|--------|
| Main JS chunk | ~720 kB | split: index ~181 kB + react/tanstack/icons | PASS |
| CSS | ~92 kB | ~92 kB | PASS |
| Build time | ~14s | ~7–8s | PASS |
| Chunk warning | Yes (>500kB) | Cleared for portal primary chunks | PASS |

## Live Dashboard (`web/dashboard-ui`)

| Metric | Status | Notes |
|--------|--------|-------|
| Production build | PASS | Vite build succeeds |
| Manual chunks | PASS | react / tanstack / icons |
| Remaining large vendor | PARTIAL | Charts/UI deps still sizable; acceptable for LAN shop PCs |

## Backend / API

| Metric | Status | Evidence |
|--------|--------|----------|
| Health endpoint latency | PASS | Production `/api/health` responds 200 |
| Sync batch size | PASS | Caps 1–500 entities |
| Outbox retries | PASS | Exponential backoff on failure |

## Remediation

- Consider route-level `React.lazy` for rarely used Portal admin screens.
- Profile Desktop POS cold start after next PyInstaller build.
