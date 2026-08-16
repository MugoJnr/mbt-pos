"""Local desktop QA login — dev bootstrap gated by MBT_QA_ALLOW_DEV_BOOTSTRAP."""
from __future__ import annotations

import os


def _qa_dev_bootstrap_allowed() -> bool:
    return os.environ.get("MBT_QA_ALLOW_DEV_BOOTSTRAP", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def ensure_qa_bootstrap_env() -> None:
    """Seed admin via MBT_BOOTSTRAP_ADMIN_PASSWORD when QA dev mode is enabled."""
    if os.environ.get("MBT_BOOTSTRAP_ADMIN_PASSWORD"):
        return
    if not _qa_dev_bootstrap_allowed():
        raise RuntimeError(
            "Set MBT_BOOTSTRAP_ADMIN_PASSWORD or MBT_QA_ALLOW_DEV_BOOTSTRAP=1 for local QA harness"
        )
    os.environ["MBT_BOOTSTRAP_ADMIN_PASSWORD"] = "admin123"


def qa_admin_user() -> str:
    return (os.environ.get("MBT_BOOTSTRAP_ADMIN_USER") or "admin").strip()


def qa_admin_password() -> str:
    ensure_qa_bootstrap_env()
    return (os.environ.get("MBT_BOOTSTRAP_ADMIN_PASSWORD") or "").strip()


def qa_login(api):
    return api.login(qa_admin_user(), qa_admin_password())
