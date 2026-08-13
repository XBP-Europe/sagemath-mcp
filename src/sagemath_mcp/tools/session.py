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
)
from ..session import (
    DEFAULT_SESSION_NAME,
)
from ..text import SESSION_ARG_DESC as _SESSION_ARG_DESC

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


@mcp.tool(description="Reset the SageMath session state for the current MCP session")
async def reset_sage_session(
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> ResetResponse:
    """Reset the Sage session associated with the current MCP session."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to reset state")
    await runtime.SESSION_MANAGER.reset(runtime.SESSION_MANAGER.key_for(ctx.session_id, session))
    await ctx.info(f"Sage session '{session}' reset")
    return ResetResponse()


@mcp.tool(
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
    key = runtime.SESSION_MANAGER.key_for(ctx.session_id, session)
    interrupted = await runtime.SESSION_MANAGER.interrupt(key)
    if not interrupted:
        # No worker to signal: either nothing has run yet in this workspace, or
        # it has already exited. Not an error, but say which.
        await ctx.info(f"No running Sage worker for session '{session}'")
        return ResetResponse(message=f"No running computation in session '{session}'")
    await ctx.warning(f"Interrupted session '{session}'; state preserved")
    return ResetResponse(message=f"Interrupted session '{session}'; state preserved")


@mcp.tool(description="Cancel any running Sage computation and restart the worker")
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
    await runtime.SESSION_MANAGER.cancel(runtime.SESSION_MANAGER.key_for(ctx.session_id, session))
    await ctx.warning(f"Sage session '{session}' cancelled and restarted")
    return ResetResponse(message="Session cancelled and restarted")


@mcp.tool(description="Start a named Sage workspace with its own independent variables")
async def start_sage_session(
    name: Annotated[str, Field(description="Workspace name, e.g. 'curves' or 'scratch'")],
    ctx: Context | None = None,
) -> ResetResponse:
    """Create a named workspace so one client can hold several at once.

    Workspaces are independent: a variable defined in one is invisible to the
    others. Calling this for an existing name is harmless.
    """
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to start a session")
    if not name.strip():
        raise ToolError("Session name must not be empty")
    await runtime.resolve_session(ctx.session_id, name)
    await ctx.info(f"Started Sage session '{name}'")
    return ResetResponse(message=f"Session '{name}' ready")


@mcp.tool(description="List the named Sage workspaces belonging to this client")
async def list_sage_sessions(ctx: Context | None = None) -> dict:
    """Report every workspace for this client, with liveness and statement counts."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to list sessions")
    sessions = await runtime.SESSION_MANAGER.list_for_scope(ctx.session_id)
    return {"sessions": sessions, "count": len(sessions)}


@mcp.tool(description="Stop a named Sage workspace and release its worker")
async def stop_sage_session(
    name: Annotated[str, Field(description="Workspace name to stop")],
    ctx: Context | None = None,
) -> ResetResponse:
    """Terminate one workspace. Other workspaces are unaffected."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to stop a session")
    stopped = await runtime.SESSION_MANAGER.stop(ctx.session_id, name)
    if not stopped:
        raise ToolError(f"No Sage session named '{name}' for this client")
    await ctx.info(f"Stopped Sage session '{name}'")
    return ResetResponse(message=f"Session '{name}' stopped")


@mcp.resource("resource://sagemath/session/{scope}")
async def session_resource(scope: str, ctx: Context | None = None) -> str:
    """Expose a resource describing active Sage sessions for observability."""
    import json as _json

    del ctx  # resource does not require request context
    data = runtime.SESSION_MANAGER.snapshot()
    if scope != "all":
        data = [entry for entry in data if entry["session_id"] == scope]
    snapshots = [
        SessionSnapshot(
            session_id=entry["session_id"],
            live=bool(entry["live"]),
            started_at=float(entry["started_at"]),
            last_used_at=float(entry["last_used_at"]),
            idle_seconds=float(entry["idle_seconds"]),
        )
        for entry in data
    ]
    return _json.dumps([s.model_dump() for s in snapshots])


@mcp.resource("resource://sagemath/monitoring/{scope}")
async def monitoring_resource(scope: str, ctx: Context | None = None) -> str:
    """Expose aggregated metrics for observability."""
    del ctx
    if scope not in {"metrics", "all"}:
        return "[]"
    snapshot = monitoring.snapshot()
    return MonitoringSnapshot(**snapshot).model_dump_json()


@mcp.resource("resource://sagemath/docs/{scope}")
async def documentation_resource(scope: str, ctx: Context | None = None) -> list[DocumentationLink]:
    del ctx
    if scope == "all":
        return DOC_LINKS
    return [link for link in DOC_LINKS if link.slug == scope]
