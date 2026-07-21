# API Documentation — MugoByte Platform / Portal

**Base URL (production):** `https://portal.mugobyte.com`
**Auth:** Bearer JWT (desktop/portal session) unless noted
**Date:** 2026-07-21

## Health

| Method | Path | Auth | Status |
|--------|------|------|--------|
| GET | `/api/health` | No | PASS verified 200 |

## Auth (cloud)

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/cloud/auth/login` | Email/password → access + refresh cookie |
| POST | `/api/cloud/auth/register` | Requires strong password; email verify |
| POST | `/api/cloud/auth/refresh` | Refresh cookie |
| POST | `/api/cloud/auth/logout` | Clears refresh |
| POST | `/api/cloud/auth/update-password` | Authenticated |

## Organizations / bootstrap

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/cloud/bootstrap` | Ensure business + org for identity |

## Licenses

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/cloud/licenses` | Org-scoped |
| POST | `/api/cloud/licenses` | Create |
| POST | `/api/cloud/licenses/activate` | Activate on device |
| POST | `/api/cloud/licenses/<id>/revoke` | Admin |
| POST | `/api/cloud/licenses/<id>/suspend` | Admin |
| POST | `/api/cloud/licenses/<id>/renew` | Admin |
| POST | `/api/cloud/licenses/<id>/force-validate` | Admin |
| POST | `/api/cloud/licenses/<id>/transfer` | Admin |
| GET | `/api/cloud/licenses/<id>/history` | History |

## Devices

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/cloud/devices` | Org roster |
| POST | `/api/cloud/devices/register` | Desktop self-register → pending |
| POST | `/api/cloud/devices/<id>/approve` | Admin |
| POST | `/api/cloud/devices/<id>/reject` | Admin |
| POST | `/api/cloud/devices/<id>/rename` | Admin |
| POST | `/api/cloud/devices/<id>/deactivate` | Admin |
| GET | `/api/cloud/devices/events` | History |

## Synchronization

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/cloud/sync/batch` | Idempotent entity ingest; approved devices only |

## Classification

| Area | Status |
|------|--------|
| Documented | PASS |
| Live health | PASS |
| Authenticated E2E matrix | PARTIAL / NOT RUN for every mutating route |
