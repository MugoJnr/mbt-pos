import json
import os
from pathlib import Path

from backend.cloud_backup.paths import (
    backup_state_path,
    is_cloud_configured,
    is_logged_in,
    load_cloud_config,
    load_identity,
    load_json,
)
from backend.cloud.platform_service import service_select
from backend.local_db_backup import local_backup_status, get_local_backup_dir


def main() -> None:
    print("=== CLOUD ===")
    print("configured", is_cloud_configured())
    print("logged_in", is_logged_in())
    cfg = load_cloud_config()
    ident = load_identity()
    print("enabled", bool(cfg.get("enabled")))
    print("bucket", cfg.get("bucket"))
    print("device", ident.get("device_id"))
    print("email", ident.get("email"))
    print("user_id", ident.get("user_id"))

    st = load_json(backup_state_path(), {})
    print("state_path", backup_state_path())
    print("state", json.dumps(st, indent=2, default=str)[:2500])

    rows = service_select(
        "backups",
        "select=id,device_id,storage_path,size_bytes,backup_type,reason,created_at,mbt_version"
        "&order=created_at.desc&limit=8",
    ) or []
    print("cloud_backups_count_recent", len(rows))
    for r in rows:
        print(
            f"  {r.get('created_at')} {r.get('reason'):10} "
            f"{r.get('device_id')} {r.get('size_bytes')}B {r.get('storage_path')}"
        )

    print("\n=== LOCAL ===")
    print("dir", get_local_backup_dir())
    print("status", local_backup_status())
    d = Path(get_local_backup_dir())
    if d.exists():
        files = sorted(d.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]
        for f in files:
            if f.is_file():
                print(f"  {f.name} {f.stat().st_size}B")

    print("\n=== LIVE RUN ===")
    try:
        from backend.cloud_backup import get_sync_manager

        sm = get_sync_manager()
        result = sm.run_backup(reason="healthcheck")
        print("run_backup", json.dumps(result, indent=2, default=str)[:2000])
    except Exception as e:
        print("run_backup_ERR", type(e).__name__, e)

    st2 = load_json(backup_state_path(), {})
    print("\nstate_after", json.dumps(st2, indent=2, default=str)[:1500])


if __name__ == "__main__":
    main()
