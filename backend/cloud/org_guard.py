"""A shop may use cloud data only when the organisation id is known and matches."""
from __future__ import annotations


def organisation_allowed(local_org_id: str, remote_org_id: str) -> dict:
    local = (local_org_id or '').strip()
    remote = (remote_org_id or '').strip()
    if not local or not remote:
        return {'allowed': False, 'reason': 'Organisation is not confirmed'}
    if local != remote:
        return {'allowed': False, 'reason': 'Organisation does not match this shop'}
    return {'allowed': True}
