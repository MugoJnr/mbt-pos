Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class NavK {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
}
"@
$p = Get-Process chrome | Where-Object MainWindowTitle | Select-Object -First 1
[NavK]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
[NavK]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 300
[System.Windows.Forms.SendKeys]::SendWait('^l')
Start-Sleep -Milliseconds 200
Set-Clipboard 'https://chatgpt.com/'
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 100
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Start-Sleep -Seconds 4
Write-Host (Get-Process chrome | Where-Object MainWindowTitle | Select-Object -ExpandProperty MainWindowTitle)
