# MBT POS — Vendor AI Key Configuration (Administrators only)

**Cashiers never see API keys in Settings or the UI.**

Keys are vendor-managed (same pattern as Exam Hub Kenya OpenRouter integration).

## Exam Hub reference

Studied and adapted from:

`C:\Users\mugoj\OneDrive\Desktop\examhub-kenya\backend\src\ai\`

- `providers/openrouter.ts` — HTTP OpenRouter client
- `config.ts` — env-only models/keys
- `service.ts` — single gateway
- `security.ts` — sanitize I/O
- `logger.ts` — usage logging

MBT POS adapts these for offline-first desktop (PyQt + local SQLite). Modules must call `desktop.utils.ai.AiService` / `desktop.utils.ai.ops.get_ai_ops()` only — never OpenRouter directly.

## How to configure the key (admin / vendor)

Resolution order:

1. Environment variables (preferred for vendor servers / IT images):
   - `MBT_OPENROUTER_API_KEY` or `OPENROUTER_API_KEY`
   - Optional: `MBT_AI_MODEL`, `MBT_AI_TIMEOUT_SEC`, `OPENROUTER_BASE_URL`
2. DPAPI-protected AppData file (Windows user-scoped):
   - `%LOCALAPPDATA%\MugoByte\MBT POS\config\vendor_ai.bin`
3. Local-dev fallback JSON (still not shown in cashier Settings):
   - `%LOCALAPPDATA%\MugoByte\MBT POS\config\vendor_ai.local.json`

### Save via Python (admin machine)

```python
from desktop.utils.ai.config import save_vendor_api_key
save_vendor_api_key("sk-or-v1-YOUR_KEY")
```

Or create `vendor_ai.local.json`:

```json
{
  "provider": "openrouter",
  "api_key": "sk-or-v1-YOUR_KEY"
}
```

Restart MBT POS (or RUN_DEV) after setting the key.

## Offline behavior

POS sales/inventory work without AI. The floating assistant and AI Operations Center show:

> AI features temporarily unavailable

and auto-reconnect via a background watcher.

## Related modules

| Area | Path |
|------|------|
| AI gateway | `desktop/utils/ai/service.py` |
| OpenRouter provider | `desktop/utils/ai/provider_openrouter.py` |
| Floating assistant | `desktop/widgets/ai_assistant.py` |
| AI Operations | `desktop/utils/ai/ops/` + `desktop/tabs/ai_ops_tab.py` |
| Prompt library | `desktop/utils/ai/prompts/library.json` |
