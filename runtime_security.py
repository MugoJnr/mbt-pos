"""Runtime-only security configuration for MBT POS and Portal.

Secrets are loaded from environment variables in production. Desktop/local
installs get a stable per-install secret in the writable data directory. No
secret defined here is suitable for bundling into an installer or container.
"""
from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path


def _is_production() -> bool:
    return os.environ.get("MBT_ENV", "").strip().lower() in {
        "prod",
        "production",
    }


def _secret_file(name: str) -> Path:
    from mbt_paths import ensure_data_dirs, get_project_root

    root = Path(ensure_data_dirs(get_project_root()))
    return root / "config" / name


_SECRET_CACHE: dict[tuple[str, str], str] = {}


def reset_secret_cache() -> None:
    """Drop memoized on-disk secrets (tests that relocate the data root)."""
    _SECRET_CACHE.clear()


def _read_or_create_secret(env_name: str, filename: str, *, min_length: int = 32) -> str:
    configured = os.environ.get(env_name, "").strip()
    if configured:
        if len(configured) < min_length:
            raise RuntimeError(f"{env_name} must be at least {min_length} characters")
        return configured

    if _is_production():
        raise RuntimeError(f"{env_name} is required when MBT_ENV=production")

    # Cached: the identity cipher derives from this on every protected field,
    # so re-reading it kept re-resolving the data root from the UI thread.
    cache_key = (env_name, filename)
    cached = _SECRET_CACHE.get(cache_key)
    if cached is not None:
        return cached

    path = _secret_file(filename)
    try:
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= min_length:
            _SECRET_CACHE[cache_key] = value
            return value
    except FileNotFoundError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(48)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value, encoding="utf-8")
    try:
        os.chmod(tmp, stat.S_IREAD | stat.S_IWRITE)
    except OSError:
        pass
    os.replace(tmp, path)
    _SECRET_CACHE[cache_key] = value
    return value


def get_jwt_secret() -> str:
    """Stable local JWT secret; mandatory environment secret in production."""
    return _read_or_create_secret("MBT_JWT_SECRET", ".jwt_secret")


def get_activation_hmac_secret() -> str:
    """Server-side activation HMAC secret. Never expose to a desktop client."""
    return _read_or_create_secret(
        "MBT_ACTIVATION_HMAC_SECRET",
        ".activation_hmac_secret",
    )
