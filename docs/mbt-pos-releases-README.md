# mbt-pos-releases

Public installers for MBT POS. Shops download `MBT_POS_Setup.exe` from this repository with no account and no token.

This repository must not contain source code. Do not push the POS tree, a submodule, or GitHub's automatic source zip/tar into a release. Each release is only:

- `MBT_POS_Setup.exe` — Windows installer
- `MBT_POS_Setup.exe.sha256` — checksum sidecar (`<64 hex>  MBT_POS_Setup.exe`)
- the release notes, including `[checksum_sha256: <64 hex>]`

Latest installer (what tills and the portal use when they ask for "latest"):

https://github.com/MugoJnr/mbt-pos-releases/releases/latest/download/MBT_POS_Setup.exe

Version check:

https://api.github.com/repos/MugoJnr/mbt-pos-releases/releases/latest

Releases are copied here from `MugoJnr/mbt-pos` by `scripts/publish_release_3.py` and by the GitHub Actions workflow `mirror-public-release.yml`. The copy uses a fine-grained token that can write to this repository and cannot read the source tree. The git tag on this repository points at this README history. The installer is a release asset, not a commit of the application.

Copy this file to the root README of `MugoJnr/mbt-pos-releases` if you want that page to say the same thing. Do not copy any other file from the source repository.
