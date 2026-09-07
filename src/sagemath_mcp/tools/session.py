"""Session lifecycle tools and the read-only resources.

One of the tool modules imported by :mod:`sagemath_mcp.server` for its
registration side effect. Decorating against the shared ``mcp`` object keeps
every tool name exactly as it was; FastMCP's mount/import_server composition
would have prefixed them.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from .. import monitoring, runtime
from ..app import mcp
from ..models import (
    DocumentationLink,
    MonitoringSnapshot,
    ResetResponse,
    SessionSnapshot,
    WorkspaceHandle,
)
from ..session import (
    DEFAULT_SESSION_NAME,
    WORKSPACE_TOKEN_PREFIX,
    SageSessionManager,
)
from ..text import SESSION_ARG_DESC as _SESSION_ARG_DESC
from .hints import DISCARDS, INTERRUPTS, READS, STARTS

DOC_LINKS: list[DocumentationLink] = [
    DocumentationLink(
        title="SageMath Reference Manual",
        url="https://doc.sagemath.org/html/en/reference",
        slug="reference",
        description="Comprehensive API and functionality reference for SageMath.",
    ),
    DocumentationLink(
        title="Sage Tutorial",
        url="https://doc.sagemath.org/html/en/tutorial",
        slug="tutorial",
        description="Gentle introduction to SageMath syntax and workflows.",
    ),
]


def _loggable(session: str) -> str:
    """A workspace label safe for logs, notifications and responses.

    A workspace token is a **bearer credential** (see `session.py`): whoever
    holds it reaches that workspace, so it must never appear in a log line, an
    MCP notification or a tool response -- the same secrecy `start_sage_session`
    promises. A caller's `session` argument may be either a plain name or a
    token, so a token is shown as a generic label and a name (not a secret) as
    itself. Every lifecycle tool routes its user-facing strings through here.
    """
    return "the workspace" if session.strip().startswith(WORKSPACE_TOKEN_PREFIX) else f"'{session}'"


@mcp.tool(
    annotations=DISCARDS,
    description="Reset the SageMath session state for the current MCP session",
)
async def reset_sage_session(
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> ResetResponse:
    """Reset the Sage session associated with the current MCP session."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to reset state")
    key = runtime.SESSION_MANAGER.resolve_key(ctx.session_id, session)
    await runtime.SESSION_MANAGER.reset(key)
    await ctx.info(f"Sage session {_loggable(session)} reset")
    return ResetResponse()


