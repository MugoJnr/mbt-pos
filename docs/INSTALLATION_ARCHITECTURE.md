# MBT Installation Architecture (Locked)

## Two paths only — installer decides

### New installation
No `MBT_POS.exe` at install dir / registry → install files → first launch → Setup Wizard → Portal activation → SQLite init → Ready.

### Upgrade installation
Existing install detected → backup AppData DB + license → update Program Files → preserve AppData settings/license → launch POS (wizard skipped) → Done.

User never chooses Upgrade vs Fresh.

## Portal Download Center
`https://portal.mugobyte.com/downloads` is the download page. The file itself is `MBT_POS_Setup.exe` on the public repository `MugoJnr/mbt-pos-releases` (latest asset URL, no token). The source repository is not the download host once it is private.

## Separation
- Portal = cloud account, licenses, devices, downloads
- Live Dashboard = `{shop}.mugobyte.com` live ops via Cloudflare → local SQLite
Never merge.
