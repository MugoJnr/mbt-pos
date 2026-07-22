"""
MBT POS — Legacy Offline License Key Generator (DISABLED BY DEFAULT)

Production licensing is online-only via portal.mugobyte.com (MBT-… keys).
This tool generates local signed keys that POS will reject unless
MBT_ALLOW_LOCAL_KEYS=1 is set on the customer machine.

Do not use for customer licenses. Issue keys from the Portal / license server.

Emergency override (dev/tests only):
    set MBT_ALLOW_LOCAL_KEYGEN=1
    python license_keygen.py --force --device-id <id> --plan basic --days 365
"""
import sys
import os
import argparse
import time
from datetime import datetime, timedelta

# Make licensing importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from licensing.license_engine import (
    generate_license_key, decode_license_key, PLANS, _MASTER_SECRET, _sign
)


def _local_keygen_allowed(force: bool = False) -> bool:
    if force:
        return True
    return (os.environ.get('MBT_ALLOW_LOCAL_KEYGEN') or '').strip() in (
        '1', 'true', 'TRUE', 'yes', 'YES',
    )


def _refuse_and_exit():
    print()
    print("=" * 60)
    print("  Local keygen is DISABLED.")
    print("  Issue online keys from portal.mugobyte.com")
    print("  (Admin -> Licenses / license server).")
    print()
    print("  Dev override only:")
    print("    set MBT_ALLOW_LOCAL_KEYGEN=1")
    print("    python license_keygen.py --force ...")
    print("=" * 60)
    print()
    sys.exit(2)


def banner():
    print()
    print("=" * 60)
    print("  MBT POS — Legacy Key Generator (NOT for production)")
    print("  Prefer portal.mugobyte.com online MBT-… keys")
    print("=" * 60)
    print()


def generate(device_id: str, plan: str, days: int, issued_by: str = 'MugoByte Technologies'):
    key = generate_license_key(device_id, plan, days, issued_by)
    exp = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
    return key, exp


def print_key_block(key: str, device_id: str, plan: str, days: int, exp: str):
    plan_name = PLANS.get(plan, {}).get('name', plan.title())
    print()
    print("  ┌─── LICENSE KEY ─────────────────────────────────┐")
    for i, chunk in enumerate(key.split('-')):
        part = f"  │  {chunk}  │" if i == 0 else f"  │  -{chunk}  │"
    # Print the full key nicely
    print(f"  │")
    print(f"  │  {key}")
    print(f"  │")
    print(f"  ├─── DETAILS ──────────────────────────────────────┤")
    print(f"  │  Plan:      {plan_name}")
    print(f"  │  Duration:  {days} days")
    print(f"  │  Expires:   {exp}")
    print(f"  │  Device:    {device_id[:12]}…")
    print(f"  └──────────────────────────────────────────────────┘")
    print()


def generate_remote_activation_payload(device_id: str, plan: str, days: int) -> dict:
    """Generate a signed payload for remote activation via Telegram."""
    import json, hmac, hashlib
    now = int(time.time())
    days = max(1, int(days))
    payload = {
        'device_id':      device_id,
        'plan':           plan,
        'issued_at':      now,
        'expires_at':     now + days * 86400,
        'duration_days':  days,
        'issued_by':      'MugoByte Technologies',
        'version':        2,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    payload['sig'] = hmac.new(_MASTER_SECRET, raw, hashlib.sha256).hexdigest()
    return payload


def generate_extension_sig(device_id: str, days: int) -> str:
    """Generate a signed extension token for /extend_subscription."""
    import hmac, hashlib
    raw = f"extend:{days}:{device_id}".encode()
    return hmac.new(_MASTER_SECRET, raw, hashlib.sha256).hexdigest()


def generate_revoke_sig(device_id: str) -> str:
    """Generate a signed revocation token."""
    import hmac, hashlib
    raw = f"revoke:{device_id}".encode()
    return hmac.new(_MASTER_SECRET, raw, hashlib.sha256).hexdigest()


def interactive():
    banner()
    print("  [1] Generate license key")
    print("  [2] Generate remote activation payload (Telegram)")
    print("  [3] Generate extension signature")
    print("  [4] Generate revoke signature")
    print("  [5] Decode & verify a key")
    print()

    choice = input("  Choice: ").strip()

    if choice == '1':
        device_id = input("  Device ID (from customer's app): ").strip()
        print(f"  Plans: {', '.join(PLANS.keys())}")
        plan = input("  Plan [basic]: ").strip() or 'basic'
        days = int(input("  Days [365]: ").strip() or '365')
        key, exp = generate(device_id, plan, days)
        print_key_block(key, device_id, plan, days, exp)

    elif choice == '2':
        device_id = input("  Device ID: ").strip()
        plan = input("  Plan [basic]: ").strip() or 'basic'
        days = int(input("  Days [365]: ").strip() or '365')
        import json
        payload = generate_remote_activation_payload(device_id, plan, days)
        print()
        print("  Send this as a Telegram message to your bot:")
        print(f"  __LICPUSH__{json.dumps(payload, separators=(',',':'))}")

    elif choice == '3':
        device_id = input("  Device ID: ").strip()
        days = int(input("  Extension days: ").strip())
        sig = generate_extension_sig(device_id, days)
        print(f"\n  Telegram command:  /extend_subscription {days}")
        print(f"  Signature (internal):  {sig[:20]}…")

    elif choice == '4':
        device_id = input("  Device ID: ").strip()
        sig = generate_revoke_sig(device_id)
        print(f"\n  Telegram command:  /revoke_license")
        print(f"  Signature (internal):  {sig[:20]}…")

    elif choice == '5':
        key = input("  License key to verify: ").strip()
        data = decode_license_key(key)
        if data:
            exp = datetime.fromtimestamp(data['expires_at']).strftime('%Y-%m-%d')
            print(f"\n  ✓  Valid key")
            print(f"     Plan:    {data.get('plan')}")
            print(f"     Expires: {exp}")
            print(f"     Device:  {data.get('device_id','ANY')[:12]}…")
        else:
            print("\n  ✗  Invalid or tampered key")

    print()
    input("  Press Enter to exit…")


def main():
    if len(sys.argv) == 1:
        if not _local_keygen_allowed():
            _refuse_and_exit()
        interactive()
        return

    parser = argparse.ArgumentParser(
        description='Legacy offline keygen (disabled; use Portal online keys)')
    parser.add_argument('--device-id', help='Device fingerprint from customer')
    parser.add_argument('--plan', default='basic', choices=list(PLANS.keys()))
    parser.add_argument('--days', type=int, default=365)
    parser.add_argument('--verify', metavar='KEY', help='Verify an existing key')
    parser.add_argument(
        '--force', action='store_true',
        help='Allow local keygen despite online-only policy (dev/tests only)',
    )
    args = parser.parse_args()

    if args.verify:
        data = decode_license_key(args.verify)
        if data:
            print(f"VALID: plan={data['plan']} expires={datetime.fromtimestamp(data['expires_at']).date()}")
        else:
            print("INVALID")
        return

    if not args.device_id:
        parser.error('--device-id is required unless --verify is used')

    if not _local_keygen_allowed(force=args.force):
        _refuse_and_exit()

    key, exp = generate(args.device_id, args.plan, args.days)
    print(f"KEY={key}")
    print(f"EXPIRES={exp}")
    print("NOTE: POS rejects this key unless MBT_ALLOW_LOCAL_KEYS=1 on the device.")


if __name__ == '__main__':
    main()
