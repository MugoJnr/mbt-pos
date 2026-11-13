Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class FX2 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
}
"@
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'POS Checkout Layouts Evaluation' } | Select-Object -First 1
if (-not $p) {
  Get-Process chrome | Where-Object MainWindowTitle | ForEach-Object { Write-Host "CHROME $($_.Id) $($_.MainWindowTitle)" }
  throw 'NO_EVAL_WINDOW'
}
Write-Host "found $($p.Id) $($p.MainWindowTitle)"
[FX2]::ShowWindow($p.MainWindowHandle, 3) | Out-Null
[FX2]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep 1
$root = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$hits = New-Object System.Collections.Generic.List[string]
foreach ($el in $all) {
  $n = $el.Current.Name
  if ($n -and ($n -match 'CHECKOUT_PRO:\s*\d+%|PRODUCT_EXPLORER:\s*\d+%|RETAIL_CLASSIC:\s*\d+%|OVERALL_CHECKOUT:\s*\d+%')) {
    if (-not $hits.Contains($n)) { $hits.Add($n) }
  }
}
$out = 'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\_qa_full_system_polish\desktop_iter23\scrape_eval.txt'
$hits | Set-Content $out -Encoding UTF8
Write-Host "wrote $out"
$hits | ForEach-Object { Write-Host $_ }
