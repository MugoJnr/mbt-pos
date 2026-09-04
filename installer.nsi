; MBT POS - NSIS Installer Script
; MugoByte Technologies | mugobyte.com
; Builds a professional Windows installer from dist\MBT_POS\
;
; Installation modes (automatic - user never chooses):
;   NEW     - no existing MBT_POS.exe -> install files -> first launch runs Setup Wizard
;   UPGRADE - existing install found -> backup AppData DB -> update files -> preserve
;             settings/license (AppData) -> launch POS (wizard skipped)

;=============================================================================
; General Settings
;=============================================================================
!define APP_VERSION "3.0.83"
!define APP_VERSION_QUAD "3.0.83.0"
Unicode True
Name "MBT POS"
OutFile "dist\MBT_POS_Setup.exe"
InstallDir "$PROGRAMFILES64\MugoByte\MBT POS"
InstallDirRegKey HKLM "Software\MugoByte\MBT POS" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
BrandingText "MugoByte Technologies | mugobyte.com"

Var IsUpgrade
Var InstallMode
Var LicenseMachineDir

;=============================================================================
; Modern UI
;=============================================================================
!include "MUI2.nsh"
!include "WinVer.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

; Soft install: skip abort confirmation MessageBox
;!define MUI_ABORTWARNING
!define MUI_ICON "assets\mbt_icon.ico"
!define MUI_UNICON "assets\mbt_icon.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP_NOSTRETCH

!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP_NOSTRETCH

; Do not launch from the elevated installer. If UAC used alternate admin
; credentials, that would create shop data under the administrator profile.
; The user starts MBT POS normally from the machine-wide shortcut after Finish.
!define MUI_FINISHPAGE_LINK "Download Center - portal.mugobyte.com"
!define MUI_FINISHPAGE_LINK_LOCATION "https://portal.mugobyte.com/downloads"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; Detect new vs upgrade automatically
Function .onInit
    FileOpen $9 "$TEMP\mbt_pos_installer_trace.log" w
    FileWrite $9 "start version=${APP_VERSION}$\r$\n"
    FileClose $9
    ; 64-bit registry view for Program Files (x64) installs
    ${If} ${RunningX64}
        SetRegView 64
    ${EndIf}

    StrCpy $IsUpgrade "0"
    StrCpy $InstallMode "new"

    ; Prefer registry install path when present
    ReadRegStr $0 HKLM "Software\MugoByte\MBT POS" "InstallDir"
    ${If} $0 != ""
        ${If} ${FileExists} "$0\MBT_POS.exe"
            StrCpy $INSTDIR $0
            StrCpy $IsUpgrade "1"
            StrCpy $InstallMode "upgrade"
        ${EndIf}
    ${EndIf}

    ${If} $IsUpgrade == "0"
        ${If} ${FileExists} "$INSTDIR\MBT_POS.exe"
            StrCpy $IsUpgrade "1"
            StrCpy $InstallMode "upgrade"
        ${EndIf}
    ${EndIf}

    ; Bound process shutdown so installer startup cannot hang indefinitely.
    ; taskkill waits for termination; nsExec forcibly returns after five seconds.
    nsExec::ExecToLog /TIMEOUT=5000 'taskkill /F /T /IM MBT_POS.exe'
    nsExec::ExecToLog /TIMEOUT=5000 'taskkill /F /T /IM cloudflared.exe'
    Sleep 500
    FileOpen $9 "$TEMP\mbt_pos_installer_trace.log" a
    FileWrite $9 "init_complete mode=$InstallMode dir=$INSTDIR$\r$\n"
    FileClose $9
FunctionEnd

;=============================================================================
; Version Info
;=============================================================================
VIProductVersion "${APP_VERSION_QUAD}"
VIAddVersionKey "ProductName"     "MBT POS"
VIAddVersionKey "CompanyName"     "MugoByte Technologies"
VIAddVersionKey "LegalCopyright"  "(c) 2026 MugoByte Technologies"
VIAddVersionKey "FileDescription" "MBT POS Installer - auto new/upgrade"
VIAddVersionKey "FileVersion"     "${APP_VERSION}"
VIAddVersionKey "ProductVersion"  "${APP_VERSION}"

