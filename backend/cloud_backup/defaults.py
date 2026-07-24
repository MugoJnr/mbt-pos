"""
Production MugoByte Cloud endpoints for shop installs.

The Supabase *anon* key is a public client credential (same class as a
browser SPA key). It is safe and required to ship inside the desktop
installer so Portal sign-in / license activation works on a fresh PC.

Never put the service-role key here. Service keys stay on the Portal
server / developer machines only (env or local cloud_config.json).
"""
from __future__ import annotations

from typing import Any

# MugoByte production Supabase project (portal.mugobyte.com backend).
PRODUCTION_SUPABASE_URL = 'https://uynfglgttkaibyeglsrt.supabase.co'
PRODUCTION_PROJECT_REF = 'uynfglgttkaibyeglsrt'
PRODUCTION_ANON_KEY = (
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.'
    'eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InV5bmZnbGd0dGthaWJ5ZWdsc3J0Iiwicm9sZSI6'
    'ImFub24iLCJpYXQiOjE3ODQzNzEzODAsImV4cCI6MjA5OTk0NzM4MH0.'
    'nRuhFyoBFgdN0U2vdw0P9gOBWzNQd7i5DNVpwYLEUK4'
)


def production_cloud_defaults() -> dict[str, Any]:
    """Public Portal cloud config for shop PCs (no service_key)."""
    return {
        'supabase_url': PRODUCTION_SUPABASE_URL,
        'anon_key': PRODUCTION_ANON_KEY,
        'service_key': '',
        'project_ref': PRODUCTION_PROJECT_REF,
        'project_name': 'mbt-pos',
        'enabled': True,
        'backup_interval_minutes': 5,
        'bucket': 'mbt-backups',
    }
