# M-Pesa / MugoByte Payments — Phase A–O certification notes
#
# Authoritative source: extracted/mbt_pos_v3071_cert (v3.0.77)
# Branch: feature/mpesa-payment-subsystem
#
# Architecture:
#   Checkout UI → PaymentService → MpesaProvider → payments.mugobyte.com → Daraja
#   Till/C2B webhooks → cloud incoming → local match → VERIFIED → create_sale() ONCE
#
# Non-negotiables enforced in code:
#   - Daraja request_accepted ≠ paid
#   - UNIQUE provider_reference
#   - Ambiguous matches → needs_confirmation (never auto)
#   - Under/overpay not silent
#   - Additive schema only
#   - Remote revoke_license durable local receipt + atomic claim
