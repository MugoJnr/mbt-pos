Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class SC7 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
  public struct RECT { public int L; public int T; public int R; public int B; }
  public static void ForceFocus(IntPtr h) {
    uint pid; uint foreThread = GetWindowThreadProcessId(GetForegroundWindow(), out pid);
    uint appThread = GetCurrentThreadId();
    if (foreThread != appThread) AttachThreadInput(foreThread, appThread, true);
    ShowWindow(h, 9); // SW_RESTORE
    BringWindowToTop(h);
    SetForegroundWindow(h);
    if (foreThread != appThread) AttachThreadInput(foreThread, appThread, false);
  }
}
"@

# Minimize Cursor-like windows that steal focus (optional: only if title matches)
Get-Process | Where-Object { $_.MainWindowTitle -match 'POS 2\.3\.24' } | ForEach-Object {
  [SC7]::ShowWindow($_.MainWindowHandle, 6) | Out-Null # SW_MINIMIZE
  Write-Host "minimized $($_.MainWindowTitle)"
}

$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'POS Checkout Layouts' } | Select-Object -First 1
if (-not $p) { throw 'NO_CHROME' }
[SC7]::ForceFocus($p.MainWindowHandle)
Start-Sleep -Milliseconds 600
Write-Host "fg chrome title=$($p.MainWindowTitle)"

$r = New-Object SC7+RECT
[SC7]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
Write-Host "rect $($r.L),$($r.T)-$($r.R),$($r.B)"

# Click chat, jump to end, page up to scores
[System.Windows.Forms.SendKeys]::SendWait('^{END}')
Start-Sleep -Milliseconds 500
1..4 | ForEach-Object { [System.Windows.Forms.SendKeys]::SendWait('{PGUP}'); Start-Sleep -Milliseconds 180 }
Start-Sleep -Milliseconds 400

$bmp = New-Object Drawing.Bitmap (($r.R-$r.L), ($r.B-$r.T))
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$path = 'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\_qa_full_system_polish\desktop_iter21\junior_gate_scores.png'
$bmp.Save($path)
$g.Dispose(); $bmp.Dispose()
Write-Host "SHOT $path size=$((Get-Item $path).Length)"
