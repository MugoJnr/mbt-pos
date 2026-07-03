' MBT POS — Stop Web Service (silent)
' Kills web_launcher.py and cloudflared processes cleanly.

Option Explicit
Dim oShell
Set oShell = CreateObject("WScript.Shell")

' Kill by image name — silent, no window
oShell.Run "taskkill /F /FI ""WINDOWTITLE eq MBT*"" /T", 0, False
oShell.Run "wmic process where ""commandline like '%web_launcher%'"" delete", 0, True
oShell.Run "taskkill /F /IM cloudflared.exe /T", 0, False

MsgBox "Web service stopped.", 64, "MBT POS"
