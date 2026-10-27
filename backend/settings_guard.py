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

# Returned by the shop API only as a yes/no, never as the stored secret.
HIDDEN_SETTING_KEYS = frozenset({
    "superadmin_pin_hash",
    "telegram_bot_token",
    "telegram_chat_id",
    "developer_chat_id",
    "login_lockout_state",
})

# An Admin can edit shop settings. These stay with the Super Admin.
PRIVILEGED_SETTING_KEYS = HIDDEN_SETTING_KEYS


def reject_secret_settings(data: dict) -> dict:
    blocked = sorted(k for k in data if str(k).lower() in BLOCKED_SETTING_KEYS)
    if blocked:
        raise ValueError("Payment provider secrets are not stored in shop settings")
    return data


def reject_privileged_settings(data: dict, role: str) -> dict:
    """Keep PIN and messaging secrets off an Admin settings save."""
    if (role or "").lower() == "superadmin":
        return data
    blocked = sorted(k for k in data if str(k).lower() in PRIVILEGED_SETTING_KEYS)
    if blocked:
        raise ValueError("Only a Super Admin can change that security setting")
    return data


def public_settings(data: dict) -> dict:
    """Settings safe to send to a signed-in shop user."""
    hidden = {str(key).lower() for key in HIDDEN_SETTING_KEYS}
    visible = {
        key: value for key, value in (data or {}).items()
        if str(key).lower() not in hidden
    }
    visible["pin_configured"] = "1" if str((data or {}).get("superadmin_pin_hash") or "").strip() else "0"
    return visible
