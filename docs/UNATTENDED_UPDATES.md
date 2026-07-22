# Unattended desktop updates (MBT POS)

## Behavior

1. POS downloads `MBT_POS_Setup.exe` in the background (resumable + retries).
2. SHA-256 is resolved from cloud metadata, release notes (`[checksum_sha256: …]`), or a `.sha256` sidecar asset.
3. When the POS is idle (empty cart, no modal/popup, no critical/backup busy) for ~60 seconds, it installs silently and restarts **only if install succeeds**.
4. Shop database and config stay in `%LOCALAPPDATA%\MugoByte\MBT POS` (NSIS upgrade also snapshots them under `backups\pre_upgrade`).

## Elevation without surprise UAC

Fresh installs register scheduled task **`MBT_POS_UpdateHelper`** (SYSTEM / Highest, on-demand — not an always-running service).

- Unprivileged POS writes a constrained job file (`update_job.json`) with installer path + SHA-256.
- Helper runs only `MBT_POS_Setup*.exe /S` after path allowlist + checksum checks.
- No arbitrary command execution is accepted from the job file.

## Legacy PCs / staged fallback

PCs installed before the helper task:

- **Unattended install is blocked** until the helper exists (avoids surprise UAC).
- Manual **Update** button still works via one-time UAC (`RunAs`).
- After that elevated install succeeds, the helper task is registered for future silent updates.

## Loop / concurrency guards

- Named mutex `Global\MBT_POS_UpdateEngine` — one updater engine per PC.
- Install state file tracks in-progress / fail counts; auto-install cools down after repeated failures.
- Concurrent `install_and_restart` calls are rejected.

## Publishing a release

Always publish checksum with the installer:

```
[checksum_sha256: <64-hex>]
[min_version: 1.0.0]
```

And/or upload `MBT_POS_Setup.exe.sha256` next to the setup EXE.
