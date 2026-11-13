"""UI-automation ChatGPT checkout gate on the visible Junior Chrome window (no CDP)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from stamp_qa_images import stamp

CLIP = ROOT / "scripts" / "clip_image.ps1"
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


def ps(cmd: str, timeout: int = 60) -> str:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return (r.stdout or "") + (r.stderr or "")


def focus_chatgpt() -> None:
    out = ps(
        r"""
Add-Type @"
using System; using System.Runtime.InteropServices;
public class F {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
}
"@
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'ChatGPT' } | Select-Object -First 1
if (-not $p) { $p = Get-Process chrome | Where-Object MainWindowTitle | Select-Object -First 1 }
[F]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
[F]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
$p.MainWindowTitle
"""
    )
    print("focus", out.strip(), flush=True)


def send_keys(sequence: str) -> None:
    # sequence examples: ^l  ^v  {ENTER}  etc (SendKeys syntax)
    ps(f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('{sequence}')")


def clip_image(path: Path) -> None:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(CLIP), str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if "CLIP_OK" not in (r.stdout or ""):
        raise RuntimeError(f"clip failed: {r.stdout} {r.stderr}")


def screenshot(dest: Path) -> None:
    ps(
        rf"""
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class Sc {{
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  public struct RECT {{ public int L; public int T; public int R; public int B; }}
}}
"@
$p = Get-Process chrome | Where-Object {{ $_.MainWindowTitle -match 'ChatGPT|Inspect' }} | Select-Object -First 1
if (-not $p) {{ $p = Get-Process chrome | Where-Object MainWindowTitle | Select-Object -First 1 }}
[Sc]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
$r = New-Object Sc+RECT
[Sc]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object Drawing.Bitmap (($r.R-$r.L), ($r.B-$r.T))
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$bmp.Save('{str(dest).replace("'", "''")}')
$g.Dispose(); $bmp.Dispose()
"""
    )


def type_text(text: str) -> None:
    # Put prompt on clipboard and paste (avoids SendKeys escaping hell)
    tmp = ROOT / "_qa_full_system_polish" / "_clip_prompt.txt"
    tmp.write_text(text, encoding="utf-8")
    ps(
        f"Set-Clipboard -Value (Get-Content -Raw -Encoding UTF8 '{tmp}')"
    )
    time.sleep(0.2)
    send_keys("^v")


def main():
    it = sys.argv[1] if len(sys.argv) > 1 else "21"
    folder = ROOT / "_qa_checkout_pro_design" / f"iter_{it}"
    out_dir = ROOT / "_qa_full_system_polish" / f"desktop_iter{it}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "chatgpt_checkout_gate.txt"
    up = out_dir / "chatgpt_upload"
    up.mkdir(parents=True, exist_ok=True)
    stamp_id = str(int(time.time()))
    imgs = []
    for name, label in (
        ("checkout_pro.png", "PRO"),
        ("product_explorer.png", "EXPLORER"),
        ("retail_classic.png", "CLASSIC"),
    ):
        d = up / f"ui_{label.lower()}_{stamp_id}.jpg"
        stamp(folder / name, d, f"{label}-{stamp_id}-UI")
        imgs.append(d)
        print("prepared", d.name, flush=True)

    # Navigate to chatgpt new chat
    focus_chatgpt()
    time.sleep(0.3)
    send_keys("^l")
    time.sleep(0.2)
    ps("Set-Clipboard 'https://chatgpt.com/'")
    send_keys("^v")
    time.sleep(0.1)
    send_keys("{ENTER}")
    time.sleep(4.5)
    focus_chatgpt()
    time.sleep(0.5)

    # Click composer roughly (bottom center) then paste images
    # Focus page body and click lower composer via Tab? Use click at bottom center of window
    ps(
        r"""
Add-Type @"
using System; using System.Runtime.InteropServices;
public class Clk {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  public struct RECT { public int L; public int T; public int R; public int B; }
  public const uint D=0x0002; public const uint U=0x0004;
}
"@
$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'ChatGPT' } | Select-Object -First 1
[Clk]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
$r = New-Object Clk+RECT
[Clk]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$x = [int](($r.L + $r.R) / 2)
$y = [int]($r.B - 120)
[Clk]::SetCursorPos($x, $y) | Out-Null
[Clk]::mouse_event([Clk]::D,0,0,0,[UIntPtr]::Zero)
[Clk]::mouse_event([Clk]::U,0,0,0,[UIntPtr]::Zero)
"clicked composer $x $y"
"""
    )
    time.sleep(0.5)

    for img in imgs:
        clip_image(img)
        time.sleep(0.3)
        focus_chatgpt()
        send_keys("^v")
        print("pasted", img.name, flush=True)
        time.sleep(2.5)

    time.sleep(1.0)
    type_text(PROMPT)
    time.sleep(0.8)
    send_keys("{ENTER}")
    print("sent", flush=True)

    # Wait and screenshot periodically; stop when we see CHECKOUT_PRO in OCR-less visual dumps
    # Save screenshots for vision read
    end = time.time() + 180
    last_shot = None
    n = 0
    while time.time() < end:
        n += 1
        shot = out_dir / f"chatgpt_ui_reply_{n}.png"
        focus_chatgpt()
        screenshot(shot)
        last_shot = shot
        print("shot", shot.name, shot.stat().st_size, flush=True)
        time.sleep(8)
        if n >= 8:
            break

    # Store pointer for parent/agent vision read
    meta = {
        "shots": [str(out_dir / f"chatgpt_ui_reply_{i}.png") for i in range(1, n + 1)],
        "last": str(last_shot) if last_shot else None,
        "note": "Parse CHECKOUT_PRO scores from last screenshot via vision",
    }
    (out_dir / "chatgpt_ui_gate_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("META", meta["last"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
