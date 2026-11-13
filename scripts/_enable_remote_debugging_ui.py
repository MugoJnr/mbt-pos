"""Enable chrome://inspect/#remote-debugging on the Junior ChatGPT window via UI, then verify CDP."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]


def ps(script: str) -> str:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return (r.stdout or "") + (r.stderr or "")


def main():
    # Focus Junior ChatGPT window and navigate to remote-debugging page
    out = ps(
        r"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W2 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
}
"@
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'ChatGPT' } | Select-Object -First 1
if (-not $p) { 'NO_WINDOW'; return }
[W2]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
[W2]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 400
# Ctrl+L focus omnibox
[W2]::keybd_event(0x11,0,0,[UIntPtr]::Zero) # ctrl down
[W2]::keybd_event(0x4C,0,0,[UIntPtr]::Zero) # L
[W2]::keybd_event(0x4C,0,2,[UIntPtr]::Zero)
[W2]::keybd_event(0x11,0,2,[UIntPtr]::Zero)
Start-Sleep -Milliseconds 300
# Type URL via clipboard paste for reliability
Set-Clipboard 'chrome://inspect/#remote-debugging'
Start-Sleep -Milliseconds 200
[W2]::keybd_event(0x11,0,0,[UIntPtr]::Zero)
[W2]::keybd_event(0x56,0,0,[UIntPtr]::Zero) # V
[W2]::keybd_event(0x56,0,2,[UIntPtr]::Zero)
[W2]::keybd_event(0x11,0,2,[UIntPtr]::Zero)
Start-Sleep -Milliseconds 200
[W2]::keybd_event(0x0D,0,0,[UIntPtr]::Zero) # Enter
[W2]::keybd_event(0x0D,0,2,[UIntPtr]::Zero)
'NAV_OK title=' + $p.MainWindowTitle
"""
    )
    print(out)
    time.sleep(3)
    # Screenshot
    ps(
        r"""
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W3 {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  public struct RECT { public int L,T,R,B; }
}
"@
$p = Get-Process chrome | Where-Object MainWindowTitle | Select-Object -First 1
[W3]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
$r = New-Object W3+RECT
[W3]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$w=$r.R-$r.L; $h=$r.B-$r.T
$bmp=New-Object Drawing.Bitmap $w,$h
$g=[Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L,$r.T,0,0,$bmp.Size)
$bmp.Save('"""
        + str(ROOT / "_qa_full_system_polish/desktop_iter21/remote_debugging_page.png").replace("\\", "/")
        + r"""')
$g.Dispose(); $bmp.Dispose()
$p.MainWindowTitle
"""
    )
    print("titles:")
    print(ps("(Get-Process chrome | Where-Object MainWindowTitle | Select-Object Id,MainWindowTitle | Format-Table | Out-String)"))
    # Probe if 9222 already up from eugene or inspect
    try:
        v = requests.get("http://127.0.0.1:9222/json/version", timeout=2).json()
        print("CDP_ALREADY", v.get("Browser"))
    except Exception as e:
        print("NO_CDP_YET", e)


if __name__ == "__main__":
    main()
