# MBT Installation Architecture (Locked)

## Two paths only — installer decides

### New installation
No `MBT_POS.exe` at install dir / registry → install files → first launch → Setup Wizard → Portal activation → SQLite init → Ready.

### Upgrade installation
Existing install detected → backup AppData DB + license → update Program Files → preserve AppData settings/license → launch POS (wizard skipped) → Done.

User never chooses Upgrade vs Fresh.

## Portal Download Center
`https://portal.mugobyte.com/downloads` is the source of truth for `MBT_POS_Setup.exe`.

## Separation
- Portal = cloud account, licenses, devices, downloads
- Live Dashboard = `{shop}.mugobyte.com` live ops via Cloudflare → local SQLite
Never merge.
