$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class UAG {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  public struct RECT { public int L; public int T; public int R; public int B; }
  public const uint D=0x0002; public const uint U=0x0004;
}
"@

$root = 'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos'
$imgs = Get-ChildItem (Join-Path $root '_qa_full_system_polish\desktop_iter21\chatgpt_upload') -Filter 'pick_*.jpg' |
  Sort-Object LastWriteTime -Descending | Select-Object -First 3

$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'ChatGPT' } | Select-Object -First 1
[UAG]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
[UAG]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 300

$rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
$cond = New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'composer-plus-btn')
$btn = $rootEl.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
if (-not $btn) { throw 'NO_PLUS_BTN' }
$rect = $btn.Current.BoundingRectangle
Write-Host "plus x=$([int]$rect.X) y=$([int]$rect.Y) w=$([int]$rect.Width) h=$([int]$rect.Height)"

# Invoke pattern
try {
  $inv = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
  ([System.Windows.Automation.InvokePattern]$inv).Invoke()
  Write-Host 'invoked plus'
} catch {
  $cx = [int]($rect.X + $rect.Width/2)
  $cy = [int]($rect.Y + $rect.Height/2)
  [UAG]::SetCursorPos($cx,$cy) | Out-Null
  [UAG]::mouse_event([UAG]::D,0,0,0,[UIntPtr]::Zero)
  [UAG]::mouse_event([UAG]::U,0,0,0,[UIntPtr]::Zero)
  Write-Host "clicked plus $cx $cy"
}
Start-Sleep -Milliseconds 1000

# Find menu item for photos/files
$all = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$hit = $null
foreach ($el in $all) {
  $n = $el.Current.Name
  if ($n -and ($n -match 'photo|file|upload|Add photos|Add files|computer')) {
    Write-Host "menu candidate [$n] $($el.Current.ControlType.ProgrammaticName)"
    if ($n -match 'photo|Add files|upload from|from computer|Add photos') { $hit = $el }
  }
}
if ($hit) {
  try {
    $inv = $hit.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    ([System.Windows.Automation.InvokePattern]$inv).Invoke()
    Write-Host "invoked menu [$($hit.Current.Name)]"
  } catch {
    $rr = $hit.Current.BoundingRectangle
    $cx = [int]($rr.X + $rr.Width/2); $cy = [int]($rr.Y + $rr.Height/2)
    [UAG]::SetCursorPos($cx,$cy) | Out-Null
    [UAG]::mouse_event([UAG]::D,0,0,0,[UIntPtr]::Zero)
    [UAG]::mouse_event([UAG]::U,0,0,0,[UIntPtr]::Zero)
    Write-Host "clicked menu $cx $cy"
  }
} else {
  # Fallback click below plus
  $cx = [int]($rect.X + 60); $cy = [int]($rect.Y + 50)
  [UAG]::SetCursorPos($cx,$cy) | Out-Null
  [UAG]::mouse_event([UAG]::D,0,0,0,[UIntPtr]::Zero)
  [UAG]::mouse_event([UAG]::U,0,0,0,[UIntPtr]::Zero)
  Write-Host "fallback menu click $cx $cy"
}
Start-Sleep -Milliseconds 1500

$joined = ($imgs | ForEach-Object { '"' + $_.FullName + '"' }) -join ' '
Write-Host "paths $joined"
[System.Windows.Forms.SendKeys]::SendWait('%n')
Start-Sleep -Milliseconds 400
Set-Clipboard $joined
[System.Windows.Forms.SendKeys]::SendWait('^a')
Start-Sleep -Milliseconds 100
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 250
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Write-Host 'dialog submitted'
Start-Sleep -Seconds 6

# Screenshot
$r = New-Object UAG+RECT
[UAG]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object Drawing.Bitmap (($r.R-$r.L), ($r.B-$r.T))
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$shot = Join-Path $root '_qa_full_system_polish\desktop_iter21\junior_uia_attach.png'
$bmp.Save($shot)
$g.Dispose(); $bmp.Dispose()
Write-Host "SHOT $shot"
