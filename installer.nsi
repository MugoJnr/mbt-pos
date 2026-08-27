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
!define APP_VERSION "3.0.72"
!define APP_VERSION_QUAD "3.0.72.0"
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

    ExecWait 'taskkill /F /IM MBT_POS.exe' $0
    ExecWait 'taskkill /F /IM cloudflared.exe' $0
    Sleep 2000
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

    ReadEnvStr $LicenseMachineDir "PROGRAMDATA"
    ${If} $LicenseMachineDir == ""
        StrCpy $LicenseMachineDir "$WINDIR\..\ProgramData"
    ${EndIf}
    StrCpy $LicenseMachineDir "$LicenseMachineDir\MugoByte\MBT POS\license"

    DetailPrint "Install mode: $InstallMode"

    ; UPGRADE: back up the real runtime paths before replacing binaries.
    ${If} $IsUpgrade == "1"
        DetailPrint "Upgrade detected - backing up database..."
        CreateDirectory "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\${APP_VERSION}"
        CreateDirectory "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\${APP_VERSION}\config"
        CreateDirectory "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\${APP_VERSION}\license"
        nsExec::ExecToLog 'cmd /C if exist "$LOCALAPPDATA\MugoByte\MBT POS\data\mbt_pos.db" copy /Y "$LOCALAPPDATA\MugoByte\MBT POS\data\mbt_pos.db" "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\${APP_VERSION}\mbt_pos.db"'
        nsExec::ExecToLog 'cmd /C if exist "$LOCALAPPDATA\MugoByte\MBT POS\data\mbt_pos.db-wal" copy /Y "$LOCALAPPDATA\MugoByte\MBT POS\data\mbt_pos.db-wal" "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\${APP_VERSION}\mbt_pos.db-wal"'
        nsExec::ExecToLog 'cmd /C if exist "$LOCALAPPDATA\MugoByte\MBT POS\data\mbt_pos.db-shm" copy /Y "$LOCALAPPDATA\MugoByte\MBT POS\data\mbt_pos.db-shm" "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\${APP_VERSION}\mbt_pos.db-shm"'
        nsExec::ExecToLog 'cmd /C if exist "$LOCALAPPDATA\MugoByte\MBT POS\config\*" xcopy /E /I /Y "$LOCALAPPDATA\MugoByte\MBT POS\config" "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\${APP_VERSION}\config"'
        nsExec::ExecToLog 'cmd /C if exist "$LicenseMachineDir\lc.db" copy /Y "$LicenseMachineDir\lc.db" "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\${APP_VERSION}\license\lc.db.machine"'
        nsExec::ExecToLog 'cmd /C if exist "$LOCALAPPDATA\MugoByte\.mbt_lic\lc.db" copy /Y "$LOCALAPPDATA\MugoByte\.mbt_lic\lc.db" "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\${APP_VERSION}\license\lc.db"'
        nsExec::ExecToLog 'cmd /C if exist "$APPDATA\MugoByte\.mbt_lic\lc.db" copy /Y "$APPDATA\MugoByte\.mbt_lic\lc.db" "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\${APP_VERSION}\license\lc.db.roaming"'
        DetailPrint "Database, settings, and encrypted license backup complete."
    ${Else}
        DetailPrint "New installation - Setup Wizard will run on first launch."
    ${EndIf}

    SetOutPath "$INSTDIR"
    SetOverwrite on

    ; Onedir build: MBT_POS.exe + python311.dll + libs
    File /r "dist\MBT_POS\*.*"

    ; License is machine-scoped. Older releases stored it under whichever
    ; Windows profile performed activation, including alternate UAC admins.
    CreateDirectory "$LicenseMachineDir"
    nsExec::ExecToLog 'icacls "$LicenseMachineDir" /grant *S-1-5-32-545:(OI)(CI)M /T /C /Q'
    DetailPrint "Recovering any existing per-user activation..."
    nsExec::ExecToLog '"$INSTDIR\MBT_POS.exe" --repair-license-store'

    ; Elevated unattended-update helper stored in a dedicated deploy directory
    SetOutPath "$INSTDIR\deploy"
    File "deploy\MBT_UpdateHelper.ps1"
    File "deploy\register_update_helper.ps1"
    SetOutPath "$INSTDIR"

    ; Record install mode for support / diagnostics
    CreateDirectory "$LOCALAPPDATA\MugoByte\MBT POS"
    CreateDirectory "$LOCALAPPDATA\MugoByte\MBT POS\updates"
    FileOpen $1 "$LOCALAPPDATA\MugoByte\MBT POS\last_install_mode.txt" w
    FileWrite $1 "$InstallMode$\r$\n"
    FileWrite $1 "version=${APP_VERSION}$\r$\n"
    FileClose $1

    WriteRegStr HKLM "Software\MugoByte\MBT POS" "InstallDir" "$INSTDIR"
    WriteRegStr HKLM "Software\MugoByte\MBT POS" "Version"    "${APP_VERSION}"
    WriteRegStr HKLM "Software\MugoByte\MBT POS" "InstallMode" "$InstallMode"

    ; Register on-demand elevated helper (no always-running service).
    DetailPrint "Registering silent update helper task..."
    nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\deploy\register_update_helper.ps1"'

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
    WriteRegDWORD HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "EstimatedSize" 80000

    WriteUninstaller "$INSTDIR\Uninstall.exe"

SectionEnd

;=============================================================================
; Uninstaller - AppData (sales, license, settings) left intact
;=============================================================================
Section "Uninstall"
    SetShellVarContext all
    ${If} ${RunningX64}
        SetRegView 64
    ${EndIf}
    ExecWait 'taskkill /F /IM MBT_POS.exe' $0
    ExecWait 'taskkill /F /IM cloudflared.exe' $0

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
    DeleteRegKey HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS"
SectionEnd

