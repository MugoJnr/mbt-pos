"""Shop settings must not store Daraja secrets."""

BLOCKED_SETTING_KEYS = frozenset({
    "daraja_consumer_key",
    "daraja_consumer_secret",
    "daraja_passkey",
    "mpesa_consumer_secret",
    "mpesa_passkey",
    "initiator_password",
    "security_credential",
})


def reject_secret_settings(data: dict) -> dict:
    blocked = sorted(k for k in data if str(k).lower() in BLOCKED_SETTING_KEYS)
    if blocked:
        raise ValueError("Payment provider secrets are not stored in shop settings")
    return data
