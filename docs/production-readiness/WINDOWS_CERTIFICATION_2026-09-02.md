# MBT POS Windows production-readiness evidence

Date: 2026-09-02  
Target source version: 3.0.75  
Test OS: Windows 11 build 10.0.26200  
Repository branch: `fix/v3.0.74-review-followup`

## Current candidate (post 21:36 rebuild)

This identity supersedes installer/EXE hashes in the “Final integrated
certification” section below. No additional production rebuild or reinstall was
performed in this pass.

### Binary identity

- Installer: `extracted\mbt_pos_v3071_cert\dist\MBT_POS_Setup.exe`
- Installer SHA-256: `8C626A7FA5080EB1BCD20F053A02B9B792CD456AA720B0D8EF86DFBDF67F8C5D`
- Dist and installed EXE SHA-256 (identical): `EE4C179F04EE1DCC89B0F99386329AFB8CA6F3008A8102A91534D0D25996CA77`
- Installed path: `C:\Program Files\MugoByte\MBT POS\MBT_POS.exe`
- Version: `3.0.75` / PE machine `0x8664` / PE subsystem `2` (`WINDOWS_GUI`)
- Authenticode: **NotSigned** (installer and installed EXE)

### Power / WTS session handlers in the frozen binary: **PRESENT**

Factual checks (no rebuild required):

- Source `desktop\utils\windows_session.py` LastWrite `2026-09-02 21:33:26` (+03).
- Frozen `MBT_POS.exe` LastWrite `2026-09-02 21:35:04` (+03); installer
  `2026-09-02 21:36:54`; Program Files install `2026-09-02 21:37:53`.
- No loose `_internal` `windows_session` pyc (expected: onedir PYZ).
- PyInstaller `PYZ.pyz` TOC contains `desktop.utils.windows_session` as a code
  object (`co_filename` `desktop\utils\windows_session.py`) with
  `register_session_notifications`, `WM_POWERBROADCAST`, and
  `WM_WTSSESSION_CHANGE`.
- Packed `desktop.main` contains `_install_windows_session_events` and the
  `desktop.utils.windows_session` import.
- Isolated launch of the installed EXE logged
  `Windows power/session event handling enabled`
  (`C:\MBT_Certification\session-handler-login-20260902\logs\app.log`).

NSIS `MBT_POS_Setup.exe` does not contain those UTF-8 strings in the outer
archive; the module lives inside the compressed onedir EXE.

### Tests and login (this pass)

- Full suite: **383 passed in 54.18s** (`C:\MBT_Build\_python311\python.exe -m pytest`).
- Isolated Program Files login: copy of certification data under
  `C:\MBT_Certification\session-handler-login-20260902`; UI automation reached
  `MainWindow` titled `MBT POS - MugoByte Technologies`. Live shop AppData was
  not used. Cloud restore was not started.
- No persistent console window after startup. PE is GUI. A `cmd.exe` /
  `conhost.exe` child was observed at t≈0.44s and was gone by later samples
  (`kids` empty while MainWindow was visible). Evidence:
  `C:\MBT_Certification\evidence\session-handler-login\result.json`.

### Remaining known blockers / not claimed

- **Unsigned Authenticode** on installer and EXE.
- **Fly portal deploy** still blocked without `FLY_API_TOKEN` / logged-in `flyctl`.
- This PC remains the **E2E Fresh Shop test organization** (`org-test` is not a
  UUID; cloud `businesses`/`devices` calls return Postgres `22P02`). Environment
  note, not a desktop packaging defect.
- **Not tested this pass:** Windows 10, physical mixed-DPI monitor move,
  hibernate/resume, Fast User Switching, RDP, printer hardware, touchscreen.
- OpenCode independent review remains **NOT TESTED**.

## Final integrated certification

Final verdict: **READY** (Windows desktop candidate; see remaining blockers above)

This section supersedes the preliminary run below. Certification was completed against
the integrated, uncommitted working tree on Windows 11 build 10.0.26200. No reset,
revert, or commit was performed.

### Release identity

