Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class UAF {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
"@
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'ChatGPT' } | Select-Object -First 1
[UAF]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
$root = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$i = 0
foreach ($el in $all) {
  $n = $el.Current.Name
  $aid = $el.Current.AutomationId
  $ct = $el.Current.ControlType.ProgrammaticName
  if ($n -and ($n -match 'Add|Attach|Upload|photo|file|plus|\+|Ask anything|Send|composer')) {
    $r = $el.Current.BoundingRectangle
    Write-Host "$ct name=[$n] id=[$aid] x=$([int]$r.X) y=$([int]$r.Y) w=$([int]$r.Width) h=$([int]$r.Height)"
    $i++
    if ($i -gt 40) { break }
  }
}
Write-Host "done matched=$i"
