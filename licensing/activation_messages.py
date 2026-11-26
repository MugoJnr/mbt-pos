"""Plain next steps for a shop owner. Technical detail stays in the log."""
from __future__ import annotations


def explain_activation_failure(message: str) -> str:
    """Turn a licence or network error into one action the owner can take.

    Success text is returned unchanged. A failure never says only "Activation failed".
    """
    text = ' '.join(str(message or '').split())
    low = text.lower()
    if not text:
        return (
            "This computer was not activated. Connect to the internet and try again. "
            "If it still fails, open portal.mugobyte.com and confirm a licence is assigned to this email."
        )
    if low.startswith('license activated') or low.startswith('cloud license activated') or 'already activated' in low:
        return text
    if any(word in low for word in (
        'timed out', 'timeout', 'connection', 'network', 'unreachable',
        'name or service', 'max retries', 'temporarily unavailable', 'ssl',
    )):
        return (
            "MugoByte Workspace did not answer. This computer was not activated, and no extra computer seat was used. "
            "Check the internet, then press Activate again."
        )
    if any(word in low for word in ('not verified', 'verify your email', 'verification', 'confirm your email')):
        return (
            "The business email is not confirmed yet. Open the message from MugoByte, confirm the email, then press Activate again. "
            "Cashiers do not need their own Portal account."
        )
    if 'revoked' in low or 'suspended' in low:
        return (
            "MugoByte has stopped this licence. The shop records already on this computer are unchanged. "
            "Ask MugoByte to restore the licence, then activate this computer again."
        )
    if 'expired' in low:
        return (
            "This licence has expired. The shop records already on this computer are unchanged. "
            "Renew it in the Portal, then activate this computer again."
        )
    if any(word in low for word in (
        'no free', 'no seat', 'all seats', 'seats are', 'maximum', 'max device', 'no device seat',
    )):
        return (
            "Every computer allowed by this plan is already in use. This computer was not added. "
            "In the Portal, release an old computer or transfer its licence to this one, then try again."
        )
    if 'different device' in low or 'another device' in low or 'bound to' in low or 'transfer' in low:
        return (
            "This licence is already on a different computer. "
            "In the Portal, transfer or release that computer, then activate this one."
        )
    if 'not found' in low or 'no license' in low or 'no licence' in low or 'not reserved' in low:
        return (
            "No licence is assigned to this email yet. "
            "Ask MugoByte to assign a plan in the Portal, then paste that licence key and activate again."
        )
    if 'invalid' in low or 'format' in low or 'no longer accepted' in low:
        return (
            "That key was not accepted. Paste the licence key from portal.mugobyte.com. It starts with MBT-. "
            "A cashier password is not a licence key."
        )
    if text.lower() == 'activation failed':
        return (
            "This computer was not activated. Connect to the internet and try again. "
            "If the Portal shows no free computer on this plan, release an old computer first."
        )
    return text
