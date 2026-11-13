Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class SC12 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
}
"@
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'POS Checkout Layouts|ChatGPT' -and $_.MainWindowTitle -match 'Google Chrome' } | Select-Object -First 1
if (-not $p) { throw 'NO_CHROME_WINDOW' }
Write-Host "using $($p.Id) $($p.MainWindowTitle)"
[SC12]::ShowWindow($p.MainWindowHandle, 3) | Out-Null
[SC12]::BringWindowToTop($p.MainWindowHandle) | Out-Null
[SC12]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 400
$root = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
# Get all text
$sb = New-Object System.Text.StringBuilder
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($el in $all) {
  $n = $el.Current.Name
  if ($n -and $n.Length -gt 2 -and $n -match '%|CHECKOUT|PRODUCT|RETAIL|OVERALL|IMPROVED|REMAINING|NEXT FIX') {
    [void]$sb.AppendLine($n)
  }
}
$out = 'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\_qa_full_system_polish\desktop_iter21\chatgpt_checkout_gate.txt'
# Also dump a larger scrape
$sb2 = New-Object System.Text.StringBuilder
$count = 0
foreach ($el in $all) {
  $n = $el.Current.Name
  if ($n -and $n.Length -gt 20) {
    [void]$sb2.AppendLine($n)
    $count++
    if ($count -gt 200) { break }
  }
}
$sb2.ToString() | Set-Content $out -Encoding UTF8
Write-Host "Wrote $out chars=$($sb2.Length) matches:"
Write-Host $sb.ToString()
