# MBT POS 3.0.25

## Summary
Permanently eliminate surprise POS prompts and floating flashes during normal cashier work (layout switch, Focus/Restore, Complete Sale, Hold/Resume).

## Fixes
- Never `.show()` parentless explorer/classic chrome or scroll areas during `apply_layout_shell` (was opening brief OS windows with title bar).
- Hide widgets before `setParent(None)` in layout clear / Checkout Pro secondary-action regrid.
- Park new shell chrome under an invisible stash; layout sink widgets use `WA_DontShowOnScreen`.
- Mid-apply + post-apply orphan top-level flash guard (`hide_orphan_pos_flashes`).
- Customer-unavailable warnings demoted to toast; dark MessageBox style remains for intentional confirms/errors.

## Verification
See `_qa_prompts_gone/NOTES.txt` — zero orphan top-level widgets across Classic/Explorer/Pro switches, Focus, Review, Hold/Resume, Complete Sale (mock). Only intentional Yes/No confirms remain by design.

## Residual (by design)
- Yes/No: Hold/Suspend replace, M-Pesa confirm, void/edit confirms, hard license revoke
- Hard errors: sale record failure, critical license/update failures
