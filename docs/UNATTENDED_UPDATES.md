# Secure desktop updates (MBT POS)

## Behavior

1. POS downloads `MBT_POS_Setup.exe` in the background (resumable + retries).
2. SHA-256 is resolved from cloud metadata, release notes (`[checksum_sha256: …]`), or a `.sha256` sidecar asset.
3. The POS notifies the user when the verified update is ready.
4. The user clicks **Update** and approves the standard Windows UAC prompt.
5. The app restarts only after a successful install.
6. Shop database and config stay in `%LOCALAPPDATA%\MugoByte\MBT POS`; NSIS snapshots every detected MBT POS user profile under `backups\pre_upgrade`.

## Elevation policy

The retired `MBT_POS_UpdateHelper` SYSTEM task is removed during installation.

An unsigned installer must not be launched as SYSTEM from a user-writable job file, even when that job contains a checksum: a local user could replace both the installer and expected checksum. Until MBT POS releases are Authenticode-signed and the privileged side verifies the trusted publisher, elevation always uses explicit UAC (`RunAs`).

## Loop / concurrency guards

- Named mutex `Global\MBT_POS_UpdateEngine` — one updater engine per PC.
- Install state tracks in-progress and failure counts.
- Concurrent `install_and_restart` calls are rejected.

## Publishing a release

Always publish checksum with the installer:

```
[checksum_sha256: <64-hex>]
[min_version: 1.0.0]
```

And/or upload `MBT_POS_Setup.exe.sha256` next to the setup EXE.
