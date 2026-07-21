; MBT POS - NSIS Installer Script
; MugoByte Technologies | mugobyte.com
; Builds a professional Windows installer from dist\MBT_POS\
;
; Installation modes (automatic — user never chooses):
;   NEW     — no existing MBT_POS.exe → install files → first launch runs Setup Wizard
;   UPGRADE — existing install found → backup AppData DB → update files → preserve
;             settings/license (AppData) → launch POS (wizard skipped)

;=============================================================================
; General Settings
;=============================================================================
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

; Finish — launch POS (wizard runs only on new installs via needs_wizard())
!define MUI_FINISHPAGE_RUN "$INSTDIR\MBT_POS.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch MBT POS"
!define MUI_FINISHPAGE_LINK "Download Center · portal.mugobyte.com"
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
VIProductVersion "3.0.0.0"
VIAddVersionKey "ProductName"     "MBT POS"
VIAddVersionKey "CompanyName"     "MugoByte Technologies"
VIAddVersionKey "LegalCopyright"  "© 2026 MugoByte Technologies"
VIAddVersionKey "FileDescription" "MBT POS Installer — auto new/upgrade"
VIAddVersionKey "FileVersion"     "3.0.0"
VIAddVersionKey "ProductVersion"  "3.0.0"

;=============================================================================
; Installer Sections
;=============================================================================
Section "MBT POS" SecMain
    SectionIn RO

    DetailPrint "Install mode: $InstallMode"

    ; UPGRADE: back up the real runtime paths before replacing binaries.
    ${If} $IsUpgrade == "1"
        DetailPrint "Upgrade detected — backing up database…"
        CreateDirectory "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\3.0.0"
        CreateDirectory "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\3.0.0\config"
        CreateDirectory "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\3.0.0\license"
        nsExec::ExecToLog 'cmd /C if exist "$LOCALAPPDATA\MugoByte\MBT POS\data\mbt_pos.db" copy /Y "$LOCALAPPDATA\MugoByte\MBT POS\data\mbt_pos.db" "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\3.0.0\mbt_pos.db"'
        nsExec::ExecToLog 'cmd /C if exist "$LOCALAPPDATA\MugoByte\MBT POS\data\mbt_pos.db-wal" copy /Y "$LOCALAPPDATA\MugoByte\MBT POS\data\mbt_pos.db-wal" "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\3.0.0\mbt_pos.db-wal"'
        nsExec::ExecToLog 'cmd /C if exist "$LOCALAPPDATA\MugoByte\MBT POS\data\mbt_pos.db-shm" copy /Y "$LOCALAPPDATA\MugoByte\MBT POS\data\mbt_pos.db-shm" "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\3.0.0\mbt_pos.db-shm"'
        nsExec::ExecToLog 'cmd /C if exist "$LOCALAPPDATA\MugoByte\MBT POS\config\*" xcopy /E /I /Y "$LOCALAPPDATA\MugoByte\MBT POS\config" "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\3.0.0\config"'
        nsExec::ExecToLog 'cmd /C if exist "$APPDATA\MugoByte\.mbt_lic\lc.db" copy /Y "$APPDATA\MugoByte\.mbt_lic\lc.db" "$LOCALAPPDATA\MugoByte\MBT POS\backups\pre_upgrade\3.0.0\license\lc.db"'
        DetailPrint "Database, settings, and encrypted license backup complete."
    ${Else}
        DetailPrint "New installation — Setup Wizard will run on first launch."
    ${EndIf}

    SetOutPath "$INSTDIR"
    SetOverwrite on

    ; Onedir build: MBT_POS.exe + python311.dll + libs
    File /r "dist\MBT_POS\*.*"

    ; Record install mode for support / diagnostics
    CreateDirectory "$LOCALAPPDATA\MugoByte\MBT POS"
    FileOpen $1 "$LOCALAPPDATA\MugoByte\MBT POS\last_install_mode.txt" w
    FileWrite $1 "$InstallMode$\r$\n"
    FileWrite $1 "version=3.0.0$\r$\n"
    FileClose $1

    WriteRegStr HKLM "Software\MugoByte\MBT POS" "InstallDir" "$INSTDIR"
    WriteRegStr HKLM "Software\MugoByte\MBT POS" "Version"    "3.0.0"
    WriteRegStr HKLM "Software\MugoByte\MBT POS" "InstallMode" "$InstallMode"

    CreateDirectory "$SMPROGRAMS\MugoByte\MBT POS"
    CreateShortcut  "$SMPROGRAMS\MugoByte\MBT POS\MBT POS.lnk" \
                    "$INSTDIR\MBT_POS.exe" "" "$INSTDIR\MBT_POS.exe" 0 \
                    SW_SHOWNORMAL "" "MBT POS — Professional Point of Sale System"
    CreateShortcut  "$SMPROGRAMS\MugoByte\MBT POS\Uninstall MBT POS.lnk" \
                    "$INSTDIR\Uninstall.exe"
    CreateShortcut  "$SMPROGRAMS\MugoByte\MBT POS\MugoByte Workspace.lnk" \
                    "https://portal.mugobyte.com" "" "$INSTDIR\MBT_POS.exe" 0 \
                    SW_SHOWNORMAL "" "MugoByte Workspace — downloads, licenses, devices"

    CreateShortcut "$DESKTOP\MBT POS.lnk" \
                   "$INSTDIR\MBT_POS.exe" "" "$INSTDIR\MBT_POS.exe" 0 \
                   SW_SHOWNORMAL "" "MBT POS"

    WriteRegStr HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "DisplayName"          "MBT POS"
    WriteRegStr HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "DisplayVersion"       "3.0.0"
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
; Uninstaller — AppData (sales, license, settings) left intact
;=============================================================================
Section "Uninstall"
    ExecWait 'taskkill /F /IM MBT_POS.exe' $0
    ExecWait 'taskkill /F /IM cloudflared.exe' $0

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
