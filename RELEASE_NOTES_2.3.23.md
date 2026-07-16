## MBT POS 2.3.23 — Lovable theme fix

### What was wrong (2.3.22)
- Qt QSS treated CSS-style hex alphas (`{err}22`) as `#AARRGGBB`, turning Void Sale and other tints olive/wrong
- Light mode left New Sale on dark gold `#F2A800` and Quick Actions on dark tiles
- POS qty controls hardcoded dark colors
- Windows native style (no Fusion) fought QSS

### What changed
- `qss_alpha()` / rgba() for all translucent colors
- Fusion style + Manrope
- Theme-aware dashboard New Sale / Void / Quick Actions
- Theme-aware POS qty chrome
- Tokens still match Lovable `styles.css` dark/light

### Verify
- Dark gold `#F2A800`, light gold `#B87000`
- Void Sale = red tint (not olive)
- Installer: `MBT_POS_Setup.exe`
