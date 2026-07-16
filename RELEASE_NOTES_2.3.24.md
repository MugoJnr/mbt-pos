## MBT POS 2.3.24 — Pending-update crash fix

### What was wrong
- Startup showed **Unexpected Error**: `'MainWindow' object has no attribute '_pending_installer_path'`
- Introduced with the 2.3.22/23 updater path: `_restore_pending_update` (2s timer) could run while `_start_services` was still starting monitors/license/diag and had not yet assigned updater attrs

### What changed
- Initialize `_pending_installer_path` / related updater state in `MainWindow.__init__`
- Guard restore + update-button readers with `getattr(..., None)`

### Verify
- Cold start with a cached `MBT_POS_Setup_v*.exe` in Temp must not crash
- Update button still appears when a newer installer is cached
- Installer: `MBT_POS_Setup.exe`