- Installer: `C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos_v3071_cert\dist\MBT_POS_Setup.exe`
- Installer SHA-256 (superseded by Current candidate above): `86AB1A6BBC6E053DEC1897D48F46A8E793A5473E9364F4F52FC94BF05A9BA243`
- Installed EXE: `C:\Program Files\MugoByte\MBT POS\MBT_POS.exe`
- Built and installed EXE SHA-256 (superseded by Current candidate above): `47ADDEF4742F828B0C4F394FF365E8F62AFD6E7BF83BAD0B46B52A153D2CF751`
- Version: `3.0.75` / PE file version `3.0.75.0`
- Git HEAD: `946721fae6c403f4dcf307a489dde7d6d580021a`
- Source state: uncommitted working tree containing the integrated Windows, portal,
  cloud-backup, security, test, and documentation changes listed by `git status`.

### 38 labeled results

1. **Integrated working tree — PASS.** Windows UI/subprocess/DPI repairs, portal
   dashboard changes, and cloud-backup changes coexist in the current tree. No
   concurrent-edit rollback was performed.
2. **Python compile/test integration — PASS.** Final full run: `382 passed in
   159.14s`.
3. **Portal production assets — PASS.** Vite 6.4.3 transformed 3,602 modules and
   completed the production build in 1m24s. The 1.16 MB main-chunk warning is an
   optimization note, not a functional release blocker.
4. **Idle CPU root cause — PASS.** Profiling identified repeated legacy WMIC
   fingerprint probes, repeated PBKDF2 derivation during license construction,
   per-poll `LicenseEngine` creation, and avoidable new Supabase/TLS sessions.
5. **Idle CPU repair — PASS.** PBKDF2 results are cached by secret/device,
   `CommandPoller` reuses its license engine, cheap identity candidates precede
   WMIC fallback, WMIC is hidden, and the platform client reuses its HTTP session.
6. **CPU regression coverage — PASS.** Windows runtime tests cover key-derivation
   caching and command-poller behavior. The final suite includes these tests.
7. **Release version consistency — PASS.** Python build tag, `version.json`,
   PyInstaller version resource, manifest, NSIS installer, registry, and installed
   file report 3.0.75/3.0.75.0.
8. **PyInstaller windowed configuration — PASS.** `mbt_pos.spec` has
   `console=False`.
9. **Actual PE subsystem — PASS.** Resource inspection reports PE subsystem 2
   (`WINDOWS_GUI`), not a console subsystem.
10. **Architecture — PASS.** Actual built PE machine is `0x8664` (x64).
11. **Execution level — PASS.** RT_MANIFEST extracted from the actual built EXE
   contains `requestedExecutionLevel level="asInvoker" uiAccess="false"`.
12. **DPI manifest — PASS.** Extracted RT_MANIFEST contains legacy `true/pm` and
   `PerMonitorV2,PerMonitor`, plus long-path awareness and Common Controls v6.
13. **Qt DPI configuration — PASS.** High-DPI application attributes are applied
   before `QApplication`; no conflicting MBT AppCompat Layers override or forced
   production `QT_SCALE_FACTOR` was found.
14. **Runtime subprocess visibility — PASS.** WMIC and normal helper probes use
   `CREATE_NO_WINDOW`; report-folder opening uses `os.startfile`. Sustained
   observation found no visible console window.
15. **Qt platform plugin — PASS.** Packaged PyQt5 Qt5 plugin tree contains
   `plugins\platforms\qwindows.dll`.
16. **Qt image plugins — PASS.** Packaged Qt plugin tree contains the required
   image-format plugins, including JPEG and SVG support.
17. **SQLite dependency — PASS.** `_internal\sqlite3.dll` and Python SQLite
   bindings are present and exercised by the installed workflows.
18. **SSL/crypto dependency — PASS.** `_internal\libssl-3.dll`,
   `_internal\libcrypto-3.dll`, and the Qt-compatible SSL libraries are present.
19. **Certificate bundle — PASS.** `_internal\certifi\cacert.pem` is present.
20. **VC runtime assumption — PASS.** `VCRUNTIME140.dll` and
   `VCRUNTIME140_1.dll` are packaged; the candidate launched from Program Files.
