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
    provider = build_http_auth(SageSettings(http_auth_token="example-token"))
    assert isinstance(provider, StaticBearerTokenVerifier)


async def test_the_configured_token_is_accepted() -> None:
    verifier = StaticBearerTokenVerifier("example-token")
    access = await verifier.verify_token("example-token")
    assert access is not None
    assert access.token == "example-token"


@pytest.mark.parametrize(
    "presented",
    ["", "wrong", "example-toke", "example-token ", "EXAMPLE-TOKEN"],
)
async def test_any_other_token_is_refused(presented: str) -> None:
    """A near-miss, a prefix, a trailing space, the wrong case -- all rejected."""
    verifier = StaticBearerTokenVerifier("example-token")
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
    """Host validation also covers requests forwarded through a container."""
    from sagemath_mcp.server import _host_origin_kwargs

    assert _host_origin_kwargs("http")["host_origin_protection"] is True


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


async def test_a_token_that_cannot_be_encoded_is_refused_not_raised() -> None:
    """A lone surrogate cannot be UTF-8 encoded, and `token.encode("utf-8")`
    raised straight out of the verifier -- a 500 from the one function whose
    entire job is answering yes or no.

    Not reachable over HTTP: header bytes decode as latin-1, which never
    produces a surrogate, and every byte sequence tried against a real server
    returned a clean 401 (measured 2026-09-21). But `verify_token` takes a
    `str`, and refusing is the only answer it should have for one it cannot
    even encode (REVIEW_ACTIONS 94).
    """
    from sagemath_mcp.auth import StaticBearerTokenVerifier

    verifier = StaticBearerTokenVerifier("s3cret")
    assert await verifier.verify_token("\ud800") is None
    assert await verifier.verify_token("\udfff\ud800") is None


async def test_the_verifier_accepts_only_the_configured_token() -> None:
    """The counter-property, over the near-misses a timing or prefix bug would
    let through. A verifier that refused everything would pass the test above
    and be useless."""
    from sagemath_mcp.auth import StaticBearerTokenVerifier

    verifier = StaticBearerTokenVerifier("s3cret")
    assert await verifier.verify_token("s3cret") is not None
    for wrong in ("", "s3cre", "s3cretX", "S3CRET", "s3crét", "s3cret\x00", "x" * 100_000):
        assert await verifier.verify_token(wrong) is None, wrong


@pytest.mark.parametrize("transport", ["http", "streamable-http", "sse"])
async def test_forwarded_requests_still_validate_host_and_origin(transport):
    import httpx2 as httpx
    from fastmcp.server.http import HostOriginGuardMiddleware
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def endpoint(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", endpoint)], middleware=[
        Middleware(HostOriginGuardMiddleware, mode="strict"),
    ])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                                 base_url="http://172.20.0.2:8314") as client:
        response = await client.get("/", headers={"host": "attacker.example:8314",
                                                   "origin": "http://attacker.example:8314"})
        assert response.status_code == 421
        assert (await client.get("/", headers={"host": "localhost:8314"})).status_code == 200
    from sagemath_mcp.server import _host_origin_kwargs
    config = _host_origin_kwargs(transport)
    if transport == "sse":
        assert config["middleware"][0].kwargs["mode"] == "strict"
    else:
        assert config["host_origin_protection"] is True


def test_container_scratch_directory_is_writable_by_runtime_user():
    import yaml

    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    mounts = compose["services"]["sage-mcp"]["tmpfs"]
    sage_mount = next(m for m in mounts if m.startswith("/home/sage/.sage:"))
    assert {"uid=1001", "gid=1001", "mode=0700"} <= set(sage_mount.split(":", 1)[1].split(","))
