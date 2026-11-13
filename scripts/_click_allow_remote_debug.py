"""Click Allow remote debugging checkbox and probe CDP ports."""
from __future__ import annotations

import subprocess
import time

import requests


def ps(cmd: str) -> str:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return (r.stdout or "") + (r.stderr or "")


CLICK = r"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Mclk {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
  public struct RECT { public int L; public int T; public int R; public int B; }
  public const uint LEFTDOWN=0x0002; public const uint LEFTUP=0x0004;
}
"@
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'Inspect' } | Select-Object -First 1
if (-not $p) { 'NO_INSPECT_WINDOW'; exit 1 }
[Mclk]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
$r = New-Object Mclk+RECT
[Mclk]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
# Try several checkbox locations
$points = @(
  @{x=280; y=230},
  @{x=255; y=245},
  @{x=270; y=260},
  @{x=300; y=220}
)
foreach ($pt in $points) {
  $x = $r.L + $pt.x
  $y = $r.T + $pt.y
  Write-Host "click $x $y"
  [Mclk]::SetCursorPos($x, $y) | Out-Null
  Start-Sleep -Milliseconds 150
  [Mclk]::mouse_event([Mclk]::LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 50
  [Mclk]::mouse_event([Mclk]::LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 400
}
'DONE'
"""


def main():
    print(ps(CLICK))
    time.sleep(2)
    shot = r"""
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class Shot2 {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  public struct RECT { public int L; public int T; public int R; public int B; }
}
"@
$p = Get-Process chrome | Where-Object MainWindowTitle | Select-Object -First 1
[Shot2]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
$r = New-Object Shot2+RECT
[Shot2]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object Drawing.Bitmap (($r.R-$r.L), ($r.B-$r.T))
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$path = 'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\_qa_full_system_polish\desktop_iter21\remote_debugging_after.png'
$bmp.Save($path)
$g.Dispose(); $bmp.Dispose()
$p.MainWindowTitle
"""
    print("title", ps(shot))
    for port in (9222, 9229, 9333, 9223):
        try:
            v = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=1).json()
            print("CDP", port, v.get("Browser"))
        except Exception:
            print("no", port)


if __name__ == "__main__":
    main()
