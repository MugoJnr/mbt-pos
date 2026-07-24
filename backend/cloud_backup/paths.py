"""
AppData paths for Cloud Backup config & identity.

Shop installs get production Portal URL + public anon key from
``backend.cloud_backup.defaults`` when AppData has no cloud_config yet.
Never ship the service-role key in the installer — only example /
public defaults live in the repo.
"""
from __future__ import annotations

import json
import logging
import os
import base64
import hashlib
from typing import Any
from cryptography.fernet import Fernet, InvalidToken

from mbt_paths import ensure_data_dirs, get_project_root
from runtime_security import get_jwt_secret
from backend.cloud_backup.defaults import production_cloud_defaults

logger = logging.getLogger('cloud_backup.paths')

CLOUD_CONFIG_NAME = 'cloud_config.json'
CLOUD_IDENTITY_NAME = 'cloud_identity.json'
CLOUD_QUEUE_NAME = 'cloud_offline_queue.json'
CLOUD_STATE_NAME = 'cloud_backup_state.json'

_UNCONFIGURED_MSG = (
    'Could not reach MugoByte Cloud on this PC. '
    'Check your internet connection, then sign in with your portal.mugobyte.com '
    'email and password. If this keeps failing, contact MugoByte support.'
)


def config_dir() -> str:
    root = ensure_data_dirs(get_project_root())
    path = os.path.join(root, 'config')
    os.makedirs(path, exist_ok=True)
    return path


def cloud_config_path() -> str:
    return os.path.join(config_dir(), CLOUD_CONFIG_NAME)


def cloud_identity_path() -> str:
    return os.path.join(config_dir(), CLOUD_IDENTITY_NAME)


def offline_queue_path() -> str:
    return os.path.join(config_dir(), CLOUD_QUEUE_NAME)


def backup_state_path() -> str:
    return os.path.join(config_dir(), CLOUD_STATE_NAME)


def _atomic_write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, path)


def load_json(path: str, default: dict | None = None) -> dict:
    default = default if default is not None else {}
    if not os.path.isfile(path):
        return dict(default)
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else dict(default)
    except Exception as e:
        logger.warning('Failed to load %s: %s', path, e)
        return dict(default)


def save_json(path: str, data: dict) -> None:
    try:
        _atomic_write_json(path, data)
    except Exception as e:
        logger.error('Failed to save %s: %s', path, e)
        raise


def ensure_production_cloud_config(*, persist: bool = True) -> dict[str, Any]:
    """
    Fill missing supabase_url / anon_key from production defaults and
    optionally write AppData cloud_config.json so shop PCs are ready
    for Portal sign-in without a manual config step.

    Env overrides (MBT_SUPABASE_*) still win in load_cloud_config().
    Never invents or writes a service_key.
    """
    path = cloud_config_path()
    defaults = production_cloud_defaults()
    cfg = load_json(path, {})
    changed = False

    if not str(cfg.get('supabase_url') or '').strip():
        cfg['supabase_url'] = defaults['supabase_url']
        changed = True
    if not str(cfg.get('anon_key') or '').strip():
        cfg['anon_key'] = defaults['anon_key']
        changed = True
    for key in ('project_ref', 'project_name', 'bucket'):
        if not str(cfg.get(key) or '').strip():
            cfg[key] = defaults[key]
            changed = True
    if 'enabled' not in cfg:
        cfg['enabled'] = True
        changed = True
    if not cfg.get('backup_interval_minutes'):
        cfg['backup_interval_minutes'] = defaults['backup_interval_minutes']
        changed = True
    if 'service_key' not in cfg:
        cfg['service_key'] = ''
        changed = True

    if persist and (changed or not os.path.isfile(path)):
        try:
            save_json(path, cfg)
            logger.info('Seeded production cloud_config.json at %s', path)
        except Exception as e:
            logger.warning('Could not persist cloud_config.json: %s', e)
    return cfg


