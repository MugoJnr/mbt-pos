$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class G23d {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  public const uint D=0x0002; public const uint U=0x0004;
}
"@
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'ChatGPT|Google Chrome' } | Select-Object -First 1
[G23d]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep 1
$rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'composer-plus-btn')
$btn = $rootEl.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
Write-Host "plus=$([bool]$btn)"
if ($btn) {
  ([System.Windows.Automation.InvokePattern]$btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)).Invoke()
  Start-Sleep -Milliseconds 1200
}
$all = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($el in $all) {
  $n = $el.Current.Name
  if ($n -match 'photo|file|upload|computer|Add ') {
    Write-Host "ITEM [$n] $($el.Current.ControlType.ProgrammaticName) id=$($el.Current.AutomationId)"
  }
}
# Click Add photos & files by name via tree walk parent invoke
foreach ($el in $all) {
  if ($el.Current.Name -eq 'Add photos & files') {
    $rr = $el.Current.BoundingRectangle
    Write-Host "clicking Add photos at $([int]$rr.X),$([int]$rr.Y)"
    [G23d]::SetCursorPos([int]($rr.X+20), [int]($rr.Y+$rr.Height/2)) | Out-Null
    [G23d]::mouse_event([G23d]::D,0,0,0,[UIntPtr]::Zero)
    [G23d]::mouse_event([G23d]::U,0,0,0,[UIntPtr]::Zero)
    break
  }
}
Start-Sleep 2
Write-Host '--- windows ---'
$desktop = [System.Windows.Automation.AutomationElement]::RootElement
$wcond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Window)
$wins = $desktop.FindAll([System.Windows.Automation.TreeScope]::Children, $wcond)
foreach ($w in $wins) {
  Write-Host "WIN [$($w.Current.Name)]"
}
