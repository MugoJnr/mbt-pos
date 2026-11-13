$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class UA3 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  public struct RECT { public int L; public int T; public int R; public int B; }
  public const uint D=0x0002; public const uint U=0x0004;
}
"@

function Focus-ChatGPT {
  $p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'ChatGPT' } | Select-Object -First 1
  [UA3]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
  [UA3]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
  Start-Sleep -Milliseconds 250
  return $p
}
function Click-At([int]$x, [int]$y) {
  Write-Host "click $x $y"
  [UA3]::SetCursorPos($x, $y) | Out-Null
  Start-Sleep -Milliseconds 80
  [UA3]::mouse_event([UA3]::D,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 50
  [UA3]::mouse_event([UA3]::U,0,0,0,[UIntPtr]::Zero)
}

$root = 'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos'
$imgs = Get-ChildItem (Join-Path $root '_qa_full_system_polish\desktop_iter21\chatgpt_upload') -Filter 'pick_*.jpg' |
  Sort-Object LastWriteTime -Descending | Select-Object -First 3
Write-Host "files $($imgs.Count)"

$p = Focus-ChatGPT
$r = New-Object UA3+RECT
[UA3]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
Write-Host "win $($r.L),$($r.T)-$($r.R),$($r.B) size=$(($r.R-$r.L))x$(($r.B-$r.T))"

# Relative positions from screenshot analysis (sidebar ~250px, composer bottom)
# + button ~ left side of centered input pill
$plusX = $r.L + 320
$plusY = $r.B - 155
Click-At $plusX $plusY
Start-Sleep -Milliseconds 1000

# "Add photos & files" typically first menu item under +
Click-At ($plusX + 40) ($plusY - 10)
Start-Sleep -Milliseconds 300
Click-At ($plusX + 50) ($plusY + 45)
Start-Sleep -Milliseconds 1500

# Open File dialog: set filename to all three quoted paths
$joined = ($imgs | ForEach-Object { '"' + $_.FullName + '"' }) -join ' '
Write-Host "dialog $joined"
[System.Windows.Forms.SendKeys]::SendWait('%n')
Start-Sleep -Milliseconds 400
Set-Clipboard $joined
[System.Windows.Forms.SendKeys]::SendWait('^a')
Start-Sleep -Milliseconds 100
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 250
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Write-Host 'files submitted'
Start-Sleep -Seconds 6

# Screenshot to verify thumbs
$p = Focus-ChatGPT
[UA3]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object Drawing.Bitmap (($r.R-$r.L), ($r.B-$r.T))
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$shot = Join-Path $root '_qa_full_system_polish\desktop_iter21\junior_after_attach.png'
$bmp.Save($shot)
$g.Dispose(); $bmp.Dispose()
Write-Host "SHOT $shot"