21. **cloudflared package — PASS.** `_internal\cloudflared.exe` is present at the
   path expected by the frozen application.
22. **Installed launch isolation — PASS.** The absolute Program Files EXE launched
   and remained alive using an isolated data root; acceptance did not depend on
   repository Python, Git, or a development working directory.
23. **Genuine-data snapshot — PASS.** A consistent pre-final-install snapshot of
   live DB/config/license material is retained at
   `C:\MBT_Certification\live-snapshot-20260902-193756`, with
   `snapshot_hashes.json`.
24. **Elevated final install — PASS.** The final candidate was installed over
   `C:\Program Files\MugoByte\MBT POS`; built and installed EXE hashes are
   identical.
25. **Live business data preservation — PASS.** Snapshot and post-install SQLite
   canonical row comparisons show no changed, added, or removed rows in any
   business table. The raw DB file hash changed only from SQLite file-level
   bookkeeping.
26. **License/config preservation — PASS.** Machine `device.id`,
   `crypto.secret`, cloud configuration, and JWT secret match the snapshot.
   License DB changes are expected runtime metadata (`last_*` timestamps,
   online/offline flags, cloud-license normalization, and eight appended audit
   records); the installed license gate passed.
27. **Registry, shortcuts, and hashes — PASS.** HKLM install path is
   `C:\Program Files\MugoByte\MBT POS`, uninstall version is 3.0.75, and public
   Desktop and Start Menu shortcuts exist.
28. **Retired privilege artifacts — PASS.** No `MBT_POS_UpdateHelper` scheduled
   task, packaged retired SYSTEM helper, or EDMUS marker was found.
29. **Installed startup/login/navigation — PASS.** The actual installed EXE
   completed startup, valid license gate, superadmin login, dashboard, inventory,
   POS, and reopen navigation. Screenshots are in
   `C:\MBT_Certification\evidence\installed-session`.
30. **Adjust Stock workflow — PASS.** Isolated UI add `+5` and decimal remove
   `-0.25` produced stock `14.75`, two `SUPERADMIN_ADJUST` movements, two audit
   entries, and the same value after reopen. Evidence:
   `C:\MBT_Certification\evidence\stock-adjustment\result.json`.
31. **Sale/payment/receipt — PASS.** Installed UI created
   `RCP-20260902-0001`, accepted controlled cash payment, and rendered/reprinted
   the receipt. All rows are confined to the isolated certification root.
32. **Void/restoration/persistence — PASS.** Sale status persisted as `voided`;
   `VOID_RESTORE` restored all seven test units from 18 to 25, exactly reversing
   the sale movement. Reopen retained the result.
33. **Backup/sync/update checks — PASS.** Local backup artifacts were created;
   cloud/sync and update checks ran without blocking the UI or creating a visible
   prompt. Network helper children were short-lived.
34. **Flicker/window-state acceptance — PASS.** Startup/login/navigation,
   Adjust Stock, payment, receipt, maximize, restore, resize, minimize, close, and
   reopen produced no observed abnormal flicker or transient console/prompt
   window. `console_windows` remained empty.
35. **Sustained resource acceptance — PASS.** The final installed session was
   sampled 212 times over 119.7s: CPU average 3.33%, final 60s average 1.92%,
   RSS changed by less than 0.8 MiB, handles ended where they started (667), and
   threads declined from 25 to 21. No unbounded growth was observed.
36. **Resolution/DPI matrix — PASS.** Final offscreen walkthroughs passed with
   zero failures/partials at 1024x768@100%, 1600x900@125%,
   1920x1080@150%, 2560x1440@175%, and 3840x2160@200%. Physical mixed-DPI
   monitor movement, dynamic scaling, Windows 10, RDP, printer hardware, and
   touchscreen remain **NOT TESTED** and are not claimed.
