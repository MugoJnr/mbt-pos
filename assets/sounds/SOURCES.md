# MBT POS Sound Sources

All runtime audio is **bundled locally** under `assets/sounds/`. No network requests at runtime.

## Generation

Procedural WAV tones created by `scripts/generate_audio_library.py` (MBT-unique; not Windows system sounds).

- Sample rate: 22050 Hz mono 16-bit
- Peak normalized to ~0.52 (−5.7 dBFS) for balanced play across events
- Light 2nd harmonic + short attack/release envelopes for a professional POS feel

## Library files (`library/`)

| File | Used for |
|------|----------|
| startup.wav | App startup |
| login_ok.wav / login_fail.wav | Login |
| barcode.wav | Barcode scan |
| product_add.wav / product_remove.wav | Cart line add/remove |
| sale_complete.wav | Sale recorded |
| void.wav | Void sale |
| pay_cash.wav / pay_mpesa.wav / pay_card.wav / pay_credit.wav | Payment methods |
| low_stock.wav | Low stock (grouped) |
| error.wav / warning.wav / success.wav | Feedback |
| ai_thinking.wav / ai_ready.wav | AI stubs |
| permission.wav | Permission denied |
| dialog_open.wav / dialog_close.wav | Dialogs |
| save.wav / delete.wav | Persist / delete |
| nav.wav / click.wav | Navigation / UI |
| notify.wav | Notifications |

## Themes

JSON maps in `themes/*.json` point events → relative paths. Switch theme in **Settings → Audio** (no code change).

Custom replacements: `%LOCALAPPDATA%\MugoByte\MBT POS\config\audio_custom\` (WAV/OGG/MP3).

## Pixabay / CC0

Dev-time curation may use Pixabay/CC0; replace library files and document here. Runtime remains offline.
