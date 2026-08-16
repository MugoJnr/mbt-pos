"""Shared E2E / ops credentials — never hardcode production secrets in scripts."""
from __future__ import annotations

import os
import sys


def e2e_admin_email() -> str:
    return (os.environ.get("MBT_E2E_ADMIN_EMAIL") or "").strip()


def e2e_admin_password() -> str:
    return (os.environ.get("MBT_E2E_ADMIN_PASSWORD") or "").strip()


def e2e_testshop_email() -> str:
    return (os.environ.get("MBT_E2E_TESTSHOP_EMAIL") or "").strip()


def e2e_testshop_password() -> str:
    return (os.environ.get("MBT_E2E_TESTSHOP_PASSWORD") or "").strip()


def require_e2e_admin() -> tuple[str, str]:
    email = e2e_admin_email()
    password = e2e_admin_password()
    if not email or not password:
        print(
            "Set MBT_E2E_ADMIN_EMAIL and MBT_E2E_ADMIN_PASSWORD before running this script.",
            file=sys.stderr,
        )
        sys.exit(2)
    return email, password


def require_e2e_testshop() -> tuple[str, str]:
    email = e2e_testshop_email()
    password = e2e_testshop_password()
    if not email or not password:
        print(
            "Set MBT_E2E_TESTSHOP_EMAIL and MBT_E2E_TESTSHOP_PASSWORD before running this script.",
            file=sys.stderr,
        )
        sys.exit(2)
    return email, password
