Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class SC9 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  public struct RECT { public int L; public int T; public int R; public int B; }
  public static void ForceFocus(IntPtr h) {
    uint pid; uint fore = GetWindowThreadProcessId(GetForegroundWindow(), out pid);
    uint app = GetCurrentThreadId();
    if (fore != app) AttachThreadInput(fore, app, true);
    ShowWindow(h, 3); // maximize
    BringWindowToTop(h); SetForegroundWindow(h);
    if (fore != app) AttachThreadInput(fore, app, false);
  }
}
"@
Get-Process | Where-Object { $_.MainWindowTitle -match 'POS 2\.3\.24' } | ForEach-Object { [SC9]::ShowWindow($_.MainWindowHandle, 6) | Out-Null }
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'POS Checkout Layouts' } | Select-Object -First 1
[SC9]::ForceFocus($p.MainWindowHandle)
Start-Sleep -Milliseconds 500

# Dismiss attachment toast if any - click elsewhere
[System.Windows.Forms.SendKeys]::SendWait('{ESC}')
Start-Sleep -Milliseconds 300

# Ask scores as text-only (no attach)
Set-Clipboard @"
Without needing images, restate ONLY your score lines from the prior review:

CHECKOUT_PRO: n%
PRODUCT_EXPLORER: n%
RETAIL_CLASSIC: n%
OVERALL_CHECKOUT: n%
"@
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 400
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Write-Host 'asked'
Start-Sleep -Seconds 20

[SC9]::ForceFocus($p.MainWindowHandle)
[System.Windows.Forms.SendKeys]::SendWait('^{END}')
Start-Sleep -Milliseconds 700
$r = New-Object SC9+RECT
[SC9]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object Drawing.Bitmap (($r.R-$r.L), ($r.B-$r.T))
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$path = 'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\_qa_full_system_polish\desktop_iter21\junior_gate_scores.png'
$bmp.Save($path)
$g.Dispose(); $bmp.Dispose()
Write-Host "SHOT $path $((Get-Item $path).Length) rect=$($r.L),$($r.T)-$($r.R),$($r.B)"
