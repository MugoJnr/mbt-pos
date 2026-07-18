"""
MBT Cloud Backup & Restore (Supabase) — local-first disaster recovery.

v1: encrypted full SQLite snapshots to Supabase Storage + metadata rows,
device registration, business auth, Settings dashboard, setup-wizard hooks.
Incremental row-level sync hooks exist for products/sales/customers (future).
"""
from __future__ import annotations

SCHEMA_VERSION = 1  # bump when backup payload format changes incompatibly

__all__ = [
    'SCHEMA_VERSION',
    'get_sync_manager',
    'start_cloud_backup_service',
    'stop_cloud_backup_service',
]


def get_sync_manager():
    from backend.cloud_backup.sync_manager import SyncManager
    return SyncManager.instance()


def start_cloud_backup_service(**kwargs):
    from backend.cloud_backup.sync_manager import SyncManager
    return SyncManager.instance().start(**kwargs)


def stop_cloud_backup_service():
    from backend.cloud_backup.sync_manager import SyncManager
    SyncManager.instance().stop()
