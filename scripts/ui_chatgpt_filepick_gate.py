"""Attach 3 checkout screenshots to Junior ChatGPT via + file picker UI."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from stamp_qa_images import stamp

PROMPT = """NEW screenshots attached (ignore colored QA borders).

Rate MBT POS checkout layouts in order: 1 Checkout Pro, 2 Product Explorer, 3 Retail Classic.

Respond EXACTLY:
CHECKOUT_PRO: <0-100>%
PRODUCT_EXPLORER: <0-100>%
RETAIL_CLASSIC: <0-100>%
OVERALL_CHECKOUT: <0-100>%

IMPROVED:
- ...

REMAINING (must-fix before 98%):
1. ...

NEXT FIXES (top 5 concrete UI only):
1. ...

Be strict. 98%=ship-ready."""


def ps_file(path: Path) -> str:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return (r.stdout or "") + (r.stderr or "")


def main():
    it = sys.argv[1] if len(sys.argv) > 1 else "21"
    folder = ROOT / "_qa_checkout_pro_design" / f"iter_{it}"
    out_dir = ROOT / "_qa_full_system_polish" / f"desktop_iter{it}"
    up = out_dir / "chatgpt_upload"
    up.mkdir(parents=True, exist_ok=True)
    stamp_id = str(int(time.time()))
    imgs = []
    for name, label in (
        ("checkout_pro.png", "PRO"),
        ("product_explorer.png", "EXPLORER"),
        ("retail_classic.png", "CLASSIC"),
    ):
        d = up / f"pick_{label.lower()}_{stamp_id}.jpg"
        stamp(folder / name, d, f"{label}-{stamp_id}-PICK")
        imgs.append(d.resolve())
        print("prepared", d.name, flush=True)

    # Write helper ps1 with absolute paths
    helper = ROOT / "scripts" / "_ui_attach_send.ps1"
    paths_csv = ";".join(str(p) for p in imgs)
    prompt_file = out_dir / "_gate_prompt.txt"
    prompt_file.write_text(PROMPT, encoding="utf-8")
    helper.write_text(
        f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class UA {{
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  public struct RECT {{ public int L; public int T; public int R; public int B; }}
  public const uint D=0x0002; public const uint U=0x0004;
}}
"@

function Focus-ChatGPT {{
  $p = Get-Process chrome | Where-Object {{ $_.MainWindowTitle -match 'ChatGPT' }} | Select-Object -First 1
  if (-not $p) {{ throw 'NO_CHATGPT_WINDOW' }}
  [UA]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
  [UA]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
  return $p
}}

function Click-At([int]$x, [int]$y) {{
  [UA]::SetCursorPos($x, $y) | Out-Null
  Start-Sleep -Milliseconds 80
  [UA]::mouse_event([UA]::D,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 40
  [UA]::mouse_event([UA]::U,0,0,0,[UIntPtr]::Zero)
}}

$p = Focus-ChatGPT
$r = New-Object UA+RECT
[UA]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
Write-Host "win $($r.L),$($r.T)-$($r.R),$($r.B)"

# Fresh chat: Ctrl+Shift+O often new chat on ChatGPT, else navigate
[System.Windows.Forms.SendKeys]::SendWait('^l')
Start-Sleep -Milliseconds 200
Set-Clipboard 'https://chatgpt.com/'
[System.Windows.Forms.SendKeys]::SendWait('^v{{ENTER}}')
Start-Sleep -Seconds 4
$p = Focus-ChatGPT
[UA]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null

# Click composer center-bottom
$cx = [int](($r.L + $r.R)/2)
$cy = [int]($r.B - 140)
Click-At $cx $cy
Start-Sleep -Milliseconds 400

# Click + button (left of composer). Approx: center-200, same y
$plusX = $cx - 220
$plusY = $cy
Click-At $plusX $plusY
Write-Host "clicked plus $plusX $plusY"
Start-Sleep -Milliseconds 800

# Click "Add photos and files" menu item - usually just below plus
Click-At $plusX $plusY + 40
# Also try a bit lower
Click-At ($plusX + 40) ($plusY + 55)
Start-Sleep -Milliseconds 1200

# File dialog should be open - type path of first file, then we may need multi-select
# For multi-select: quote paths separated by space in filename box
$paths = @('{paths}')
$joined = ($paths | ForEach-Object {{ '\"' + $_ + '\"' }}) -join ' '
Write-Host "filedialog paths: $joined"
Start-Sleep -Milliseconds 500
# Focus filename edit (Alt+N in common dialogs)
[System.Windows.Forms.SendKeys]::SendWait('%n')
Start-Sleep -Milliseconds 300
Set-Clipboard $joined
[System.Windows.Forms.SendKeys]::SendWait('^a')
Start-Sleep -Milliseconds 100
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 300
[System.Windows.Forms.SendKeys]::SendWait('{{ENTER}}')
Write-Host 'submitted file dialog'
Start-Sleep -Seconds 5

# Paste prompt
$p = Focus-ChatGPT
Click-At $cx $cy
Start-Sleep -Milliseconds 300
$prompt = Get-Content -Raw -Encoding UTF8 '{prompt_file}'
Set-Clipboard $prompt
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 800
[System.Windows.Forms.SendKeys]::SendWait('{{ENTER}}')
Write-Host 'SENT'
Start-Sleep -Seconds 3

# Screenshot
Add-Type -AssemblyName System.Drawing
$p = Focus-ChatGPT
[UA]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object Drawing.Bitmap (($r.R-$r.L), ($r.B-$r.T))
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$out = '{shot}'
$bmp.Save($out)
$g.Dispose(); $bmp.Dispose()
Write-Host "SHOT $out"
""".replace("{paths}", paths_csv.replace("'", "''"))
        .replace("{prompt_file}", str(prompt_file).replace("'", "''"))
        .replace("{shot}", str(out_dir / "chatgpt_ui_after_send.png").replace("'", "''")),
        encoding="utf-8",
    )
    # Fix the paths array injection - rewrite more carefully
    content = helper.read_text(encoding="utf-8")
    # The f-string already embedded paths_csv wrongly into $paths = @('{paths}')
    # Rebuild cleanly:
    path_list = ",\n  ".join(f'"{p}"' for p in imgs)
    helper.write_text(
        helper.read_text(encoding="utf-8")
        .replace("$paths = @('{paths}')", f"$paths = @(\n  {path_list}\n)"),
        encoding="utf-8",
    )
    # Actually the first write used paths_csv in replace of {paths} inside @('{paths}') - messy.
    # Rewrite the whole script cleanly below in Python without the broken template.
    lines = []
    lines.append("$ErrorActionPreference = 'Continue'")
    lines.append("Add-Type -AssemblyName System.Windows.Forms")
    lines.append(
        r"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class UA {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  public struct RECT { public int L; public int T; public int R; public int B; }
  public const uint D=0x0002; public const uint U=0x0004;
}
"@
"""
    )
    lines.append(
        r"""
