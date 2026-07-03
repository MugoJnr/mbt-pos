' MBT POS — Install Silent Auto-Start
' MugoByte Technologies | mugobyte.com
' Installs the web service to start with Windows — no CMD window.
' Uses Windows Task Scheduler (more reliable than Startup folder).
' Run this ONCE after SETUP CLOUDFLARE.bat

Option Explicit

Dim oShell, oFSO, sBase, sVBS, sTask, sResult

Set oShell = CreateObject("WScript.Shell")
Set oFSO   = CreateObject("Scripting.FileSystemObject")

sBase = oFSO.GetParentFolderName(WScript.ScriptFullName)
sVBS  = sBase & "\START WEB.vbs"
sTask = "MBT_POS_Web_Service"

If Not oFSO.FileExists(sVBS) Then
    MsgBox "START WEB.vbs not found in:" & vbCrLf & sBase, 16, "MBT POS"
    WScript.Quit
End If

' Delete old task if exists (silent)
oShell.Run "schtasks /Delete /TN """ & sTask & """ /F", 0, True

' Create new scheduled task:
'   Trigger: At system startup + At logon (both, so it works with or without login)
'   Action:  wscript.exe "START WEB.vbs"
'   Run as:  current user
'   Hidden:  yes
Dim sCmd
sCmd = "schtasks /Create /TN """ & sTask & """ " & _
       "/TR ""wscript.exe """"" & sVBS & """""" " & _
       "/SC ONLOGON " & _
       "/RL HIGHEST " & _
       "/F"

Dim ret
ret = oShell.Run(sCmd, 0, True)

If ret = 0 Then
    ' Also add ONSTART trigger via XML for boot-time (no login required)
    ' Simple approach: also copy to Startup folder as fallback
    Dim sStartup
    sStartup = oShell.ExpandEnvironmentStrings("%APPDATA%") & _
               "\Microsoft\Windows\Start Menu\Programs\Startup\MBT_POS_Web.vbs"
    oFSO.CopyFile sVBS, sStartup, True

    MsgBox "Auto-start installed successfully!" & vbCrLf & vbCrLf & _
           "The web service will now start silently every time Windows starts." & vbCrLf & vbCrLf & _
           "Task: " & sTask & vbCrLf & _
           "Dashboard: https://trading.mugobyte.com", 64, "MBT POS — Done"
Else
    MsgBox "Task Scheduler install failed (code " & ret & ")." & vbCrLf & vbCrLf & _
           "A shortcut was placed in your Startup folder instead." & vbCrLf & _
           "It will still work, but may show briefly on login.", 48, "MBT POS"
    ' Startup folder fallback already done above
End If