def load_cloud_config() -> dict[str, Any]:
    """
    Resolve Supabase URL + keys from (priority):
      1. Env: MBT_SUPABASE_URL, MBT_SUPABASE_ANON_KEY, MBT_SUPABASE_SERVICE_KEY
      2. AppData config/cloud_config.json
      3. Built-in production Portal defaults (public URL + anon key)
    Never logs secret values.
    """
    # Seed AppData on first run so frozen shop installs match Portal.
    ensure_production_cloud_config(persist=True)

    cfg = load_json(cloud_config_path(), {
        'supabase_url': '',
        'anon_key': '',
        'service_key': '',
        'enabled': False,
        'backup_interval_minutes': 5,
        'bucket': 'mbt-backups',
    })
    defaults = production_cloud_defaults()
    if not str(cfg.get('supabase_url') or '').strip():
        cfg['supabase_url'] = defaults['supabase_url']
    if not str(cfg.get('anon_key') or '').strip():
        cfg['anon_key'] = defaults['anon_key']
    if not str(cfg.get('project_ref') or '').strip():
        cfg['project_ref'] = defaults['project_ref']
    if not str(cfg.get('bucket') or '').strip():
        cfg['bucket'] = defaults['bucket']

    env_url = os.environ.get('MBT_SUPABASE_URL', '').strip()
    env_anon = os.environ.get('MBT_SUPABASE_ANON_KEY', '').strip()
    env_svc = os.environ.get('MBT_SUPABASE_SERVICE_KEY', '').strip()
    if env_url:
        cfg['supabase_url'] = env_url
    if env_anon:
        cfg['anon_key'] = env_anon
    if env_svc:
        cfg['service_key'] = env_svc
    cfg['supabase_url'] = (cfg.get('supabase_url') or '').rstrip('/')
    cfg['backup_interval_minutes'] = int(cfg.get('backup_interval_minutes') or 5)
    cfg['bucket'] = cfg.get('bucket') or 'mbt-backups'
    return cfg


def save_cloud_config(cfg: dict) -> None:
    # Strip empty service_key writes that might wipe env-only setups? Keep as-is.
    save_json(cloud_config_path(), cfg)


def cloud_unconfigured_message() -> str:
    return _UNCONFIGURED_MSG


def _identity_cipher() -> Fernet:
    material = hashlib.sha256(
        (get_jwt_secret() + ':cloud-identity:v1').encode()
    ).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def _protect(value: str) -> str:
    if not value:
        return ''
    return _identity_cipher().encrypt(value.encode()).decode()


def _unprotect(value: str) -> str:
    if not value:
        return ''
    try:
        return _identity_cipher().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        logger.warning('Protected cloud identity token could not be decrypted')
        return ''


def load_identity() -> dict[str, Any]:
    identity = load_json(cloud_identity_path(), {
        'device_id': '',
        'business_id': '',
        'business_name': '',
        'user_id': '',
        'email': '',
        'access_token': '',
        'refresh_token': '',
        'encryption_salt': '',
        'cloud_skipped': False,
        'created_at': '',
    })
    migrated = False
    for name in ('access_token', 'refresh_token', 'activation_token'):
        protected_name = f'{name}_protected'
        plaintext = str(identity.get(name) or '')
        if plaintext:
            identity[protected_name] = _protect(plaintext)
            identity[name] = ''
            migrated = True
        identity[name] = _unprotect(str(identity.get(protected_name) or ''))
    if migrated:
        save_identity(identity)
    return identity


def save_identity(identity: dict) -> None:
    stored = dict(identity)
    for name in ('access_token', 'refresh_token', 'activation_token'):
        plaintext = str(stored.pop(name, '') or '')
        protected_name = f'{name}_protected'
        if plaintext:
            stored[protected_name] = _protect(plaintext)
        elif protected_name not in stored:
            stored[protected_name] = ''
    save_json(cloud_identity_path(), stored)


def is_cloud_configured() -> bool:
    cfg = load_cloud_config()
    return bool(cfg.get('supabase_url') and cfg.get('anon_key'))


def is_logged_in() -> bool:
    ident = load_identity()
    return bool(ident.get('access_token') and ident.get('business_id'))
