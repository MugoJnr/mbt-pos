' Start Cloudflare tunnel silently (no CMD window)
Option Explicit
Dim sh, base, cf, cfg
Set sh = CreateObject("WScript.Shell")
base = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
cf = base & "\cloudflared.exe"
cfg = sh.ExpandEnvironmentStrings("%USERPROFILE%") & "\.cloudflared\config.yml"
If Not CreateObject("Scripting.FileSystemObject").FileExists(cf) Then WScript.Quit 1
sh.Run """" & cf & """ tunnel --config """ & cfg & """ run", 0, False
