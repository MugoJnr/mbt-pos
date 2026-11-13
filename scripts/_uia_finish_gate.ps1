$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class UAH {
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
# Prefer PRO, EXPLORER, CLASSIC order
$all = Get-ChildItem (Join-Path $root '_qa_full_system_polish\desktop_iter21\chatgpt_upload') -Filter 'pick_*.jpg' | Sort-Object LastWriteTime -Descending
$pro = $all | Where-Object Name -match 'pro_' | Select-Object -First 1
$exp = $all | Where-Object Name -match 'explorer_' | Select-Object -First 1
$cls = $all | Where-Object Name -match 'classic_' | Select-Object -First 1
# Already have one attached (unknown which). Attach the other two via clipboard paste image
$toPaste = @($pro, $exp, $cls) | Where-Object { $_ }

$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'ChatGPT' } | Select-Object -First 1
[UAH]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
[UAH]::SetForegroundWindow($p.MainWindowHandle) | Out-Null

function Invoke-PlusUpload([string]$filePath) {
  $rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
  $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'composer-plus-btn')
  $btn = $rootEl.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
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
    [UAH]::SetCursorPos($cx,$cy) | Out-Null
    [UAH]::mouse_event([UAH]::D,0,0,0,[UIntPtr]::Zero)
    [UAH]::mouse_event([UAH]::U,0,0,0,[UIntPtr]::Zero)
    Write-Host "clicked $($target.Current.Name) at $cx $cy"
  }
  Start-Sleep -Milliseconds 1200
  Set-Clipboard ("`"$filePath`"")
  [System.Windows.Forms.SendKeys]::SendWait('%n')
  Start-Sleep -Milliseconds 300
  [System.Windows.Forms.SendKeys]::SendWait('^a')
  Start-Sleep -Milliseconds 80
  [System.Windows.Forms.SendKeys]::SendWait('^v')
  Start-Sleep -Milliseconds 200
  [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
  Write-Host "uploaded $filePath"
  Start-Sleep -Seconds 3
}

# Attach remaining via one-by-one (safer). Skip if already 3 - we don't know count, attach all three again after clear? 
# Just attach pro and explorer explicitly (classic may already be there)
foreach ($f in @($pro, $exp)) {
  if ($f) { Invoke-PlusUpload $f.FullName }
}

# Paste prompt
$prompt = Get-Content -Raw -Encoding UTF8 (Join-Path $root '_qa_full_system_polish\desktop_iter21\_gate_prompt.txt')
Set-Clipboard $prompt
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 800
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Write-Host 'SENT'
Start-Sleep -Seconds 8

# Screenshot
$r = New-Object UAH+RECT
[UAH]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object Drawing.Bitmap (($r.R-$r.L), ($r.B-$r.T))
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$shot = Join-Path $root '_qa_full_system_polish\desktop_iter21\junior_gate_reply.png'
$bmp.Save($shot)
$g.Dispose(); $bmp.Dispose()
Write-Host "SHOT $shot"
