"""Text shown to MCP clients that more than one module needs.

Small on purpose: these strings are part of the tool contract -- they appear in
the schema every client reads -- so they live where both the tool modules and
the app can reach them without importing each other.
"""

from __future__ import annotations

from .session import DEFAULT_SESSION_NAME

SESSION_ARG_DESC = (
    "Workspace to use, as a name or a portable handle. Workspaces have "
    "independent variables. A name is scoped to this MCP session; a handle "
    "returned by start_sage_session (workspace_token) reaches the same "
    "workspace across reconnects and is a bearer credential -- keep it secret. "
    f"Omit for '{DEFAULT_SESSION_NAME}'."
)