;=============================================================================
; Installer Sections
;=============================================================================
Section "MBT POS" SecMain
    SectionIn RO
    FileOpen $9 "$TEMP\mbt_pos_installer_trace.log" a
    FileWrite $9 "section_start$\r$\n"
    FileClose $9

    ReadEnvStr $LicenseMachineDir "PROGRAMDATA"
    ${If} $LicenseMachineDir == ""
        StrCpy $LicenseMachineDir "$WINDIR\..\ProgramData"
    ${EndIf}
    StrCpy $LicenseMachineDir "$LicenseMachineDir\MugoByte\MBT POS\license"

    DetailPrint "Install mode: $InstallMode"

    ; UPGRADE: back up the real runtime paths before replacing binaries.
    ${If} $IsUpgrade == "1"
        DetailPrint "Upgrade detected - backing up all MBT POS user profiles..."
        SetOutPath "$PLUGINSDIR"
        File /oname=Backup-MBTUserData.ps1 "deploy\Backup-MBTUserData.ps1"
        nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\Backup-MBTUserData.ps1" -Version "${APP_VERSION}"'
        DetailPrint "Database, settings, and encrypted license backups complete."
    ${Else}
        DetailPrint "New installation - Setup Wizard will run on first launch."
    ${EndIf}

    ; Replace the frozen runtime as a unit. Overlay-only upgrades leave removed
    ; modules and build-variant markers behind; in particular, an EDMUS offline
    ; marker would otherwise keep disabling production licensing indefinitely.
    Delete "$INSTDIR\MBT_POS.exe"
    Delete "$INSTDIR\EDMUS_OFFLINE_BUILD.flag"
    Delete "$INSTDIR\MBT_UpdateHelper.ps1"
    Delete "$INSTDIR\register_update_helper.ps1"
    RMDir /r "$INSTDIR\deploy"
    RMDir /r "$INSTDIR\_internal"
    FileOpen $9 "$TEMP\mbt_pos_installer_trace.log" a
    FileWrite $9 "old_runtime_removed$\r$\n"
    FileClose $9

    SetOutPath "$INSTDIR"
    SetOverwrite on

    ; Onedir build: MBT_POS.exe + python311.dll + libs
    File /r "dist\MBT_POS\*.*"
    FileOpen $9 "$TEMP\mbt_pos_installer_trace.log" a
    FileWrite $9 "new_runtime_copied$\r$\n"
    FileClose $9

    ; License is machine-scoped. Older releases stored it under whichever
    ; Windows profile performed activation, including alternate UAC admins.
    CreateDirectory "$LicenseMachineDir"
    nsExec::ExecToLog 'icacls "$LicenseMachineDir" /grant *S-1-5-32-545:(OI)(CI)M /T /C /Q'
    DetailPrint "Recovering any existing per-user activation..."
    nsExec::ExecToLog '"$INSTDIR\MBT_POS.exe" --repair-license-store'

    ; Record install mode for support / diagnostics
    CreateDirectory "$LOCALAPPDATA\MugoByte\MBT POS"
    CreateDirectory "$LOCALAPPDATA\MugoByte\MBT POS\updates"
    FileOpen $1 "$LOCALAPPDATA\MugoByte\MBT POS\last_install_mode.txt" w
    FileWrite $1 "$InstallMode$\r$\n"
    FileWrite $1 "version=${APP_VERSION}$\r$\n"
    FileClose $1

    ; Keep LocalAppData version stamp aligned with the installed binary.
    FileOpen $1 "$LOCALAPPDATA\MugoByte\MBT POS\installed_version.json" w
    FileWrite $1 '{"version":"${APP_VERSION}","build":"${APP_VERSION}","path":"$INSTDIR\MBT_POS.exe","released":"2026-09-04"}$\r$\n'
    FileClose $1

    ; MBT POS only ever installs into $PROGRAMFILES64, so the native 64-bit
    ; view is the single source of truth. A 3.0.3-era 32-bit installer left
    ; orphaned copies under WOW6432Node that nothing has refreshed since, so
    ; 32-bit inventory and software-audit tools kept reporting 3.0.3. Delete
    ; them rather than mirroring the values: a mirror would list the product
    ; twice in inventories and give the uninstaller two entries to keep in
    ; step. /ifempty protects any sibling MugoByte product under the vendor key.
    ${If} ${RunningX64}
        SetRegView 32
        DeleteRegKey HKLM "Software\MugoByte\MBT POS"
        DeleteRegKey /ifempty HKLM "Software\MugoByte"
        DeleteRegKey HKLM \
            "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS"
        SetRegView 64
        DetailPrint "Cleared stale 32-bit (WOW6432Node) registry entries."
    ${EndIf}

    WriteRegStr HKLM "Software\MugoByte\MBT POS" "InstallDir" "$INSTDIR"
    WriteRegStr HKLM "Software\MugoByte\MBT POS" "Version"    "${APP_VERSION}"
    WriteRegStr HKLM "Software\MugoByte\MBT POS" "InstallMode" "$InstallMode"

    ; Remove the legacy SYSTEM helper. Its handoff was user-writable, so a local
    ; user could substitute an installer. Updates now use verified download +
    ; an explicit Windows UAC prompt.
    DetailPrint "Removing legacy silent update helper task..."
    nsExec::ExecToLog 'schtasks /Delete /TN "MBT_POS_UpdateHelper" /F'

    SetShellVarContext all
    CreateDirectory "$SMPROGRAMS\MugoByte\MBT POS"
    CreateShortcut  "$SMPROGRAMS\MugoByte\MBT POS\MBT POS.lnk" \
                    "$INSTDIR\MBT_POS.exe" "" "$INSTDIR\MBT_POS.exe" 0 \
                    SW_SHOWNORMAL "" "MBT POS - Professional Point of Sale System"
    CreateShortcut  "$SMPROGRAMS\MugoByte\MBT POS\Uninstall MBT POS.lnk" \
                    "$INSTDIR\Uninstall.exe"
    CreateShortcut  "$SMPROGRAMS\MugoByte\MBT POS\MugoByte Workspace.lnk" \
                    "https://portal.mugobyte.com" "" "$INSTDIR\MBT_POS.exe" 0 \
                    SW_SHOWNORMAL "" "MugoByte Workspace - downloads, licenses, devices"

    CreateShortcut "$DESKTOP\MBT POS.lnk" \
                   "$INSTDIR\MBT_POS.exe" "" "$INSTDIR\MBT_POS.exe" 0 \
                   SW_SHOWNORMAL "" "MBT POS"

    WriteRegStr HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "DisplayName"          "MBT POS"
    WriteRegStr HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "DisplayVersion"       "${APP_VERSION}"
    WriteRegStr HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "Publisher"            "MugoByte Technologies"
    WriteRegStr HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "UninstallString"      "$INSTDIR\Uninstall.exe"
    WriteRegStr HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "DisplayIcon"          "$INSTDIR\MBT_POS.exe"
    WriteRegStr HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "InstallLocation"      "$INSTDIR"
    WriteRegStr HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "HelpLink"             "https://portal.mugobyte.com/support"
    WriteRegStr HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "URLInfoAbout"         "https://portal.mugobyte.com"
    WriteRegDWORD HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "NoModify" 1
    WriteRegDWORD HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "NoRepair"  1
    ; Measure the freeze tree instead of shipping a constant. The onedir build
    ; is far larger than the historic 80 MB figure, so Add/Remove Programs was
    ; understating the footprint by more than half.
    ClearErrors
    ${GetSize} "$INSTDIR" "/S=0K" $2 $3 $4
    ${If} ${Errors}
    ${OrIf} $2 == ""
        StrCpy $2 "80000"
    ${EndIf}
    WriteRegDWORD HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "EstimatedSize" $2

    WriteUninstaller "$INSTDIR\Uninstall.exe"
    FileOpen $9 "$TEMP\mbt_pos_installer_trace.log" a
    FileWrite $9 "section_complete$\r$\n"
    FileClose $9

