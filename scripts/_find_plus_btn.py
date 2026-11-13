"""Find + button coords in junior_compose.png and print screen coords."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

im = Image.open(
    Path(__file__).resolve().parents[1]
    / "_qa_full_system_polish/desktop_iter21/junior_compose.png"
).convert("RGB")
w, h = im.size
px = im.load()
print("img", w, h)
# Scan bottom band for the round + control (medium gray circle)
candidates = []
for y in range(int(h * 0.70), int(h * 0.95)):
    for x in range(int(w * 0.18), int(w * 0.55)):
        r, g, b = px[x, y]
        if not (70 <= r <= 170 and abs(r - g) < 25 and abs(g - b) < 25):
            continue
        # neighborhood variance / ring
        vals = []
        for dy in range(-8, 9):
            for dx in range(-8, 9):
                xx, yy = x + dx, y + dy
                if 0 <= xx < w and 0 <= yy < h:
                    vals.append(sum(px[xx, yy]))
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        if 250 < avg < 520:
            candidates.append((avg, x, y))
candidates.sort(reverse=True)
print("top", candidates[:10])
if candidates:
    _, x, y = candidates[0]
    print(f"REL {x},{y}")
