"""Text shown to MCP clients that more than one module needs.

Small on purpose: these strings are part of the tool contract -- they appear in
the schema every client reads -- so they live where both the tool modules and
the app can reach them without importing each other.
"""

from __future__ import annotations

from .session import DEFAULT_SESSION_NAME

SESSION_ARG_DESC = (
    "Named workspace to use. Workspaces have independent variables; "
    f"omit for '{DEFAULT_SESSION_NAME}'."
)
