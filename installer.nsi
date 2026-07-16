; MBT POS - NSIS Installer Script
; MugoByte Technologies | mugobyte.com
; Builds a professional Windows installer from dist\MBT_POS.exe

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

;=============================================================================
; Modern UI
;=============================================================================
!include "MUI2.nsh"
!include "WinVer.nsh"
!include "x64.nsh"

!define MUI_ABORTWARNING
!define MUI_ICON "assets\mbt_icon.ico"
!define MUI_UNICON "assets\mbt_icon.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP_NOSTRETCH

; Header colours (hex BGR for NSIS)
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP_NOSTRETCH

; Finish page — no auto-launch (update launcher restarts the app)
!define MUI_FINISHPAGE_SHOWREADME ""
!define MUI_FINISHPAGE_LINK "mugobyte.com"
!define MUI_FINISHPAGE_LINK_LOCATION "https://mugobyte.com"

; Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; Uninstaller pages
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; Kill running POS before install — prevents corrupted exe / python DLL errors
Function .onInit
    ExecWait 'taskkill /F /IM MBT_POS.exe' $0
    Sleep 3000
FunctionEnd

;=============================================================================
; Version Info (shows in file properties)
;=============================================================================
VIProductVersion "1.0.0.0"
VIAddVersionKey "ProductName"     "MBT POS"
VIAddVersionKey "CompanyName"     "MugoByte Technologies"
VIAddVersionKey "LegalCopyright"  "© 2026 MugoByte Technologies"
VIAddVersionKey "FileDescription" "MBT POS Installer"
VIAddVersionKey "FileVersion"     "1.0.0"
VIAddVersionKey "ProductVersion"  "1.0.0"

;=============================================================================
; Installer Sections
;=============================================================================
Section "MBT POS" SecMain
    SectionIn RO  ; Required section, cannot deselect

    SetOutPath "$INSTDIR"
    SetOverwrite on

    ; Onedir build: MBT_POS.exe + python311.dll + libs (reliable silent updates)
    File /r "dist\MBT_POS\*.*"

    ; Write install location to registry
    WriteRegStr HKLM "Software\MugoByte\MBT POS" "InstallDir" "$INSTDIR"
    WriteRegStr HKLM "Software\MugoByte\MBT POS" "Version"    "1.0.0"

    ; Create Start Menu shortcut
    CreateDirectory "$SMPROGRAMS\MugoByte\MBT POS"
    CreateShortcut  "$SMPROGRAMS\MugoByte\MBT POS\MBT POS.lnk" \
                    "$INSTDIR\MBT_POS.exe" "" "$INSTDIR\MBT_POS.exe" 0 \
                    SW_SHOWNORMAL "" "MBT Point of Sale System"
    CreateShortcut  "$SMPROGRAMS\MugoByte\MBT POS\Uninstall MBT POS.lnk" \
                    "$INSTDIR\Uninstall.exe"

    ; Create Desktop shortcut
    CreateShortcut "$DESKTOP\MBT POS.lnk" \
                   "$INSTDIR\MBT_POS.exe" "" "$INSTDIR\MBT_POS.exe" 0 \
                   SW_SHOWNORMAL "" "MBT Point of Sale"

    ; Write Add/Remove Programs entry
    WriteRegStr HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "DisplayName"          "MBT POS"
    WriteRegStr HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "DisplayVersion"       "2.3.23"
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
        "HelpLink"             "https://mugobyte.com"
    WriteRegStr HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "URLInfoAbout"         "https://mugobyte.com"
    WriteRegDWORD HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "NoModify" 1
    WriteRegDWORD HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "NoRepair"  1

    ; Estimated size in KB
    WriteRegDWORD HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS" \
        "EstimatedSize" 80000

    ; Write uninstaller
    WriteUninstaller "$INSTDIR\Uninstall.exe"

SectionEnd

;=============================================================================
; Uninstaller
;=============================================================================
Section "Uninstall"
    ; Kill running process first
    ExecWait 'taskkill /F /IM MBT_POS.exe' $0

    ; Remove files
    RMDir /r "$INSTDIR"

    ; Remove shortcuts
    Delete "$DESKTOP\MBT POS.lnk"
    Delete "$SMPROGRAMS\MugoByte\MBT POS\MBT POS.lnk"
    Delete "$SMPROGRAMS\MugoByte\MBT POS\Uninstall MBT POS.lnk"
    RMDir  "$SMPROGRAMS\MugoByte\MBT POS"
    RMDir  "$SMPROGRAMS\MugoByte"

    ; Remove registry entries
    DeleteRegKey HKLM "Software\MugoByte\MBT POS"
    DeleteRegKey HKLM \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\MBT POS"

    ; Note: user data in AppData\Roaming\MugoByte is left intact
    ;       so sales data is preserved if they reinstall
SectionEnd