37. **Antigravity independent review — PASS.** Antigravity IDE received the exact
   required prompt and produced a 22-item audit. Each alleged Critical/High was
   checked against current code and evidence. Follow-up hardening now declares
   both requested compatibility IDs (`1f676c76...` and Windows 10/11
   `8e0f7a12...`); top-level startup windows use logical, scrollable sizing; and
   splash event pumping excludes user input. `reports_tab.py` has an explicit
   `win32`/`darwin`/other chain; WMIC already has `CREATE_NO_WINDOW`; and the
   installed process trace found no console window. No legitimate Critical/High
   issue reproduced. Medium/theoretical suggestions remain backlog items.
38. **OpenCode independent review — NOT TESTED.** OpenCode Desktop 1.18.21 was
   found and the exact required prompt was submitted against the explicit
   repository path in a read-only session. Its free-model run remained stuck in
   `Stop`/running state without a response after extended waiting, so no OpenCode
   finding is claimed or used for the verdict.

### Deployment-environment notes

- Portal dashboard deployment to Fly remains **BLOCKED** by the absent
  `FLY_API_TOKEN` / logged-out `flyctl`. No credential was invented. This is an
  external deployment action, not a Windows desktop code failure.
- Cloud-backup RLS is deployed and a fresh backup was verified. This PC is still
  the **E2E Fresh Shop test organization**; that is retained as a test-environment
  note, not a product defect.
- Follow-up source hardening (bounded installer `taskkill`, startup window
  centering, scrollable login/wizard) was included in the 21:36 installer
  rebuild. Power/WTS session handlers are present in that same frozen PYZ (see
  Current candidate). Hibernate, Fast User Switching, and mixed-DPI were not
  re-run on hardware after that rebuild.

## Superseded preliminary run

## Certification state

This run is **not a final integrated certification**. The admin-portal and cloud-backup jobs continued changing the working tree throughout the run (new changes appeared in `supabase_client.py`, `CLOUD_BACKUP.md`, and additional portal routes). Per the concurrency requirement, no final build or install was attempted. The installed executable therefore does not contain the repairs in this report.

No genuine business rows were modified. UI matrix runs used distinct `MBT_DATA_ROOT` directories under `%TEMP%`.

## Fixes made in this run

1. Added `desktop/utils/qt_dispatch.py`, installed on the QApplication thread at startup.
2. Replaced invalid worker-thread `QTimer.singleShot(0, ...)` calls in main-window licensing/updater/Cloudflare callbacks, setup wizard, Settings, Diagnostics, and AI connectivity with queued Qt signal dispatch.
3. Added `CREATE_NO_WINDOW` to Windows WMIC hardware-fingerprint probes.
4. Replaced Windows report-folder `explorer.exe` subprocess launch with `os.startfile`.
5. Added an explicit `asInvoker`, PerMonitorV2/PerMonitor, long-path-aware application manifest and connected it to the PyInstaller GUI build.
6. Added Windows runtime regression tests.

## Subprocess launch inventory

| Location | Purpose | Visibility | UI blocking | Repetition risk | Disposition |
|---|---|---:|---:|---:|---|
| `backend/updater.py:_unblock_windows_file` | Remove download Mark-of-the-Web | Hidden | Background/update path | Once/download | `CREATE_NO_WINDOW` present |
| `backend/updater.py:is_update_helper_registered` | Query retired scheduled task | Hidden | Worker | Once/check | `CREATE_NO_WINDOW` present |
| `backend/updater.py:run_update_helper_task` | Legacy helper trigger | Hidden | Worker | Manual/legacy | `CREATE_NO_WINDOW`; helper disabled for production installs |
| `backend/updater.py:install_and_restart` | Post-exit install/UAC/restart | Hidden launcher; UAC and installer intentionally visible | After app exits | Once/update | `cmd /c` uses `CREATE_NO_WINDOW`; UAC retained intentionally |
| `licensing/license_engine.py:_collect_hardware_probe_parts` | Legacy WMIC fingerprint compatibility | Hidden | License initialization | Up to 3 probes/start | **Fixed:** `CREATE_NO_WINDOW` |
| `backend/cloudflare_setup.py` | DNS tools, service/process control, tunnel | Hidden except explicit elevation repair | Background workers | Startup/retry/manual | Central no-window flags already used for normal launches; `ShellExecuteW runas` intentionally visible |
| `web_launcher.py` | Web service and cloudflared helper | Hidden | Background | Startup + monitor | Existing `CREATE_NO_WINDOW`/hidden startup |
| `desktop/tabs/reports_tab.py:_open_folder` | Open export folder | Explorer GUI | User click | One/click | **Fixed:** `os.startfile`, no console process |
| `web/web_routes.py` | Admin-triggered command path | Captured | Request worker | User/admin action | Not desktop startup; review retained |
| `installer.nsi` | taskkill, backup, ACL, license repair, helper cleanup | Installer details/UI | Installer-only | Once/install | `nsExec::ExecToLog`; no transient console |
| `deploy/*.ps1`, `*.bat`, `scripts/*`, `WEB_DIAGNOSTICS.py` | Build/deploy/QA/operator tools | Operator console or explicitly hidden | Outside installed desktop runtime | Operator initiated | Not runtime startup launch points |

