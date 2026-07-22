"""Fast, dependency-free checks for Supabase migration hygiene."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"
NAME_RE = re.compile(r"^\d{14}_[a-z0-9_]+\.sql$")
POLICY_RE = re.compile(
    r"create\s+policy\s+(?P<name>\"[^\"]+\"|[a-z0-9_]+)\s+on\s+"
    r"(?P<table>[a-z0-9_.]+)",
    re.IGNORECASE,
)
SECRET_RE = re.compile(
    r"(service_role|supabase_service_key|db_password)\s*[:=]\s*['\"][^$<]",
    re.IGNORECASE,
)


def main() -> int:
    errors: list[str] = []
    files = sorted(MIGRATIONS.glob("*.sql"))
    if not files:
        errors.append("no migration files found")

    timestamps: set[str] = set()
    for path in files:
        if not NAME_RE.fullmatch(path.name):
            errors.append(f"{path.name}: expected 14-digit timestamped filename")
        timestamp = path.name[:14]
        if timestamp in timestamps:
            errors.append(f"{path.name}: duplicate migration timestamp")
        timestamps.add(timestamp)

        sql = path.read_text(encoding="utf-8")
        lowered = sql.lower()
        if "begin;" not in lowered or "commit;" not in lowered:
            errors.append(f"{path.name}: migration must be transactional")
        if SECRET_RE.search(sql):
            errors.append(f"{path.name}: possible embedded secret")

        for match in POLICY_RE.finditer(sql):
            name = match.group("name")
            table = match.group("table")
            prefix = lowered[max(0, match.start() - 300) : match.start()]
            expected = f"drop policy if exists {name.lower()} on {table.lower()}"
            if expected not in prefix:
                errors.append(
                    f"{path.name}: policy {name} must be dropped immediately before creation"
                )

    if errors:
        print("Supabase migration validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"Validated {len(files)} ordered Supabase migrations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
