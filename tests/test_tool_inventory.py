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
import pathlib
from pathlib import Path

import pytest

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


def test_every_tool_is_documented_for_users() -> None:
    """A tool nobody documents is a tool nobody uses.

    USAGE.md's table drifted by four tools without anyone noticing, and they
    were not obscure ones: `interrupt_sage_session`, which the same page
    recommends in prose as the option to prefer, and the three that make up
    named workspaces -- a whole feature a reader had no way to discover there.
    The header said "37 tools" throughout, which is what made the gap invisible.
    """
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    expected = set(json.loads(SNAPSHOT.read_text(encoding="utf-8"))["tools"])

    for doc in ("USAGE.md", "README.md"):
        text = (root / doc).read_text(encoding="utf-8")
        # A tool counts as documented when it appears in a backticked mention.
        mentioned = set(re.findall(r"`([a-z_0-9]+)`", text))
        missing = sorted(expected - mentioned)
        assert not missing, f"{doc} never mentions these tools: {missing}"


if __name__ == "__main__":  # pragma: no cover - maintenance helper
    import sys

    if "--write" in sys.argv:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(
            json.dumps(asyncio.run(_collect()), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {SNAPSHOT}")


# Parameters that carry exact integers. A JSON number past MAX_SAFE_INTEGER has
# already been rounded by a JavaScript client, so each of these must also accept
# a decimal string -- and that has to be visible in the SCHEMA, not merely
# tolerated by the Python function. An earlier fix guarded the function bodies
# while leaving the schemas integer-only: the tests called the functions directly
# and passed, while every real MCP client was still refused the escape hatch.
EXACT_INTEGER_PARAMETERS = [
    ("number_theory_operation", "a"),
    ("number_theory_operation", "b"),
    ("combinatorics_operation", "n"),
    ("combinatorics_operation", "k"),
    ("graph_operation", "source"),
    ("graph_operation", "target"),
]


def _accepts_string(schema: dict) -> bool:
    if schema.get("type") == "string":
        return True
    return any(
        option.get("type") == "string"
        for option in schema.get("anyOf", []) + schema.get("oneOf", [])
    )


@pytest.mark.parametrize(
    "tool,parameter",
    EXACT_INTEGER_PARAMETERS,
    ids=[f"{t}.{p}" for t, p in EXACT_INTEGER_PARAMETERS],
)
def test_exact_integer_parameters_advertise_the_string_escape_hatch(
    tool: str, parameter: str
) -> None:
    tools = asyncio.run(_collect())["tools"]
    schema = tools[tool]["input_schema"]["properties"][parameter]
    assert _accepts_string(schema), (
        f"{tool}.{parameter} takes exact integers but the schema offers no string form, "
        "so a client cannot pass a value above 2^53 at all"
    )


def test_elliptic_curve_coefficients_advertise_it_too() -> None:
    tools = asyncio.run(_collect())["tools"]
    items = tools["elliptic_curve_operation"]["input_schema"]["properties"]["coefficients"]["items"]
    assert _accepts_string(items), "curve coefficients cannot carry an exact large integer"


@pytest.mark.parametrize(
    "tool,parameter",
    [
        ("matrix_operation", "matrix"),
        ("matrix_multiply", "matrix_a"),
        ("matrix_multiply", "matrix_b"),
    ],
)
def test_matrix_entries_advertise_exact_integers(tool: str, parameter: str) -> None:
    """A float-only entry schema rounds an exact integer before Sage sees it."""
    tools = asyncio.run(_collect())["tools"]
    entry = tools[tool]["input_schema"]["properties"][parameter]["items"]["items"]
    assert _accepts_string(entry), f"{tool}.{parameter} entries cannot carry an exact integer"
