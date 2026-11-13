$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class G23c {
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
$imgs = @(
  (Get-ChildItem $up -Filter 'pick_pro_*.jpg' | Sort-Object LastWriteTime -Descending | Select-Object -First 1),
  (Get-ChildItem $up -Filter 'pick_explorer_*.jpg' | Sort-Object LastWriteTime -Descending | Select-Object -First 1),
  (Get-ChildItem $up -Filter 'pick_classic_*.jpg' | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
)

Get-Process | Where-Object { $_.MainWindowTitle -match 'POS 2\.3\.24' } | ForEach-Object { [G23c]::ShowWindow($_.MainWindowHandle, 6) | Out-Null }
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'ChatGPT|Google Chrome' } | Select-Object -First 1
[G23c]::ShowWindow($p.MainWindowHandle, 3) | Out-Null
[G23c]::BringWindowToTop($p.MainWindowHandle) | Out-Null
[G23c]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep 1

# New chat
[System.Windows.Forms.SendKeys]::SendWait('^l')
Start-Sleep -Milliseconds 250
Set-Clipboard 'https://chatgpt.com/'
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 80
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Start-Sleep -Seconds 5
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'ChatGPT|Google Chrome' } | Select-Object -First 1
[G23c]::SetForegroundWindow($p.MainWindowHandle) | Out-Null

function Wait-Plus([int]$timeoutSec = 40) {
  $end = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $end) {
    $rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
    $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'composer-plus-btn')
    $btn = $rootEl.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
    if ($btn) { return $btn }
    Start-Sleep -Milliseconds 400
  }
  return $null
}

function Wait-OpenDialog([int]$timeoutSec = 15) {
  $end = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $end) {
    $desktop = [System.Windows.Automation.AutomationElement]::RootElement
    $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Window)
    $wins = $desktop.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
    foreach ($w in $wins) {
      $n = $w.Current.Name
      if ($n -match '^(Open|File Upload)$') { return $w }
    }
    Start-Sleep -Milliseconds 300
  }
  return $null
}

function Upload-One([string]$filePath) {
  Write-Host "upload $filePath"
  $btn = Wait-Plus 40
  if (-not $btn) { throw 'NO_PLUS' }
  ([System.Windows.Automation.InvokePattern]$btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)).Invoke()
  Start-Sleep -Milliseconds 900
  $rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
  $all = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
  $target = $null
  foreach ($el in $all) {
    if ($el.Current.Name -eq 'Add photos & files' -or $el.Current.Name -eq 'Upload from computer') { $target = $el; break }
  }
  if ($target) {
    $rr = $target.Current.BoundingRectangle
    $cx = [int]($rr.X + $rr.Width / 2); $cy = [int]($rr.Y + $rr.Height / 2)
    [G23c]::SetCursorPos($cx, $cy) | Out-Null
    [G23c]::mouse_event([G23c]::D, 0, 0, 0, [UIntPtr]::Zero)
    [G23c]::mouse_event([G23c]::U, 0, 0, 0, [UIntPtr]::Zero)
    Write-Host "menu $($target.Current.Name)"
  }
  $dlg = Wait-OpenDialog 12
  if (-not $dlg) { throw 'NO_OPEN_DIALOG' }
  Write-Host "dialog $($dlg.Current.Name)"
  # Filename edit: AutomationId 1148 often, or Name File name
  $editCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, '1148')
  $edit = $dlg.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $editCond)
  if (-not $edit) {
    $editCond2 = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, 'File name:')
    $edit = $dlg.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $editCond2)
  }
  if ($edit) {
    $edit.SetFocus()
    Start-Sleep -Milliseconds 200
    $vp = $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    if ($vp) {
      ([System.Windows.Automation.ValuePattern]$vp).SetValue($filePath)
    } else {
      Set-Clipboard $filePath
      [System.Windows.Forms.SendKeys]::SendWait('^a')
      Start-Sleep -Milliseconds 80
      [System.Windows.Forms.SendKeys]::SendWait('^v')
    }
  } else {
    Set-Clipboard $filePath
    [System.Windows.Forms.SendKeys]::SendWait('%n')
    Start-Sleep -Milliseconds 200
    [System.Windows.Forms.SendKeys]::SendWait('^a')
    [System.Windows.Forms.SendKeys]::SendWait('^v')
  }
  Start-Sleep -Milliseconds 300
  [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
  Write-Host "uploaded $(Split-Path $filePath -Leaf)"
  Start-Sleep -Seconds 3.5
}

foreach ($img in $imgs) { Upload-One $img.FullName }

$prompt = @"
NEW iter_23 screenshots attached (ignore colored QA borders).

Rate MBT POS checkout layouts in order: 1 Checkout Pro, 2 Product Explorer, 3 Retail Classic.

Respond EXACTLY:
CHECKOUT_PRO: <0-100>%
PRODUCT_EXPLORER: <0-100>%
RETAIL_CLASSIC: <0-100>%
OVERALL_CHECKOUT: <0-100>%

IMPROVED:
- ...

REMAINING (must-fix before 98%):
1. ...

NEXT FIXES (top 5 concrete UI only):
1. ...

Be strict. 98%=ship-ready.
"@
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
  if ($n -and ($n -match 'CHECKOUT_PRO:\s*\d+%|PRODUCT_EXPLORER:\s*\d+%|RETAIL_CLASSIC:\s*\d+%|OVERALL_CHECKOUT:\s*\d+%|IMPROVED:|REMAINING|NEXT FIX')) {
    [void]$sb.AppendLine($n)
  }
}
$out = Join-Path $root '_qa_full_system_polish\desktop_iter23\chatgpt_checkout_gate.txt'
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
$sb.ToString() | Set-Content $out -Encoding UTF8
Write-Host 'RESULT'
Write-Host $sb.ToString()
