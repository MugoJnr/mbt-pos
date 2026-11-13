Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class SC8 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  public struct RECT { public int L; public int T; public int R; public int B; }
  public const uint D=0x0002; public const uint U=0x0004;
  public static void ForceFocus(IntPtr h) {
    uint pid; uint fore = GetWindowThreadProcessId(GetForegroundWindow(), out pid);
    uint app = GetCurrentThreadId();
    if (fore != app) AttachThreadInput(fore, app, true);
    ShowWindow(h, 9); BringWindowToTop(h); SetForegroundWindow(h);
    if (fore != app) AttachThreadInput(fore, app, false);
  }
}
"@
Get-Process | Where-Object { $_.MainWindowTitle -match 'POS 2\.3\.24' } | ForEach-Object { [SC8]::ShowWindow($_.MainWindowHandle, 6) | Out-Null }
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'POS Checkout Layouts' } | Select-Object -First 1
[SC8]::ForceFocus($p.MainWindowHandle)
Start-Sleep -Milliseconds 400
$r = New-Object SC8+RECT
[SC8]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
# Click composer
$cx = [int](($r.L+$r.R)/2); $cy = [int]($r.B - 140)
[SC8]::SetCursorPos($cx,$cy) | Out-Null
[SC8]::mouse_event([SC8]::D,0,0,0,[UIntPtr]::Zero)
[SC8]::mouse_event([SC8]::U,0,0,0,[UIntPtr]::Zero)
Start-Sleep -Milliseconds 300
$msg = @"
Repeat ONLY these four lines from your previous rating (exact numbers):

CHECKOUT_PRO: <n>%
PRODUCT_EXPLORER: <n>%
RETAIL_CLASSIC: <n>%
OVERALL_CHECKOUT: <n>%
"@
Set-Clipboard $msg
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 500
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Write-Host 'ASKED_SCORES'
Start-Sleep -Seconds 25
[SC8]::ForceFocus($p.MainWindowHandle)
[SC8]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
[System.Windows.Forms.SendKeys]::SendWait('^{END}')
Start-Sleep -Milliseconds 600
$bmp = New-Object Drawing.Bitmap (($r.R-$r.L), ($r.B-$r.T))
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$path = 'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\_qa_full_system_polish\desktop_iter21\junior_gate_scores.png'
$bmp.Save($path)
$g.Dispose(); $bmp.Dispose()
Write-Host "SHOT $path $((Get-Item $path).Length)"
