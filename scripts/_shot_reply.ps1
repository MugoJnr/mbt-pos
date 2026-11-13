Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class SC2 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  public struct RECT { public int L; public int T; public int R; public int B; }
}
"@
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'ChatGPT|MBT|Layout' } | Select-Object -First 1
[SC2]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 300
[System.Windows.Forms.SendKeys]::SendWait('{PGDN}')
Start-Sleep -Milliseconds 400
[System.Windows.Forms.SendKeys]::SendWait('{PGDN}')
Start-Sleep -Milliseconds 400
[System.Windows.Forms.SendKeys]::SendWait('{END}')
Start-Sleep -Milliseconds 500
$r = New-Object SC2+RECT
[SC2]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object Drawing.Bitmap (($r.R-$r.L), ($r.B-$r.T))
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$path = 'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\_qa_full_system_polish\desktop_iter21\junior_gate_reply2.png'
$bmp.Save($path)
$g.Dispose(); $bmp.Dispose()
Write-Host $p.MainWindowTitle
Write-Host "SHOT $path"