SectionEnd

;=============================================================================
; Uninstaller - AppData (sales, license, settings) left intact
;=============================================================================
Section "Uninstall"
    SetShellVarContext all
    ${If} ${RunningX64}
        SetRegView 64
    ${EndIf}
    ; Release runtime files before RMDir, with a strict upper bound.
    nsExec::ExecToLog /TIMEOUT=5000 'taskkill /F /T /IM MBT_POS.exe'
    nsExec::ExecToLog /TIMEOUT=5000 'taskkill /F /T /IM cloudflared.exe'
    Sleep 500

    ; Remove elevated update helper task (data/AppData left intact)
    nsExec::ExecToLog 'schtasks /Delete /TN "MBT_POS_UpdateHelper" /F'

    RMDir /r "$INSTDIR"

    Delete "$DESKTOP\MBT POS.lnk"
    Delete "$SMPROGRAMS\MugoByte\MBT POS\MBT POS.lnk"
    Delete "$SMPROGRAMS\MugoByte\MBT POS\Uninstall MBT POS.lnk"
    Delete "$SMPROGRAMS\MugoByte\MBT POS\MugoByte Workspace.lnk"
    RMDir  "$SMPROGRAMS\MugoByte\MBT POS"
    RMDir  "$SMPROGRAMS\MugoByte"

    DeleteRegKey HKLM "Software\MugoByte\MBT POS"
    DeleteRegKey /ifempty HKLM "Software\MugoByte"
    DeleteRegKey HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS"

    ; Mirror the install-time purge so an uninstall cannot leave a stale
    ; 32-bit view behind either. Only MBT POS keys are touched; /ifempty
    ; leaves the vendor key alone if another MugoByte product still uses it.
    ${If} ${RunningX64}
        SetRegView 32
        DeleteRegKey HKLM "Software\MugoByte\MBT POS"
        DeleteRegKey /ifempty HKLM "Software\MugoByte"
        DeleteRegKey HKLM \
            "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS"
        SetRegView 64
    ${EndIf}
SectionEnd

