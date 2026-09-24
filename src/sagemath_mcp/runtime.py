"""Process-wide runtime state: the settings and the session manager.

This lives apart from ``server`` so tool modules can reach the session manager
without importing the module that imports them. Everything refers to
``runtime.SESSION_MANAGER`` by attribute rather than binding it at import time,
which is what lets a test swap the manager for a pure-Python one.
"""

from __future__ import annotations

import secrets
import uuid
from typing import Any

from fastmcp.exceptions import ToolError

from .config import DEFAULT_SETTINGS, SageSettings
from .session import DEFAULT_SESSION_NAME, WORKSPACE_TOKEN_PREFIX, SageSessionManager

SETTINGS: SageSettings = DEFAULT_SETTINGS
SESSION_MANAGER = SageSessionManager(SETTINGS)

#: The client scope every call shares when this process serves exactly one
#: client, which is what stdio means. `None` on HTTP, where one process serves
#: many clients and the scope has to come from the transport.
PROCESS_SCOPE: str | None = None

#: The first protocol version whose requests each carry their own envelope. On
#: this era the server builds a fresh connection per request, so nothing it can
#: read lasts as long as the client session -- fastmcp 4 answers
#: `Context.session_id` with a new UUID on every call. Protocol versions are
#: ISO dates, so later eras compare greater.
PER_REQUEST_ERA = "2026-07-28"

PER_REQUEST_REFUSAL = (
    "This connection speaks the 2026-07-28 MCP protocol, which gives the server "
    "no identity that lasts from one call to the next, so a workspace cannot be "
    "addressed by name here: each call would silently land in a fresh, empty "
    "session. Call start_sage_session and pass the workspace_token it returns "
    "as the `session` argument of every later call."
)


def anchor_to_process() -> str:
    """Scope every call in this process to one client. For stdio only.

    A stdio server process has exactly one client for its whole life, so the
    process itself is the identity -- one that holds whatever the transport's
    session id does between calls. The scope is minted per process rather than
    fixed: two stdio servers running side by side, or one restarted, must not
    share a journal file and restore each other's variables.
    """
    global PROCESS_SCOPE
    PROCESS_SCOPE = f"stdio-{uuid.uuid4().hex}"
    return PROCESS_SCOPE


def identity_is_per_request(ctx: Any) -> bool:
    """Is this call on a protocol era where the session id changes every call?

    A context with no request, or a request with no protocol version, is
    treated as the handshake era: nothing about it says the id will change.
    """
    version = getattr(getattr(ctx, "request_context", None), "protocol_version", None)
    return isinstance(version, str) and version >= PER_REQUEST_ERA


def client_scope(ctx: Any, session: str = DEFAULT_SESSION_NAME, *, minting: bool = False) -> str:
    """The client scope a call's workspaces live under.

    Every tool resolves its caller through here rather than reading
    `ctx.session_id` itself, because that id is only an identity on some
    transports:

    - **stdio**: the process scope, whatever the transport reports.
    - **a workspace token**: any scope will do; the token resolves on its own.
    - **the per-request era over HTTP**: refused for anything addressed by
      name, rather than handing out a fresh session per call. `minting` is
      the exception: `start_sage_session` gets a brand-new scope the server
      generates, because the token it returns is the only way back in.
    - **otherwise**: the transport's session id, as it always was.

    Never `ctx.session_id` when minting on the per-request era. There is no
    negotiated session on that era, so fastmcp falls back to the raw
    `mcp-session-id` request header -- a value the caller chooses. Minting
    under it let a client that knew another's session id mint a token into
    that client's workspace, and keep it after the victim's session ended,
    when the id itself is answered with 404 (REVIEW_ACTIONS 99).
    """
    if PROCESS_SCOPE is not None:
        return PROCESS_SCOPE
    is_token = (session or "").strip().startswith(WORKSPACE_TOKEN_PREFIX)
    if not is_token and identity_is_per_request(ctx):
        if not minting:
            raise ToolError(PER_REQUEST_REFUSAL)
        return f"minted-{secrets.token_hex(16)}"
    return ctx.session_id


def get_session_manager() -> SageSessionManager:
    """The live session manager.

    Always read through this (or ``runtime.SESSION_MANAGER``) rather than
    importing the object itself: a module-level ``from .runtime import
    SESSION_MANAGER`` binds the manager that existed at import time, and a test
    that replaces it would silently be running against the real one.
    """
    return SESSION_MANAGER


async def resolve_session(client_session_id: str, name: str):
    """Look up (or start) the worker for one client's named workspace.

    Every worker-backed tool needs this pair of calls, and spelling it out at
    each of the ~30 sites is what made the lines unwieldy once the manager moved
    out of ``server``. Reading the manager here also keeps the lookup late-bound.
    """
    manager = get_session_manager()
    return await manager.get(manager.resolve_key(client_session_id, name))
