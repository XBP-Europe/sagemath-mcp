"""The MCP contract: tool names, schemas and descriptions.

This exists to make the server.py split provable. Splitting a 2327-line module
into ten is a large diff that a reviewer cannot verify line by line, so the
question "did the public surface change?" is answered mechanically instead.

The snapshot covers what a client actually sees: every tool name, its full JSON
input schema, its description text, and the resource templates. Descriptions are
part of the contract, not documentation -- they were tuned so Codex picks the
specialized tools over evaluate_sage.

Regenerate deliberately, never to make a red test green:

    python -m tests.test_tool_inventory --write
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "tool_inventory.json"


async def _collect() -> dict:
    from sagemath_mcp import server

    tools = await server.mcp.list_tools()
    templates = await server.mcp.list_resource_templates()
    return {
        "tools": {
            tool.name: {
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in sorted(tools, key=lambda t: t.name)
        },
        "resource_templates": sorted(str(t.uri_template) for t in templates),
    }


def test_tool_inventory_is_unchanged() -> None:
    """Every name, schema and description a client can see."""
    current = asyncio.run(_collect())
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    added = sorted(set(current["tools"]) - set(expected["tools"]))
    removed = sorted(set(expected["tools"]) - set(current["tools"]))
    assert not added and not removed, (
        f"the tool list changed: added={added} removed={removed}"
    )
    assert current["resource_templates"] == expected["resource_templates"]

    drifted = [
        name
        for name in expected["tools"]
        if current["tools"][name] != expected["tools"][name]
    ]
    assert not drifted, (
        "these tools changed their schema or description:\n"
        + "\n".join(f"  - {name}" for name in drifted)
    )


def test_the_snapshot_covers_every_tool() -> None:
    """A snapshot that silently emptied would pass the test above."""
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert len(expected["tools"]) >= 37, "the snapshot lost tools"
    assert len(expected["resource_templates"]) == 3


if __name__ == "__main__":  # pragma: no cover - maintenance helper
    import sys

    if "--write" in sys.argv:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(
            json.dumps(asyncio.run(_collect()), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {SNAPSHOT}")
