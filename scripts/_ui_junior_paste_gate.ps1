$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class UA2 {
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
  if (-not $p) { throw 'NO_CHATGPT_WINDOW' }
  [UA2]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
  [UA2]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
  Start-Sleep -Milliseconds 200
  return $p
}
function Click-At([int]$x, [int]$y) {
  [UA2]::SetCursorPos($x, $y) | Out-Null
  Start-Sleep -Milliseconds 60
  [UA2]::mouse_event([UA2]::D,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 40
  [UA2]::mouse_event([UA2]::U,0,0,0,[UIntPtr]::Zero)
}

$root = 'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos'
$up = Join-Path $root '_qa_full_system_polish\desktop_iter21\chatgpt_upload'
$imgs = Get-ChildItem $up -Filter 'pick_*.jpg' | Sort-Object LastWriteTime -Descending | Select-Object -First 3
if ($imgs.Count -lt 3) {
  # fallback prepare via existing stamped files
  $imgs = Get-ChildItem $up -Filter '*.jpg' | Sort-Object LastWriteTime -Descending | Select-Object -First 3
}
Write-Host "using files:"
$imgs | ForEach-Object { Write-Host $_.FullName }

$p = Focus-ChatGPT
$r = New-Object UA2+RECT
[UA2]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
Write-Host "win $($r.L),$($r.T) $($r.R),$($r.B)"

# Go new chat
[System.Windows.Forms.SendKeys]::SendWait('^l')
Start-Sleep -Milliseconds 200
Set-Clipboard 'https://chatgpt.com/'
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 80
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Start-Sleep -Seconds 4

$p = Focus-ChatGPT
[UA2]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
# Composer is near bottom center; + is left of it
$cx = [int](($r.L + $r.R) / 2)
$cy = [int]($r.B - 150)
Click-At $cx $cy
Start-Sleep -Milliseconds 400

# Paste images one-by-one as clipboard bitmaps (more reliable once focused)
foreach ($img in ($imgs | Sort-Object Name)) {
  $image = [System.Drawing.Image]::FromFile($img.FullName)
  [System.Windows.Forms.Clipboard]::SetImage($image)
  $image.Dispose()
  Focus-ChatGPT | Out-Null
  Click-At $cx $cy
  Start-Sleep -Milliseconds 200
  [System.Windows.Forms.SendKeys]::SendWait('^v')
  Write-Host "pasted $($img.Name)"
  Start-Sleep -Seconds 2.5
}

Start-Sleep -Seconds 1
$prompt = Get-Content -Raw -Encoding UTF8 (Join-Path $root '_qa_full_system_polish\desktop_iter21\_gate_prompt.txt')
if (-not $prompt) {
  $prompt = @"
Rate MBT POS checkout layouts in order: 1 Checkout Pro, 2 Product Explorer, 3 Retail Classic.
Respond EXACTLY:
CHECKOUT_PRO: <0-100>%
PRODUCT_EXPLORER: <0-100>%
RETAIL_CLASSIC: <0-100>%
OVERALL_CHECKOUT: <0-100>%
Be strict. 98%=ship-ready.
"@
}
Focus-ChatGPT | Out-Null
Click-At $cx $cy
Set-Clipboard $prompt
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 700
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Write-Host 'SENT'
Start-Sleep -Seconds 5

# Screenshot after send
$p = Focus-ChatGPT
[UA2]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object Drawing.Bitmap (($r.R-$r.L), ($r.B-$r.T))
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$shot = Join-Path $root '_qa_full_system_polish\desktop_iter21\chatgpt_ui_after_send.png'
$bmp.Save($shot)
$g.Dispose(); $bmp.Dispose()
Write-Host "SHOT $shot"