function Focus-ChatGPT {
  $p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'ChatGPT' } | Select-Object -First 1
  if (-not $p) { throw 'NO_CHATGPT_WINDOW' }
  [UA]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
  [UA]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
  return $p
}
function Click-At([int]$x, [int]$y) {
  [UA]::SetCursorPos($x, $y) | Out-Null
  Start-Sleep -Milliseconds 80
  [UA]::mouse_event([UA]::D,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 40
  [UA]::mouse_event([UA]::U,0,0,0,[UIntPtr]::Zero)
}
"""
    )
    lines.append("$paths = @(")
    for p in imgs:
        lines.append(f'  "{p}",')
    lines.append(")")
    lines.append(f"$promptFile = '{prompt_file}'")
    lines.append(f"$shotPath = '{out_dir / 'chatgpt_ui_after_send.png'}'")
    lines.append(
        r"""
$p = Focus-ChatGPT
$r = New-Object UA+RECT
[UA]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
Write-Host "win $($r.L),$($r.T)-$($r.R),$($r.B)"
[System.Windows.Forms.SendKeys]::SendWait('^l')
Start-Sleep -Milliseconds 200
Set-Clipboard 'https://chatgpt.com/'
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 100
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Start-Sleep -Seconds 4
$p = Focus-ChatGPT
[UA]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$cx = [int](($r.L + $r.R)/2)
$cy = [int]($r.B - 140)
Click-At $cx $cy
Start-Sleep -Milliseconds 400
# + button left of composer
$plusX = $cx - 230
$plusY = $cy
Click-At $plusX $plusY
Write-Host "plus $plusX $plusY"
Start-Sleep -Milliseconds 900
# menu item Add photos
Click-At ($plusX + 30) ($plusY + 50)
Start-Sleep -Milliseconds 1400
$joined = ($paths | ForEach-Object { '"' + $_ + '"' }) -join ' '
Write-Host "paths $joined"
[System.Windows.Forms.SendKeys]::SendWait('%n')
Start-Sleep -Milliseconds 400
Set-Clipboard $joined
[System.Windows.Forms.SendKeys]::SendWait('^a')
Start-Sleep -Milliseconds 120
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 300
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Write-Host 'file dialog ok'
Start-Sleep -Seconds 6
$p = Focus-ChatGPT
[UA]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$cx = [int](($r.L + $r.R)/2)
$cy = [int]($r.B - 140)
Click-At $cx $cy
Start-Sleep -Milliseconds 300
Set-Clipboard (Get-Content -Raw -Encoding UTF8 $promptFile)
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 900
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
Write-Host 'SENT'
Start-Sleep -Seconds 4
Add-Type -AssemblyName System.Drawing
$p = Focus-ChatGPT
[UA]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object Drawing.Bitmap (($r.R-$r.L), ($r.B-$r.T))
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$bmp.Save($shotPath)
$g.Dispose(); $bmp.Dispose()
Write-Host "SHOT $shotPath"
"""
    )
    helper.write_text("\n".join(lines), encoding="utf-8")
    print(ps_file(helper), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
