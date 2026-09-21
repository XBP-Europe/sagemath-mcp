"""Optional bearer-token authentication for the HTTP transports.

Opt-in only. The default posture is unchanged and deliberate (see SECURITY.md):
no authentication, the container is the boundary, keep the endpoint on loopback.
This adds one thing on top for anyone who fronts the HTTP endpoint on a network:
a single operator-configured bearer token, set through
``SAGEMATH_MCP_HTTP_AUTH_TOKEN``. When it is set, every MCP request must carry
``Authorization: Bearer <token>``; when it is not, nothing changes.

It is a shared-secret API key, not an OAuth server: no rotation, scopes, expiry
or per-user identity. It is defence for the transport, not a replacement for the
container -- a pip install still runs with your user's privileges. The token is
compared in constant time so a wrong guess cannot be recovered byte by byte from
response timing, and it is never logged.
"""

from __future__ import annotations

import secrets

from fastmcp.server.auth import AccessToken, AuthProvider, TokenVerifier

from .config import SageSettings

# A fixed identity for the single shared token. There is exactly one principal,
# so the id is a label, not a secret, and it never carries the token itself.
_CLIENT_ID = "sagemath-mcp-bearer"


class StaticBearerTokenVerifier(TokenVerifier):
    """Accepts exactly one operator-configured bearer token, in constant time."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("bearer token must be a non-empty string")
        super().__init__()
        # Keep the expected value as bytes: compare_digest wants two byte strings
        # of the same type, and encoding once avoids doing it on every request.
        self._expected = token.encode("utf-8")

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            candidate = token.encode("utf-8")
        except UnicodeEncodeError:
            # A lone surrogate cannot be UTF-8 encoded, and this raised out of
            # the verifier: a 500 where a 401 belongs, from the one function
            # whose entire job is answering yes or no. Not reachable over HTTP
            # -- header bytes decode as latin-1, which never produces a
            # surrogate, and every byte sequence tried against a real server
            # returned a clean 401 (measured 2026-09-21). But `verify_token`
            # takes a `str`, and refusing is the only answer it should ever
            # have for one it cannot even encode (REVIEW_ACTIONS 94).
            return None
        # `secrets.compare_digest` is constant-time in the length of the shorter
        # input, so an attacker cannot learn the token one character at a time by
        # measuring how long the comparison takes.
        if secrets.compare_digest(candidate, self._expected):
            return AccessToken(token=token, client_id=_CLIENT_ID, scopes=[])
        return None


def build_http_auth(settings: SageSettings) -> AuthProvider | None:
    """The auth provider for the HTTP transports, or None when auth is off.

    Returns None unless ``http_auth_token`` is configured, so the FastMCP app is
    unauthenticated by default -- the posture SECURITY.md describes. The returned
    provider guards the MCP endpoint; the ``/health`` and ``/ready`` probes are
    plain app routes and stay open, which is what a load balancer needs.
    """
    token = settings.http_auth_token
    if not token:
        return None
    return StaticBearerTokenVerifier(token)
