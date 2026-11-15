# Making MugoJnr/mbt-pos private

Tills installed today check `https://api.github.com/repos/MugoJnr/mbt-pos/releases/latest` with no token and download `MBT_POS_Setup.exe` from that repository. Making the source repository private turns those URLs into 404s. The public repository `MugoJnr/mbt-pos-releases` is the feed that keeps working.

The updater in this branch tries `MugoJnr/mbt-pos-releases` first and falls back to `MugoJnr/mbt-pos`. That code is inside the installer. Merging this branch does not update a till. A till picks it up only by installing a release built from this branch.

## Order of operations

1. Create a fine-grained personal access token.
   - Resource owner: MugoJnr
   - Repository access: only `MugoJnr/mbt-pos-releases`
   - Permissions: Contents read and write
   - Do not grant access to `MugoJnr/mbt-pos`
2. On `MugoJnr/mbt-pos`, add the Actions secret `RELEASES_REPO_TOKEN` with that token. Do not commit it.
3. Put `.github/workflows/mirror-public-release.yml` on the default branch `main`. GitHub starts `release` workflows only from the default branch. The shipping line is `port/v3.1.66-audit`, which is ahead of `main`.
4. Copy `docs/mbt-pos-releases-README.md` to the README of `MugoJnr/mbt-pos-releases`.
5. Build the next installer from this branch and publish it with `python scripts/publish_release_3.py --publish`.
   - That publishes to `MugoJnr/mbt-pos` so tills still on the old updater can download it.
   - With the secret in place, Actions copies `MBT_POS_Setup.exe`, the `.sha256` sidecar, and the notes to `MugoJnr/mbt-pos-releases`. If you also set `RELEASES_REPO_TOKEN` in the shell, the script copies it immediately.
   - Confirm both release pages show the same tag, the same exe, and the same checksum, and that the public release has no source zip attached by us (GitHub may still show a source archive for the README commit; that archive is only this README repository).
6. Leave `MugoJnr/mbt-pos` public. Wait until the tills are running this new version. The first check is about a minute after a till opens, then on the updater interval. A till that never opens will not move.
7. Only then set `MugoJnr/mbt-pos` to private.

Optional, before step 5: run the mirror workflow with tag `v3.1.84` so the current public download URL in `version.json` exists. That does not update old tills. They still read the source repository until step 5 is installed.

## What else goes dark when the source repository is private

Checked on 2026-11-15 against GitHub:

- GitHub Pages is off (`has_pages: false`). Nothing to migrate.
- No submodules.
- No `raw.githubusercontent.com` URLs for this repository in the app, portal, or installer.
- No status badges in a root README.
- Wiki is enabled and Issues are enabled (one open issue). Both become visible only to people with access. Discussions are off.
- Release asset URLs on `MugoJnr/mbt-pos`, including `releases/latest/download/MBT_POS_Setup.exe`, return 404 without a token. That is the till outage this change avoids.
- GitHub's generated source zip/tar for each tag also becomes private. The mirror script does not upload those.
- Actions on this repository keep working. `portal-production.yml` uses `GITHUB_TOKEN` and the existing Fly and Supabase secrets. A private repository does not remove those.
- Unauthenticated `git clone` of `MugoJnr/mbt-pos` fails. That is the point of making it private.
- `web/mugobyte-platform/AGENTS.md` says the portal UI project is connected to Lovable. Lovable's GitHub connection must still be allowed to read the private repository, or portal UI sync stops.
- Rows already stored in Supabase `app_updates.download_url` point at `MugoJnr/mbt-pos` until the next publish. `publish_release_3.py` writes the public versioned URL for the new row. Older rows still 404 after the repository is private. The till uses the GitHub feed first; the stored URL is the portal fallback.
- `version.json` in this branch already names the public URL for v3.1.84. That URL 404s until v3.1.84 is mirrored. The downloads page prefers the cloud row, which still points at the working source-repo file until you publish again.
- `main` (v3.0.74, 2026-10-23) is not the line that built v3.1.84. Desktop releases are cut from `port/v3.1.66-audit`. A change that lands only on `main` is not in the next installer.
- `SETUP_GITHUB.bat` still knows how to create a v2.2.0 release on the source repository. It is a one-time leftover. Do not use it for new releases.
- Historical notes (`docs/PRODUCTION_SIGNOFF.md`, QA captures) still mention old source-repo release URLs. They are records of past tags, not the live feed.
- `backend/shop_update.py` is the dashboard "is this shop behind" check. It uses the same two repositories and does not download the installer.
