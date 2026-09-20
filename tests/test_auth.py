"""Optional HTTP bearer-token authentication.

The default posture is no auth (the container is the boundary); these tests pin
the opt-in path: the token is off unless configured, a wrong token is refused, a
right token is accepted, and binding a public host without a token is warned
about. See `src/sagemath_mcp/auth.py` and SECURITY.md.
"""

from __future__ import annotations

from pathlib import Path

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


# --- DNS rebinding: the loopback default is not self-protecting ----------------


def test_the_http_transport_asks_for_host_and_origin_protection() -> None:
    """Binding to loopback does not keep a browser out.

    Found by a security review on 2026-09-19 and reproduced live: with no
    `Host`/`Origin` validation, a request carrying `Host: attacker.example`
    was accepted and the full protocol chain -- initialize, initialized,
    `tools/call` -- completed. A page the user visits, served from a domain
    that rebinds to 127.0.0.1, is same-origin to the browser, so no preflight
    is needed and the response body is readable: arbitrary evaluation and full
    result disclosure from a drive-by page.

    This matters *more* because running locally with no authentication is a
    deliberate, supported posture here. There is no second line behind it.

    `"auto"` validates only when the connection arrives over loopback, so
    container and Kubernetes deployments -- where traffic arrives on a real
    address -- are untouched. Verified both ways against a running server.
    """
    source = (Path(__file__).resolve().parents[1] / "src" / "sagemath_mcp" / "server.py").read_text(
        encoding="utf-8"
    )
    assert '"host_origin_protection"' in source or "host_origin_protection=" in source, (
        "the HTTP transport no longer asks for host/origin protection; a browser "
        "page can reach the loopback server again"
    )
    assert '"auto"' in source, (
        "protection should be 'auto', which guards loopback binds and leaves "
        "real remote binds alone; True would break deployments behind a proxy"
    )


def test_the_threat_model_documents_the_rebinding_defence() -> None:
    """The old model said 'bind loopback' and stopped there, which is exactly
    what this attack defeats. If the control is there, the document has to say
    so, or the next person removes it as noise."""
    security = (Path(__file__).resolve().parents[1] / "SECURITY.md").read_text(encoding="utf-8")
    lowered = security.lower()
    assert "rebind" in lowered
    assert "origin" in lowered


def test_every_http_transport_gets_the_host_origin_guard() -> None:
    """FastMCP's legacy SSE app ignores `host_origin_protection` entirely.

    Found 2026-09-20, the day after the guard landed: `create_sse_app` never
    reads the flag, so `--transport sse` -- which this server's CLI offers --
    shipped with no Host/Origin validation while the other two transports had
    it. A control silently absent on one supported transport is worse than one
    absent everywhere, because the documentation says it is there.

    Asserted per transport rather than once, because the gap was invisible from
    the call site: the same keyword was passed for all three and only two
    honoured it.
    """
    from sagemath_mcp.app import mcp
    from sagemath_mcp.server import _host_origin_kwargs

    for transport in ("http", "streamable-http", "sse"):
        app = mcp.http_app(transport=transport, **_host_origin_kwargs(transport))
        installed = [m.cls.__name__ for m in app.user_middleware]
        assert any("HostOriginGuard" in name for name in installed), (
            f"the {transport} transport has no host/origin guard: {installed}"
        )
