#!/usr/bin/env python3
"""
Generate MBT POS offline WAV library (procedural, unique tones — not Windows system sounds).
Run once at build/dev time. Runtime plays only local files.
"""
from __future__ import annotations

import math
import os
import struct
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'assets', 'sounds', 'library')
SR = 22050


def _env(i: int, n: int, attack=0.01, release=0.04) -> float:
    t = i / SR
    dur = n / SR
    a = min(1.0, t / attack) if attack > 0 else 1.0
    r = 1.0
    if release > 0 and t > dur - release:
        r = max(0.0, (dur - t) / release)
    return a * r


def write_wav(path: str, samples: list[float], peak: float = 0.55):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mx = max((abs(s) for s in samples), default=1.0) or 1.0
    scale = peak / mx
    with wave.open(path, 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        frames = b''.join(
            struct.pack('<h', max(-32767, min(32767, int(s * scale * 32767))))
            for s in samples
        )
        w.writeframes(frames)


def tone(freq: float, dur: float, vol: float = 1.0, wave_fn='sine') -> list[float]:
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        if wave_fn == 'triangle':
            phase = (t * freq) % 1.0
            v = 4.0 * abs(phase - 0.5) - 1.0
        elif wave_fn == 'soft_square':
            v = math.tanh(3.0 * math.sin(2 * math.pi * freq * t))
        else:
            v = math.sin(2 * math.pi * freq * t)
        # slight 2nd harmonic for character (not pure beep)
        v += 0.18 * math.sin(4 * math.pi * freq * t)
        out.append(v * vol * _env(i, n))
    return out


def chord(freqs, dur, vol=0.9) -> list[float]:
    parts = [tone(f, dur, vol / max(1, len(freqs))) for f in freqs]
    n = max(len(p) for p in parts)
    out = [0.0] * n
    for p in parts:
        for i, s in enumerate(p):
            out[i] += s
    return out


def sweep(f0, f1, dur, vol=0.85) -> list[float]:
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        f = f0 + (f1 - f0) * (t / dur)
        v = math.sin(2 * math.pi * f * t)
        v += 0.12 * math.sin(4 * math.pi * f * t)
        out.append(v * vol * _env(i, n, 0.008, 0.05))
    return out


def blip_pair(f1, f2, gap=0.04) -> list[float]:
    return tone(f1, 0.06) + [0.0] * int(SR * gap) + tone(f2, 0.08, 0.9)


SOUNDS = {
    'startup': lambda: chord([262, 330, 392, 523], 0.45, 0.7),
    'login_ok': lambda: blip_pair(440, 660),
    'login_fail': lambda: tone(180, 0.22, 0.9, 'soft_square') + tone(140, 0.28, 0.85, 'soft_square'),
    'barcode': lambda: tone(980, 0.045, 0.75, 'triangle'),
    'product_add': lambda: blip_pair(520, 780, 0.03),
    'product_remove': lambda: blip_pair(620, 380, 0.03),
    'sale_complete': lambda: chord([392, 494, 587], 0.35, 0.75),
    'void': lambda: sweep(420, 180, 0.28, 0.8) + tone(150, 0.18, 0.7, 'soft_square'),
    'pay_cash': lambda: tone(880, 0.07) + tone(1100, 0.09),
    'pay_mpesa': lambda: chord([523, 659], 0.18, 0.7),
    'pay_card': lambda: sweep(700, 900, 0.12) + tone(950, 0.06),
    'pay_credit': lambda: tone(349, 0.1) + tone(440, 0.12),
    'low_stock': lambda: tone(480, 0.1, 0.8) + [0.0] * int(SR * 0.06) + tone(480, 0.14, 0.75),
    'error': lambda: tone(200, 0.35, 0.95, 'soft_square'),
    'warning': lambda: tone(560, 0.12) + [0.0] * int(SR * 0.05) + tone(560, 0.16),
    'success': lambda: blip_pair(523, 784, 0.04),
    'ai_thinking': lambda: sweep(300, 480, 0.22, 0.45),
    'ai_ready': lambda: chord([440, 554, 659], 0.28, 0.55),
    'permission': lambda: tone(220, 0.15, 0.85, 'soft_square') + tone(180, 0.2, 0.8),
    'dialog_open': lambda: tone(640, 0.04, 0.45, 'triangle'),
    'dialog_close': lambda: tone(420, 0.04, 0.4, 'triangle'),
    'save': lambda: blip_pair(600, 900, 0.025),
    'delete': lambda: sweep(500, 220, 0.2, 0.75),
    'nav': lambda: tone(720, 0.035, 0.4, 'triangle'),
    'click': lambda: tone(1000, 0.022, 0.35, 'triangle'),
    'notify': lambda: tone(660, 0.08) + tone(880, 0.1),
}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, fn in SOUNDS.items():
        path = os.path.join(OUT, f'{name}.wav')
        write_wav(path, fn(), peak=0.52)
        print('wrote', path)
    print('OK', len(SOUNDS), 'sounds ->', OUT)


if __name__ == '__main__':
    main()
