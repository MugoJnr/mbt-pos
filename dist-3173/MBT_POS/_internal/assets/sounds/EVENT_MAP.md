# MBT POS Audio — Event Map (v2.3.77)

Single entry point: `from desktop.utils.audio_manager import play` / `AudioManager.instance().play(event)`.

| Event | Priority | Category | Cooldown | Notes |
|-------|----------|----------|----------|-------|
| startup | medium | system | 2s | Main window ready |
| login_success | medium | system | 500ms | Login OK |
| login_fail | high | alerts | 800ms | Bad credentials |
| barcode_scan | medium | pos | **80ms** | Throttled rapid scans |
| product_add | medium | pos | 60ms | Tap product card |
| product_remove | low | pos | 80ms | Remove cart line |
| sale_complete | high | pos | 400ms | After successful sale |
| void | critical | pos | 500ms | Interrupts lower |
| payment_cash / mpesa / card / credit | medium | payments | 200ms | Via `play_payment(method)` |
| low_stock | high | alerts | 3s | **Grouped** debounce ~2.5s |
| error | critical | alerts | 5s | Always with UI message |
| warning | high | alerts | 3s | Always with UI message |
| success | medium | ui | 250ms | Generic success |
| ai_thinking / ai_ready | low | ai | 10s / 2s | Assistant stubs |
| permission_denied | high | alerts | 1.5s | + Access Denied dialog |
| dialog_open / close | low | ui | 50ms | Optional |
| save | medium | ui | 400ms | Identical spam → one |
| delete | high | ui | 400ms | |
| nav_switch | low | ui | 120ms | Muted in Focus Mode |
| click | low | ui | 50ms | Muted in Focus Mode |
| notification | medium | alerts | 800ms | |
| accounting_post | medium | system | 500ms | Journal posted |

## Themes (`assets/sounds/themes/`)

`professional` (default), `minimal`, `retail`, `supermarket`, `pharmacy`, `restaurant`, `warehouse`, `silent`.

## Change theme

**Settings → Audio Experience → Sound theme** → Apply Audio Settings (or Save All Settings).

No code change. Custom WAV/OGG/MP3: Replace… → `%LOCALAPPDATA%\MugoByte\MBT POS\config\audio_custom\`.

## Collision modes

- **Focus Mode** — mutes nav/click/dialog/AI chrome
- **Presentation Mode** — sale / payment / barcode / product_add / void / error / critical only
- **Quiet Hours** — non-critical muted or attenuated
- **Hardware beeps** — skip software duplicate for scanner / printer / drawer / card
- **Priority** — Critical interrupts; Low never interrupts High+
- **Queue** — max concurrent low; discard obsolete identical queued events

## Accessibility

Never audio-only for critical info. Mute all + Reduced audio supported.
