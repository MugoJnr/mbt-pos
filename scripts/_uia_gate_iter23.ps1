$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class G22 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  public struct RECT { public int L; public int T; public int R; public int B; }
  public const uint D=0x0002; public const uint U=0x0004;
  public static void ForceFocus(IntPtr h) {
    uint pid; uint fore = GetWindowThreadProcessId(GetForegroundWindow(), out pid);
    uint app = GetCurrentThreadId();
    if (fore != app) AttachThreadInput(fore, app, true);
    ShowWindow(h, 3); BringWindowToTop(h); SetForegroundWindow(h);
    if (fore != app) AttachThreadInput(fore, app, false);
  }
}
"@

$root = 'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos'
$up = Join-Path $root '_qa_full_system_polish\desktop_iter23\chatgpt_upload'
$imgs = @(
  (Get-ChildItem $up -Filter 'pick_pro_*.jpg' | Sort-Object LastWriteTime -Descending | Select-Object -First 1),
  (Get-ChildItem $up -Filter 'pick_explorer_*.jpg' | Sort-Object LastWriteTime -Descending | Select-Object -First 1),
  (Get-ChildItem $up -Filter 'pick_classic_*.jpg' | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
)
Write-Host "files: $($imgs.Name -join ', ')"

Get-Process | Where-Object { $_.MainWindowTitle -match 'POS 2\.3\.24' } | ForEach-Object { [G22]::ShowWindow($_.MainWindowHandle, 6) | Out-Null }
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'Google Chrome' } | Select-Object -First 1
[G22]::ForceFocus($p.MainWindowHandle)
Start-Sleep -Milliseconds 400

# New chat
[System.Windows.Forms.SendKeys]::SendWait('^l')
Start-Sleep -Milliseconds 200
Set-Clipboard 'https://chatgpt.com/'
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 80
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Start-Sleep -Seconds 5
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'ChatGPT|Google Chrome' } | Select-Object -First 1
[G22]::ForceFocus($p.MainWindowHandle)

function Upload-One([string]$filePath) {
  $rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
  $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'composer-plus-btn')
  $btn = $rootEl.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
  if (-not $btn) { throw 'NO_PLUS' }
  $inv = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
  ([System.Windows.Automation.InvokePattern]$inv).Invoke()
  Start-Sleep -Milliseconds 900
  $all = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
  $target = $null
  foreach ($el in $all) {
    $n = $el.Current.Name
    if ($n -eq 'Add photos & files' -or $n -eq 'Upload from computer') { $target = $el; break }
  }
  if ($target) {
    $rr = $target.Current.BoundingRectangle
    $cx = [int]($rr.X + $rr.Width/2); $cy = [int]($rr.Y + $rr.Height/2)
    [G22]::SetCursorPos($cx,$cy) | Out-Null
    [G22]::mouse_event([G22]::D,0,0,0,[UIntPtr]::Zero)
    [G22]::mouse_event([G22]::U,0,0,0,[UIntPtr]::Zero)
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

foreach ($img in $imgs) { Upload-One $img.FullName }

$prompt = Get-Content -Raw -Encoding UTF8 (Join-Path $root '_qa_full_system_polish\desktop_iter21\_gate_prompt.txt')
$prompt = $prompt -replace 'NEW screenshots', 'NEW iter_23 screenshots after Amount Paid / hierarchy / density polish'
Set-Clipboard $prompt
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 800
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Write-Host 'SENT'
Start-Sleep -Seconds 45

# Scrape scores
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'Google Chrome' } | Select-Object -First 1
[G22]::ForceFocus($p.MainWindowHandle)
$rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
$all = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$sb = New-Object System.Text.StringBuilder
foreach ($el in $all) {
  $n = $el.Current.Name
  if ($n -and ($n -match 'CHECKOUT_PRO:|PRODUCT_EXPLORER:|RETAIL_CLASSIC:|OVERALL_CHECKOUT:|IMPROVED:|REMAINING|NEXT FIX')) {
    [void]$sb.AppendLine($n)
  }
}
$out = Join-Path $root '_qa_full_system_polish\desktop_iter23\chatgpt_checkout_gate.txt'
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
$sb.ToString() | Set-Content $out -Encoding UTF8
Write-Host "WROTE $out"
Write-Host $sb.ToString()

