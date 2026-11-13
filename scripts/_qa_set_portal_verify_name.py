#!/usr/bin/env python3
"""Set a human display name on the QA portal.verify account (not a secret change)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

UID = "a4cd545c-9929-4050-8805-8392c79e7f06"  # portal.verify.july20c@gmail.com
NAME = "Amina Otieno"


def main() -> int:
    cfg = json.loads(
        (
            Path(os.environ["LOCALAPPDATA"])
            / "MugoByte"
            / "MBT POS"
            / "config"
            / "cloud_config.json"
        ).read_text(encoding="utf-8")
    )
    url = cfg["supabase_url"].rstrip("/")
    key = cfg["service_key"]
    H = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    r = requests.put(
        f"{url}/auth/v1/admin/users/{UID}",
        headers=H,
        json={
            "user_metadata": {"full_name": NAME, "name": NAME},
            "app_metadata": {},
        },
        timeout=30,
    )
    print("admin_update", r.status_code, r.text[:400])
    # also patch organizations owner display if stored elsewhere — optional
    return 0 if r.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
