"""
MBT POS — Enterprise AI Intelligence Platform (v1)

Adapted from Exam Hub Kenya patterns (OpenRouter gateway, config-only keys,
sanitize/log/retry) for offline-first desktop POS.

Architecture rules:
  • Application code MUST call `AiService` only — never OpenRouter directly.
  • Ops Center uses `get_ai_ops()` which also routes AI via AiService.
  • API keys are vendor-managed (env / AppData admin file). Never shown in cashier UI.
  • POS remains fully usable when AI is offline or unconfigured.

Admin key setup: docs/AI_VENDOR_CONFIG.md
"""
from desktop.utils.ai.service import AiService, get_ai_service
from desktop.utils.ai.connectivity import AiConnectivity

__all__ = ['AiService', 'get_ai_service', 'AiConnectivity']
