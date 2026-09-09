"""Focused contract tests for the Portal-to-Farm handoff signer."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from pathlib import Path

import pytest

from web import web_routes


SECRET = "test-only-portal-farm-secret-32-bytes-minimum"
USER = {
    "id": "3f061555-8411-493f-bdd1-88a996dc8038",
    "email": "Owner@Example.com",
    "email_verified": True,
}


def _decode_segment(segment: str) -> dict:
    padded = segment + ("=" * (-len(segment) % 4))
    return json.loads(base64.urlsafe_b64decode(padded))


def test_handoff_header_claims_and_signature():
    token = web_routes._mint_farm_handoff(
        USER,
        "https://farm.mugobyte.com/auth/portal",
        SECRET,
        now=1_800_000_000,
    )
    header_segment, payload_segment, signature_segment = token.split(".")

    assert _decode_segment(header_segment) == {"alg": "HS256", "typ": "JWT"}
    claims = _decode_segment(payload_segment)
    assert claims == {
        "aud": "farm-bridge",
        "email": "owner@example.com",
        "email_verified": True,
        "exp": 1_800_000_120,
        "iat": 1_800_000_000,
        "jti": claims["jti"],
        "product": "farm",
        "redirect_uri": "https://farm.mugobyte.com/auth/portal",
        "sub": USER["id"],
    }
    assert str(uuid.UUID(claims["jti"])) == claims["jti"]
    expected = hmac.new(
        SECRET.encode(),
        f"{header_segment}.{payload_segment}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    actual = base64.urlsafe_b64decode(signature_segment + ("=" * (-len(signature_segment) % 4)))
    assert hmac.compare_digest(actual, expected)


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "",
        "https://evil.example/auth/portal",
        "https://farm.mugobyte.com/auth/portal?next=https://evil.example",
        "mugobytefarm://auth-callback/extra",
    ],
)
def test_handoff_rejects_non_exact_redirects(redirect_uri):
    with pytest.raises(ValueError, match="invalid redirect"):
        web_routes._mint_farm_handoff(USER, redirect_uri, SECRET)


def test_handoff_rejects_missing_or_short_secret():
    for secret in ("", "too-short"):
        with pytest.raises(ValueError, match="missing bridge secret"):
            web_routes._mint_farm_handoff(
                USER,
                "mugobytefarm://auth-callback",
                secret,
            )


def test_handoff_requires_verified_account():
    with pytest.raises(ValueError, match="unverified email"):
        web_routes._mint_farm_handoff(
            {**USER, "email_verified": False},
            "mugobytefarm://auth-callback",
            SECRET,
        )


def test_route_contract_requires_supabase_and_frontend_preserves_state_only():
    root = Path(__file__).resolve().parents[1]
    backend = (root / "web" / "web_routes.py").read_text(encoding="utf-8")
    frontend = (
        root / "web" / "mugobyte-platform" / "src" / "routes" / "farm.tsx"
    ).read_text(encoding="utf-8")
    route_tree = (
        root / "web" / "mugobyte-platform" / "src" / "routeTree.gen.ts"
    ).read_text(encoding="utf-8")

    assert "getattr(g, 'auth_provider', None) != 'supabase'" in backend
    assert '"state"' not in backend[backend.index("def _mint_farm_handoff"):backend.index("@web.route('/api/cloud/farm/handoff")]
    assert "redirect_uri: redirect" in frontend
    assert "state," not in frontend[frontend.index('POST<FarmHandoffResponse>'):frontend.index("if (cancelled)")]
    assert "window.location.pathname}${window.location.search}" in frontend
    assert "state=${encodeURIComponent(state)}" in frontend
    assert "'/farm': typeof FarmRoute" in route_tree
