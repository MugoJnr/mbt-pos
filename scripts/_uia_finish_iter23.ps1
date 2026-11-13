$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class G23b {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  public const uint D=0x0002; public const uint U=0x0004;
}
"@

$root = 'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos'
$up = Join-Path $root '_qa_full_system_polish\desktop_iter23\chatgpt_upload'
$exp = Get-ChildItem $up -Filter 'pick_explorer_*.jpg' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$cls = Get-ChildItem $up -Filter 'pick_classic_*.jpg' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'Google Chrome' } | Select-Object -First 1
[G23b]::ShowWindow($p.MainWindowHandle, 3) | Out-Null
[G23b]::BringWindowToTop($p.MainWindowHandle) | Out-Null
[G23b]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep 2

function Wait-Plus([int]$timeoutSec = 40) {
  $end = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $end) {
    $rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
    $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'composer-plus-btn')
    $btn = $rootEl.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
    if ($btn) { return $btn }
    Start-Sleep -Milliseconds 500
  }
  return $null
}

function Upload-One([string]$filePath) {
  $btn = Wait-Plus 40
  if (-not $btn) { throw 'NO_PLUS' }
  $inv = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
  ([System.Windows.Automation.InvokePattern]$inv).Invoke()
  Start-Sleep -Milliseconds 1000
  $rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
  $all = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
  $target = $null
  foreach ($el in $all) {
    if ($el.Current.Name -eq 'Add photos & files' -or $el.Current.Name -eq 'Upload from computer') { $target = $el; break }
  }
  if ($target) {
    $rr = $target.Current.BoundingRectangle
    $cx = [int]($rr.X + $rr.Width / 2); $cy = [int]($rr.Y + $rr.Height / 2)
    [G23b]::SetCursorPos($cx, $cy) | Out-Null
    [G23b]::mouse_event([G23b]::D, 0, 0, 0, [UIntPtr]::Zero)
    [G23b]::mouse_event([G23b]::U, 0, 0, 0, [UIntPtr]::Zero)
  }
  Start-Sleep -Milliseconds 1200
  Set-Clipboard ('"' + $filePath + '"')
  [System.Windows.Forms.SendKeys]::SendWait('%n')
  Start-Sleep -Milliseconds 300
  [System.Windows.Forms.SendKeys]::SendWait('^a')
  Start-Sleep -Milliseconds 80
  [System.Windows.Forms.SendKeys]::SendWait('^v')
  Start-Sleep -Milliseconds 200
  [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
  Write-Host "uploaded $(Split-Path $filePath -Leaf)"
  Start-Sleep -Seconds 3.5
}

Upload-One $exp.FullName
Upload-One $cls.FullName

$prompt = Get-Content -Raw -Encoding UTF8 (Join-Path $root '_qa_full_system_polish\desktop_iter21\_gate_prompt.txt')
$prompt = $prompt -replace 'NEW screenshots', 'NEW iter_23 screenshots after Classic-baseline alignment pass'
Set-Clipboard $prompt
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 800
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Write-Host 'SENT'
Start-Sleep -Seconds 55

$rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
$all = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$sb = New-Object System.Text.StringBuilder
foreach ($el in $all) {
  $n = $el.Current.Name
  if ($n -and ($n -match 'CHECKOUT_PRO:\s*\d+%|PRODUCT_EXPLORER:\s*\d+%|RETAIL_CLASSIC:\s*\d+%|OVERALL_CHECKOUT:\s*\d+%')) {
    [void]$sb.AppendLine($n)
  }
}
$out = Join-Path $root '_qa_full_system_polish\desktop_iter23\chatgpt_checkout_gate.txt'
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
$sb.ToString() | Set-Content $out -Encoding UTF8
Write-Host 'SCORES:'
Write-Host $sb.ToString()