PyInstaller: `console=False`; executable type is GUI/windowed. Shortcuts point directly to `MBT_POS.exe`. No MBT-specific AppCompat Layers override was present in HKCU or HKLM.

## Timer inventory

Repeating production Qt timers:

| Location | Interval | Callback/purpose | Hidden behavior / overlap |
|---|---:|---|---|
| `desktop/main.py` | 1000 ms | clock `_tick` | Label update only |
| `desktop/main.py` | 15000 ms | idle-session check | Constant time; no subprocess/DB |
| `desktop/main.py` | 15000 ms | unattended update idle gate | Starts only after verified download; guarded against overlap |
| `desktop/tabs/dashboard_tab.py` | 60000 ms | dashboard refresh | Page-owned |
| `desktop/tabs/diagnostics_tab.py` | 30000 ms | diagnostics refresh | Page-owned; potential DB/health reads |
| `desktop/tabs/notes_tab.py` | 900 ms single-shot/debounce | autosave | Page-owned |
| `desktop/tabs/notes_tab.py` | 2200 ms single-shot | feedback clear | UI-only |
| `desktop/utils/select_controls.py` | 80 ms single-shot | filter debounce | UI-only |
| `desktop/pos/layouts/splitters.py` | 90/700 ms single-shot | relayout/settings persistence debounce | Save is worker-threaded |
| `desktop/tabs/sales_tab.py` | 80/100/120 ms single-shot | resize/filter/layout debounce | No repeating overlap |
| `desktop/utils/ui_polish.py` | 33 ms, 14 ticks | numeric animation | Stops at completion |
| `desktop/utils/charts.py` | 33 ms | chart reveal | Stops at 100%; skipped offscreen |
| `desktop/utils/splash.py` | 80 ms | splash dots | Splash-owned |
| `desktop/utils/quiet_ui.py` | 16 ms | QA top-level tracer | Installed only when `MBT_QA_TOPLEVEL_DEBUG=1`; regression test enforces off in production |

No repeating desktop timer directly launches a subprocess. Single-shot startup timers stage first paint, service startup, connectivity, update restore, and lazy tab warming.

## UI-thread audit

Confirmed defect: `QTimer.singleShot` called from plain Python worker threads queues against a thread with no Qt event loop; callbacks may never run and were being used for Qt widget mutation. Repaired locations use a `QObject` created on the QApplication thread and a `Qt.QueuedConnection`. Test `test_worker_callback_is_delivered_on_qt_thread` proves delivery on `APP.thread()`.

Existing safe patterns retained:

- Reports uses `pyqtSignal` for worker completion.
- Cloud backup panel uses QObject signals.
- AI workers use QThread signals.
- Main connectivity/updater state enters through `AppSignals`.

Signal connections in `MainWindow` are made once during construction. Lazy-tab connections are guarded by one-time tab creation. No confirmed duplicate connection was reproduced.

## Flicker findings

