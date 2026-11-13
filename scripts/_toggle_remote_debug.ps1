Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Clicker {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
  public const uint LEFTDOWN=0x0002; public const uint LEFTUP=0x0004;
}
"@

$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'Inspect' } | Select-Object -First 1
if (-not $p) { Write-Host 'NO_INSPECT'; exit 1 }
[Clicker]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
$root = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
$cond = New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
  [System.Windows.Automation.ControlType]::CheckBox
)
$boxes = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
Write-Host "checkboxes: $($boxes.Count)"
foreach ($b in $boxes) {
  $name = $b.Current.Name
  $rect = $b.Current.BoundingRectangle
  Write-Host "BOX name=[$name] x=$([int]$rect.X) y=$([int]$rect.Y) w=$([int]$rect.Width) h=$([int]$rect.Height)"
  if ($name -match 'Allow remote|remote debugging') {
    $pat = $b.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
    if ($pat) {
      $tp = [System.Windows.Automation.TogglePattern]$pat
      Write-Host "toggle state before: $($tp.Current.ToggleState)"
      $tp.Toggle()
      Start-Sleep -Milliseconds 500
      Write-Host "toggle state after: $($tp.Current.ToggleState)"
    } else {
      $cx = [int]($rect.X + $rect.Width / 2)
      $cy = [int]($rect.Y + $rect.Height / 2)
      [Clicker]::SetCursorPos($cx, $cy) | Out-Null
      [Clicker]::mouse_event([Clicker]::LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
      [Clicker]::mouse_event([Clicker]::LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
      Write-Host "clicked at $cx $cy"
    }
  }
}

# Fallback: search all elements for Allow remote text and invoke parent
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($el in $all) {
  $n = $el.Current.Name
  if ($n -and ($n -match 'Allow remote debugging')) {
    Write-Host "FOUND $($el.Current.ControlType.ProgrammaticName) [$n]"
    try {
      $inv = $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
      if ($inv) { ([System.Windows.Automation.InvokePattern]$inv).Invoke(); Write-Host 'invoked' }
    } catch {}
    try {
      $tog = $el.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
      if ($tog) { ([System.Windows.Automation.TogglePattern]$tog).Toggle(); Write-Host 'toggled' }
    } catch {}
    $rect = $el.Current.BoundingRectangle
    $cx = [int]($rect.X + 8)
    $cy = [int]($rect.Y + $rect.Height / 2)
    [Clicker]::SetCursorPos($cx, $cy) | Out-Null
    Start-Sleep -Milliseconds 100
    [Clicker]::mouse_event([Clicker]::LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
    [Clicker]::mouse_event([Clicker]::LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
    Write-Host "clicked label at $cx $cy"
  }
}
Write-Host 'DONE'
