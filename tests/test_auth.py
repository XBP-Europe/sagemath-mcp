"""Optional HTTP bearer-token authentication.

The default posture is no auth (the container is the boundary); these tests pin
the opt-in path: the token is off unless configured, a wrong token is refused, a
right token is accepted, and binding a public host without a token is warned
about. See `src/sagemath_mcp/auth.py` and SECURITY.md.
"""

from __future__ import annotations

import pytest

from sagemath_mcp.auth import StaticBearerTokenVerifier, build_http_auth
from sagemath_mcp.config import SageSettings
from sagemath_mcp.server import _exposure_warning


def test_build_http_auth_is_off_by_default() -> None:
    """No token configured -> no auth provider, so the app is unauthenticated."""
    assert build_http_auth(SageSettings()) is None


def test_build_http_auth_returns_a_verifier_when_a_token_is_set() -> None:
    provider = build_http_auth(SageSettings(http_auth_token="s3cret-token"))
    assert isinstance(provider, StaticBearerTokenVerifier)


async def test_the_configured_token_is_accepted() -> None:
    verifier = StaticBearerTokenVerifier("s3cret-token")
    access = await verifier.verify_token("s3cret-token")
    assert access is not None
    assert access.token == "s3cret-token"


@pytest.mark.parametrize(
    "presented",
    ["", "wrong", "s3cret-toke", "s3cret-token ", "S3CRET-TOKEN"],
)
async def test_any_other_token_is_refused(presented: str) -> None:
    """A near-miss, a prefix, a trailing space, the wrong case -- all rejected."""
    verifier = StaticBearerTokenVerifier("s3cret-token")
    assert await verifier.verify_token(presented) is None


def test_an_empty_token_cannot_be_configured() -> None:
    """An empty secret would authenticate everyone; refuse to build it."""
    with pytest.raises(ValueError, match="non-empty"):
        StaticBearerTokenVerifier("")


async def test_a_unicode_token_round_trips() -> None:
    # The token is compared as UTF-8 bytes, so non-ASCII secrets work end to end.
    verifier = StaticBearerTokenVerifier("clé-secrète-éè")
    assert await verifier.verify_token("clé-secrète-éè") is not None
    assert await verifier.verify_token("cle-secrete-ee") is None


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "::ffff:127.0.0.1"])
def test_loopback_binds_are_never_warned(host: str) -> None:
    assert _exposure_warning(host, has_auth=False) is None


def test_a_public_bind_without_auth_is_warned() -> None:
    warning = _exposure_warning("0.0.0.0", has_auth=False)
    assert warning is not None
    assert "NO authentication" in warning
    assert "SAGEMATH_MCP_HTTP_AUTH_TOKEN" in warning


def test_a_public_bind_with_auth_is_not_warned() -> None:
    assert _exposure_warning("0.0.0.0", has_auth=True) is None