Prior evidence in `app.log` shows POS children temporarily becoming parentless during layout rebuilding (`CategoryChipBar`, `CustomerSelector`, `QDateEdit`, labels and container widgets). That creates native top-level windows for a frame and explains millisecond centered flashes. Current source contains:

- safe parking/reparent helpers;
- a pre-paint Show event guard for accidental parentless widgets;
- lazy tab construction to prevent whole-window startup repolish;
- scoped/deferred theme updates rather than synchronous rebuilding of every tab;
- single-shot resize/filter debouncing.

Offscreen walkthroughs reported zero failures, but offscreen capture cannot certify physical compositor flicker. The currently installed build also showed abnormally high CPU usage and predates this run's fixes, so installed flicker acceptance remains open.

## DPI and manifest

- PyQt: 5.15.11
- Qt runtime: 5.15.2
- Qt high-DPI attributes are set before `QApplication`.
- New source manifest: `asInvoker`, `PerMonitorV2,PerMonitor`, Win10+ supported-OS GUID, long paths, Common Controls v6.
- Installed EXE manifest was extracted from RT_MANIFEST. It is `asInvoker` and long-path-aware but has **no dpiAware/dpiAwareness declaration**. This is fixed in source but not installed.
- No MBT-specific compatibility override was found.

## UI matrix (emulated/offscreen, not physical monitor testing)

Evidence roots contain `results.json`, walkthrough logs, and control inventories. The 1024x768 run also contains rendered screenshots; high-scale runs completed their control/dialog assertions but Qt's offscreen backend did not emit PNG files, so their result is automation evidence rather than visual screenshot evidence.

| Matrix | Result | Evidence |
|---|---|---|
| 1024x768 @ 100% | PASS | `matrix/1024x768-100/` |
| 1600x900 @ 125% | PASS | `matrix/1600x900-125/` |
| 1920x1080 @ 150% | PASS | `matrix/1920x1080-150/` |
| 2560x1440 @ 175% | PASS | `matrix/2560x1440-175/` |
| 3840x2160 @ 200% | PASS | `matrix/3840x2160-200/` |

Each walkthrough rendered login and all 14 navigation destinations, Finance subpages, Sales, Inventory, Reports, Settings, Security, License and Diagnostics; opened return/void/receive-stock/supplier/add-product/global-search dialogs; toggled themes and sales focus mode; and checked settings persistence in the isolated root.

Not physically tested: mixed-DPI monitor move, dynamic Windows scale change, RDP, Windows 10 host, reboot, printer hardware, or physical touchscreen.

## Automated tests

- Targeted Windows/runtime set: 33 passed.
- Full repository suite: **378 passed in 63.47s**.
- Python compileall: passed.
- `git diff --check`: passed (only existing LF/CRLF notices).

## Installed executable observation

Path: `C:\Program Files\MugoByte\MBT POS\MBT_POS.exe`  
Version: 3.0.75.0  
SHA-256: `D7D4BA356A2748690EA62A145905FA0FA5D9C7F406C41391305726D5B458E9A8`  
Observed process: PID 19088, 23-25 threads, 699-716 handles, about 190 MiB working set.  
Child process: one expected `cloudflared.exe`.

The installed app consumed roughly 1.4 CPU seconds per 2 wall-clock seconds during the sample, which is abnormally high for an idle POS and is a release blocker until reproduced/profiled on the final integrated build. The installed binary predates the current source edits and is not the certification candidate.

## Independent reviewers

Neither `opencode` nor `antigravity` was available through `Get-Command`; both reviews are NOT TESTED. No substitute reviewer was used.

## Required final integration rerun

After concurrent portal/cloud edits stop:

1. rerun the full suite and web build/tests;
2. build PyInstaller/NSIS 3.0.75;
3. extract the built manifest and verify PerMonitorV2;
4. snapshot live DB/config/license hashes;
5. install elevated;
6. run the installed Program Files EXE through process-popup tracing, sustained idle CPU/resource sampling, physical visual checks, and isolated Adjust Stock/sale/void/persistence acceptance;
7. run available independent reviewers;
8. certify the exact final EXE hash and commit.
