' MBT POS — Silent Web Service Launcher
' MugoByte Technologies | mugobyte.com
' Launches web_launcher.py with ZERO visible windows.
' Double-click this file — nothing appears on screen.
' Everything runs in background. Check logs\ folder for activity.

Option Explicit

Dim oShell, oFSO, sBase, sPython, sScript, sLog, sTS

Set oShell = CreateObject("WScript.Shell")
Set oFSO   = CreateObject("Scripting.FileSystemObject")

' Get the folder this .vbs file is in
sBase = oFSO.GetParentFolderName(WScript.ScriptFullName)

' Find Python — check common locations
Dim aCandidates(7)
aCandidates(0) = "C:\MBT_Build\_python311\python.exe"
aCandidates(1) = sBase & "\python311\python.exe"
aCandidates(1) = sBase & "\python\python.exe"
aCandidates(2) = "C:\Python311\python.exe"
aCandidates(3) = "C:\Python312\python.exe"
aCandidates(4) = "C:\Python310\python.exe"
aCandidates(5) = "C:\Users\" & oShell.ExpandEnvironmentStrings("%USERNAME%") & "\AppData\Local\Programs\Python\Python311\python.exe"
aCandidates(6) = "C:\Users\" & oShell.ExpandEnvironmentStrings("%USERNAME%") & "\AppData\Local\Programs\Python\Python312\python.exe"

sPython = ""
Dim i
For i = 0 To 7
    If oFSO.FileExists(aCandidates(i)) Then
        sPython = aCandidates(i)
        Exit For
    End If
Next

' Fallback: use PATH python (still invisible via wscript)
If sPython = "" Then
    sPython = "python"
End If

sScript = sBase & "\web_launcher.py"
sLog    = sBase & "\logs\web_launcher.log"

' Ensure logs directory exists
If Not oFSO.FolderExists(sBase & "\logs") Then
    oFSO.CreateFolder(sBase & "\logs")
End If

' Write startup entry to log
sTS = Now()
Dim oLog
Set oLog = oFSO.OpenTextFile(sLog, 8, True)  ' 8 = append
oLog.WriteLine "[" & sTS & "] VBS launcher: starting web_launcher.py"
oLog.Close

' Run Python completely silently
' 0 = hide window, False = don't wait for completion
oShell.Run """" & sPython & """ """ & sScript & """", 0, False

' Script exits immediately — Python continues in background
' No window, no prompt, no sound
