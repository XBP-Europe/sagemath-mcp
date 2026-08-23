"""MCP tool annotations, grouped by what a tool does to the session.

Annotations are advisory metadata for clients (`readOnlyHint`,
`destructiveHint`, `idempotentHint`, `openWorldHint`) -- an agent UI may use
them to decide what needs confirmation and what is safe to retry. They are
hints, not enforcement; the security model does not depend on them.

`openWorldHint` is False on every tool: nothing here reaches beyond the local
Sage worker. A test in tests/test_tool_inventory.py pins each group's
membership, so a new tool must say what kind it is.
"""

from __future__ import annotations

# Deterministic mathematics. These run inside the session worker (so not
# readOnly -- they cost compute and may warm caches there), but repeating one
# with the same input adds nothing and destroys nothing.
COMPUTES: dict[str, bool] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

# Open-ended code in the persistent namespace. `x += 1` twice is not the same
# as once, so no idempotence is promised.
EVALUATES: dict[str, bool] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}

# Session lifecycle that throws state away: cancel and reset discard the
# namespace, stop discards a whole workspace. The one thing worth a client's
# confirmation prompt.
DISCARDS: dict[str, bool] = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": False,
}

# Interrupt stops the computation and keeps every variable -- deliberately not
# destructive, because that distinction is the reason the tool exists.
INTERRUPTS: dict[str, bool] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

# Starting a workspace that already exists is a no-op.
STARTS: dict[str, bool] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

# Pure inspection.
READS: dict[str, bool] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
