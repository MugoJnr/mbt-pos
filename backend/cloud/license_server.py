"""
MBT Cloud — License Server.
Cloud licensing with trial/monthly/annual/lifetime plans.
Replaces Telegram-based license admin commands.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any
from runtime_security import get_activation_hmac_secret

logger = logging.getLogger('cloud.license')

PLANS = {
    'trial': {'days': 30, 'max_devices': 1, 'max_products': 100, 'max_users': 2},
    'basic': {'days': 30, 'max_devices': 1, 'max_products': 500, 'max_users': 5},
    'pro': {'days': 30, 'max_devices': 3, 'max_products': 5000, 'max_users': 20},
    'monthly': {'days': 30, 'max_devices': 2, 'max_products': 2000, 'max_users': 10},
    'annual': {'days': 365, 'max_devices': 3, 'max_products': 5000, 'max_users': 20},
    'lifetime': {'days': 36500, 'max_devices': 5, 'max_products': 99999, 'max_users': 50},
}

LICENSE_STATUSES = ('active', 'suspended', 'expired', 'revoked', 'trial')


def generate_license_key(plan: str = 'trial') -> str:
    """Generate a unique license key."""
    prefix = plan.upper()[:3]
    token = secrets.token_hex(12).upper()
    return f'MBT-{prefix}-{token[:4]}-{token[4:8]}-{token[8:12]}'


def generate_activation_token(license_key: str, device_id: str, secret: str = '') -> str:
    """Generate a secure activation token for a device."""
    payload = f'{license_key}:{device_id}:{datetime.now().strftime("%Y%m%d")}'
    signing_secret = secret or get_activation_hmac_secret()
    return hmac.new(
        signing_secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]


class CloudLicenseServer:
    """Manages licenses in Supabase cloud (service-role for server APIs)."""

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            from backend.cloud_backup.supabase_client import SupabaseClient
            self._client = SupabaseClient()
        return self._client

    def _rows(self, table: str, query: str) -> list:
        from backend.cloud.platform_service import service_select
        return service_select(table, query)

    def _insert(self, table: str, row: dict, upsert: bool = False, on_conflict: str = ''):
        from backend.cloud.platform_service import service_insert
        return service_insert(table, row, upsert=upsert, on_conflict=on_conflict)

    def _update(self, table: str, query: str, patch: dict):
        from backend.cloud.platform_service import service_update
        return service_update(table, query, patch)

    def create_license(self, org_id: str, plan: str = 'monthly', max_devices: int | None = None,
                       notes: str = '', created_by: str | None = None) -> dict:
        """Create a paid plan license. No customer free-trial by default."""
        plan_info = PLANS.get(plan) or PLANS['monthly']
        key = generate_license_key(plan if plan in PLANS else 'monthly')
        expires = datetime.now() + timedelta(days=plan_info['days'])
        devices = max_devices or plan_info['max_devices']

        row = {
            'org_id': org_id,
            'license_key': key,
            'plan': plan if plan in PLANS else 'monthly',
            'status': 'active',
            'max_devices': devices,
            'activated_devices': 0,
            'expires_at': expires.isoformat(),
            'notes': notes,
        }
        if created_by:
            row['created_by'] = created_by

        result = self._insert('licenses', row)
        lid = result.get('id') if isinstance(result, dict) else None
        if lid:
            self._log_history(lid, 'created', created_by, {'plan': plan, 'key': key})
        return result

    def activate(self, license_key: str, device_id: str, org_id: str) -> tuple[bool, str, dict | None]:
        from urllib.parse import quote
        rows = self._rows('licenses', f'license_key=eq.{quote(license_key, safe="")}&select=*')
        if not rows:
            return False, 'License key not found', None
        lic = rows[0]

        if lic['status'] in ('revoked', 'suspended'):
            return False, f'License is {lic["status"]}', None
        if lic.get('expires_at'):
            try:
                exp = datetime.fromisoformat(str(lic['expires_at']).replace('Z', '+00:00').replace('+00:00', ''))
                if exp.replace(tzinfo=None) < datetime.now():
                    return False, 'License expired', None
            except Exception:
                pass
        if lic.get('activated_devices', 0) >= lic.get('max_devices', 1):
            # Allow re-activation of same device
            existing = self._rows(
                'license_activations',
                f'license_id=eq.{lic["id"]}&device_id=eq.{quote(device_id, safe="")}&is_active=eq.true&select=*',
            )
            if not existing:
                return False, f'Device limit reached ({lic["max_devices"]})', None
            return True, 'Already activated', {
                'token': existing[0].get('activation_token'),
                'plan': lic['plan'],
                'expires_at': lic.get('expires_at'),
            }

        token = generate_activation_token(license_key, device_id)
        self._insert('license_activations', {
            'license_id': lic['id'],
            'device_id': device_id,
            'org_id': org_id,
            'activation_token': token,
            'is_active': True,
        }, upsert=True, on_conflict='license_id,device_id')
        self._update('licenses', f'id=eq.{lic["id"]}', {
            'activated_devices': int(lic.get('activated_devices') or 0) + 1,
            'activated_at': datetime.now().isoformat(),
            'status': 'active',
        })
        self._log_history(lic['id'], 'activated', None, {'device_id': device_id})
        return True, 'Activated', {'token': token, 'plan': lic['plan'], 'expires_at': lic.get('expires_at')}

    def validate(self, license_key: str, device_id: str) -> tuple[bool, str, dict | None]:
        from urllib.parse import quote
        rows = self._rows('licenses', f'license_key=eq.{quote(license_key, safe="")}&select=*')
        if not rows:
            return False, 'Invalid license', None
        lic = rows[0]
        if lic['status'] != 'active':
            return False, f'License {lic["status"]}', None

        activations = self._rows(
            'license_activations',
            f'license_id=eq.{lic["id"]}&device_id=eq.{quote(device_id, safe="")}&is_active=eq.true&select=*',
        )
        if not activations:
            return False, 'Device not activated', None

        self._update('license_activations', f'id=eq.{activations[0]["id"]}', {
            'last_validated_at': datetime.now().isoformat(),
        })
        return True, 'Valid', {
            'plan': lic['plan'],
            'expires_at': lic.get('expires_at'),
            'max_devices': lic.get('max_devices'),
        }

    def suspend(self, license_id: str, actor: str | None = None) -> bool:
        self._update('licenses', f'id=eq.{license_id}', {'status': 'suspended'})
        # Stop activations immediately so validate() and re-activate cannot succeed.
        try:
            self._update('license_activations', f'license_id=eq.{license_id}', {'is_active': False})
        except Exception as e:
            logger.warning('suspend activations clear failed: %s', e)
        self._log_history(license_id, 'suspended', actor)
        return True

    def unsuspend(self, license_id: str, actor: str | None = None) -> bool:
        rows = self._rows('licenses', f'id=eq.{license_id}&select=status,expires_at')
        if not rows:
            return False
        if rows[0].get('status') != 'suspended':
            return False
        self._update('licenses', f'id=eq.{license_id}', {'status': 'active'})
        self._log_history(license_id, 'unsuspended', actor)
        return True

    def revoke(self, license_id: str, actor: str | None = None) -> bool:
        self._update('licenses', f'id=eq.{license_id}', {
            'status': 'revoked',
            'revoked_at': datetime.now().isoformat(),
        })
        try:
            self._update('license_activations', f'license_id=eq.{license_id}', {'is_active': False})
        except Exception as e:
            logger.warning('revoke activations clear failed: %s', e)
        self._log_history(license_id, 'revoked', actor)
        return True

    def renew(self, license_id: str, days: int = 30, actor: str | None = None) -> bool:
        rows = self._rows('licenses', f'id=eq.{license_id}&select=expires_at')
        if not rows:
            return False
        current = rows[0].get('expires_at')
        try:
            base = datetime.fromisoformat(str(current).replace('Z', '')) if current else datetime.now()
        except Exception:
            base = datetime.now()
        if base < datetime.now():
            base = datetime.now()
        new_expiry = base + timedelta(days=days)
        self._update('licenses', f'id=eq.{license_id}', {
            'expires_at': new_expiry.isoformat(),
            'status': 'active',
        })
        self._log_history(license_id, 'renewed', actor, {'days': days, 'new_expiry': new_expiry.isoformat()})
        return True

    def transfer_device(self, license_id: str, old_device_id: str, new_device_id: str, actor: str | None = None) -> tuple[bool, str]:
        from urllib.parse import quote
        self._update(
            'license_activations',
            f'license_id=eq.{license_id}&device_id=eq.{quote(old_device_id, safe="")}',
            {'is_active': False},
        )
        token = generate_activation_token('', new_device_id)
        # Need org_id for activation
        lic = self._rows('licenses', f'id=eq.{license_id}&select=org_id')
        org_id = (lic[0].get('org_id') if lic else '') or ''
        self._insert('license_activations', {
            'license_id': license_id,
            'device_id': new_device_id,
            'org_id': org_id,
            'activation_token': token,
            'is_active': True,
        }, upsert=True, on_conflict='license_id,device_id')
        self._log_history(license_id, 'transferred', actor, {'from': old_device_id, 'to': new_device_id})
        return True, 'Device transferred'

    def list_licenses(self, org_id: str) -> list[dict]:
        return self._rows('licenses', f'org_id=eq.{org_id}&select=*&order=created_at.desc')

    def get_history(self, license_id: str) -> list[dict]:
        return self._rows('license_history', f'license_id=eq.{license_id}&select=*&order=created_at.desc')

    def _log_history(self, license_id: str, action: str, actor: str | None = None, details: dict | None = None):
        try:
            self._insert('license_history', {
                'license_id': license_id,
                'action': action,
                'actor_user_id': actor,
                'details': details or {},
            })
        except Exception as e:
            logger.debug('License history log skipped: %s', e)


_server: CloudLicenseServer | None = None


def get_license_server() -> CloudLicenseServer:
    global _server
    if _server is None:
        _server = CloudLicenseServer()
    return _server
