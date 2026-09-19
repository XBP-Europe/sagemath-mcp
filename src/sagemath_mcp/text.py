"""Text shown to MCP clients that more than one module needs.

Small on purpose: these strings are part of the tool contract -- they appear in
the schema every client reads -- so they live where both the tool modules and
the app can reach them without importing each other.
"""

from __future__ import annotations

from .session import DEFAULT_SESSION_NAME, WORKSPACE_TOKEN_PREFIX

SESSION_ARG_DESC = (
    "Workspace to use, as a name or a portable handle. Workspaces have "
    "independent variables. A name is scoped to this MCP session; a handle "
    "returned by start_sage_session (workspace_token) reaches the same "
    "workspace across reconnects and is a bearer credential -- keep it secret. "
    f"Omit for '{DEFAULT_SESSION_NAME}'."
)


def loggable_session(session: str) -> str:
    """A workspace label safe for logs, notifications and responses.

    A workspace token is a **bearer credential** (see `session.py`): whoever
    holds it reaches that workspace, so it must never appear in a log line, an
    MCP notification or a tool response -- the same secrecy
    `start_sage_session` promises. A caller's `session` argument may be either a
    plain name or a token, so a token is shown as a generic label and a name
    (not a secret) as itself.

    It lives here rather than in `tools/session.py` because it is not a
    lifecycle concern: `evaluate_sage` takes the same argument and leaked the
    token verbatim on its cancellation path, because the helper was somewhere
    only the lifecycle tools imported from. Every tool that accepts `session`
    routes its user-facing strings through this, and a test fails if one stops.
    """
    return "the workspace" if session.strip().startswith(WORKSPACE_TOKEN_PREFIX) else f"'{session}'"