@mcp.tool(
    annotations=INTERRUPTS,
    description="Interrupt a running Sage computation while keeping variables defined so far"
)
async def interrupt_sage_session(
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> ResetResponse:
    """Signal the worker to abandon its computation without losing state.

    Prefer this over cancel_sage_session: cancelling restarts the worker and
    discards every variable, which is the worse outcome when the state was
    expensive to build.
    """
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to interrupt work")
    key = runtime.SESSION_MANAGER.resolve_key(ctx.session_id, session)
    interrupted = await runtime.SESSION_MANAGER.interrupt(key)
    if not interrupted:
        # No worker to signal: either nothing has run yet in this workspace, or
        # it has already exited. Not an error, but say which.
        await ctx.info(f"No running Sage worker for session {_loggable(session)}")
        return ResetResponse(message=f"No running computation in session {_loggable(session)}")
    await ctx.warning(f"Interrupted session {_loggable(session)}; state preserved")
    return ResetResponse(message=f"Interrupted session {_loggable(session)}; state preserved")


@mcp.tool(
    annotations=DISCARDS,
    description="Cancel any running Sage computation and restart the worker",
)
async def cancel_sage_session(
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> ResetResponse:
    """Cancel in-flight work by restarting the backing Sage worker.

    This discards the namespace. Use interrupt_sage_session to stop a
    computation while keeping it.
    """
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to cancel work")
    key = runtime.SESSION_MANAGER.resolve_key(ctx.session_id, session)
    await runtime.SESSION_MANAGER.cancel(key)
    await ctx.warning(f"Sage session {_loggable(session)} cancelled and restarted")
    return ResetResponse(message="Session cancelled and restarted")


@mcp.tool(
    annotations=STARTS,
    description="Start a named Sage workspace with its own independent variables",
)
async def start_sage_session(
    name: Annotated[str, Field(description="Workspace name, e.g. 'curves' or 'scratch'")],
    ctx: Context | None = None,
) -> WorkspaceHandle:
    """Create a named workspace and issue a portable handle to it.

    Workspaces are independent: a variable defined in one is invisible to the
    others. Calling this for an existing name is harmless.

    The returned `workspace_token` is a **bearer credential**: whoever presents
    it as a later call's `session` argument reaches this exact workspace,
    regardless of the transport-level MCP session id -- so state survives a
    reconnect, or a transport that hands out a fresh id per call. It is not
    authentication and identifies no one; possession alone grants access, so it
    is unguessable and must be kept secret. The workspace also remains reachable
    the old way, by `name`, within this transport session.
    """
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to start a session")
    if not name.strip():
        raise ToolError("Session name must not be empty")
    if name.strip().startswith(WORKSPACE_TOKEN_PREFIX):
        raise ToolError(
            f"A workspace name may not start with '{WORKSPACE_TOKEN_PREFIX}'; "
            "that prefix is reserved for server-issued handles."
        )
    await runtime.resolve_session(ctx.session_id, name)
    key = runtime.SESSION_MANAGER.resolve_key(ctx.session_id, name)
    token = runtime.SESSION_MANAGER.mint_workspace_token(key)
    # The name is safe to log; the token is a secret and must never be.
    await ctx.info(f"Started Sage session '{name}'")
    return WorkspaceHandle(
        message=f"Session '{name}' ready", workspace_token=token, name=name
    )


@mcp.tool(annotations=READS, description="List the named Sage workspaces belonging to this client")
async def list_sage_sessions(ctx: Context | None = None) -> dict:
    """Report every workspace for this client, with liveness and statement counts."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to list sessions")
    sessions = await runtime.SESSION_MANAGER.list_for_scope(ctx.session_id)
    return {"sessions": sessions, "count": len(sessions)}


@mcp.tool(annotations=DISCARDS, description="Stop a named Sage workspace and release its worker")
async def stop_sage_session(
    name: Annotated[str, Field(description="Workspace name to stop")],
    ctx: Context | None = None,
) -> ResetResponse:
    """Terminate one workspace. Other workspaces are unaffected."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to stop a session")
    stopped = await runtime.SESSION_MANAGER.stop(ctx.session_id, name)
    if not stopped:
        raise ToolError(f"No Sage session named {_loggable(name)} for this client")
    await ctx.info(f"Stopped Sage session {_loggable(name)}")
    return ResetResponse(message=f"Session {_loggable(name)} stopped")


@mcp.resource("resource://sagemath/session/{scope}")
async def session_resource(scope: str, ctx: Context | None = None) -> str:
    """Describe the caller's own Sage workspaces, for observability.

    Scoped to the requesting client. The manager holds one entry per (MCP
    session, workspace), keyed by the client's `Mcp-Session-Id`, and this used
    to return the whole map -- so any client could read `.../session/all`, learn
    every other client's session id, and replay it in an `Mcp-Session-Id` header
    to act inside their namespace (item 57). Now the caller sees only their own
    sessions, identified by workspace *name* rather than by the raw key, so no
    MCP session id crosses the wire. `{scope}` selects a single workspace by
    name, or "all" for every workspace this client owns.

    Fails closed: without a request context there is no caller to scope to, so
    nothing is returned. `/health` still reports the process-wide session count
    for operators who need the aggregate.
    """
    import json as _json

    if ctx is None or ctx.session_id is None:
        return _json.dumps([])
    my_scope = ctx.session_id
    snapshots = []
    for entry in runtime.SESSION_MANAGER.snapshot():
        entry_scope, workspace = SageSessionManager.split_key(str(entry["session_id"]))
        if entry_scope != my_scope:
            continue
        if scope != "all" and workspace != scope:
            continue
        snapshots.append(
            SessionSnapshot(
                session_id=workspace,
                live=bool(entry["live"]),
                started_at=float(entry["started_at"]),
                last_used_at=float(entry["last_used_at"]),
                idle_seconds=float(entry["idle_seconds"]),
            )
        )
    return _json.dumps([s.model_dump() for s in snapshots])


@mcp.resource("resource://sagemath/monitoring/{scope}")
async def monitoring_resource(scope: str, ctx: Context | None = None) -> str:
    """Expose aggregated metrics for observability.

    Unscoped by design: the metrics are process-wide totals, so there is no
    per-caller view to return and `ctx` is not needed. What made scoping matter
    was the free-text error fields -- `last_error`, `last_security_violation`,
    `last_error_details` -- which held one client's message, rejected code and
    untruncated stdout in a process-global singleton, so any client reading this
    resource saw another client's data (the sibling leak the item 57 fix left in
    place; item 58). Those fields are dropped by `public_snapshot()` before they
    reach the wire; only non-identifying aggregates remain.
    """
    del ctx
    if scope not in {"metrics", "all"}:
        return "[]"
    return MonitoringSnapshot(**monitoring.public_snapshot()).model_dump_json()


@mcp.resource("resource://sagemath/docs/{scope}")
async def documentation_resource(scope: str, ctx: Context | None = None) -> list[DocumentationLink]:
    del ctx
    if scope == "all":
        return DOC_LINKS
    return [link for link in DOC_LINKS if link.slug == scope]
