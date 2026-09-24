"""Two MCP clients must not share tool results.

FastMCP's response cache keys on tool name, arguments and auth identity, but not
on the MCP session. With the defaults every tool was cached for an hour, so a
second client making an identical call received the first client's response
without its own worker ever running -- and then found the variable undefined.

The reverse is a confidentiality problem: a state-dependent expression could
return another client's value.

Every test runs on both protocol eras, because they reach a workspace
differently. On the handshake era a client's workspaces are scoped to its
transport session, so a plain call is enough. On the 2026-07-28 era there is no
session that lasts between calls (`docs/fastmcp4_session_regression.md`), so a
client starts a workspace and addresses it by the token it gets back -- the
only way state survives there, and so the way these guarantees have to hold.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from sagemath_mcp import runtime, server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.session import SageSessionManager


@pytest.fixture
def python_manager(monkeypatch):
    """Route tools through the pure-Python worker so no Sage install is needed."""
    manager = SageSessionManager(SageSettings(force_python_worker=True))
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    yield manager


def _text(result) -> str:
    return "".join(block.text for block in result.content if hasattr(block, "text"))


@pytest.fixture(params=["legacy", "modern"])
def era(request) -> str:
    return request.param


@contextlib.asynccontextmanager
async def _connect(era: str) -> AsyncIterator[tuple[Client, dict[str, str]]]:
    """A client on `era`, and the arguments that address its workspace.

    `mode="auto"` is fastmcp's default and adopts the modern era against this
    server; `test_the_in_memory_client_really_is_on_each_era` pins that, so a
    change of default cannot quietly turn the modern half into a second copy
    of the legacy one.
    """
    async with Client(server.mcp, mode="legacy" if era == "legacy" else "auto") as client:
        address: dict[str, str] = {}
        if era == "modern":
            started = await client.call_tool("start_sage_session", {"name": "work"})
            address = {"session": started.data.workspace_token}
        yield client, address


@pytest.mark.asyncio
async def test_the_in_memory_client_really_is_on_each_era(python_manager):
    """Legacy keeps a named workspace between calls; modern refuses to pretend.

    Against real fastmcp rather than a fake context: the refusal is what stops
    a modern-era client silently getting an empty session per call.
    """
    async with Client(server.mcp, mode="legacy") as legacy:
        await legacy.call_tool("evaluate_sage", {"code": "keeper = 41"})
        assert "41" in _text(await legacy.call_tool("evaluate_sage", {"code": "keeper"}))
    async with Client(server.mcp) as modern:
        with pytest.raises(ToolError, match="start_sage_session"):
            await modern.call_tool("evaluate_sage", {"code": "keeper = 41"})


@pytest.mark.asyncio
async def test_two_clients_do_not_share_tool_results(python_manager, era):
    """The identical call from two clients must execute twice, not once."""
    async with _connect(era) as (first, a), _connect(era) as (second, b):
        # Same code in both clients: a cache keyed on the arguments would collide.
        await first.call_tool("evaluate_sage", {"code": "cache_probe = 41", **a})
        await second.call_tool("evaluate_sage", {"code": "cache_probe = 41", **b})

        # If the second call was served from cache, its worker never ran and
        # the variable does not exist there.
        second_read = await second.call_tool("evaluate_sage", {"code": "cache_probe", **b})
        assert "41" in _text(second_read), (
            "second client's assignment did not execute; it was served from cache"
        )

        first_read = await first.call_tool("evaluate_sage", {"code": "cache_probe", **a})
        assert "41" in _text(first_read)


@pytest.mark.asyncio
async def test_one_clients_variable_is_not_visible_to_another(python_manager, era):
    """The confidentiality half, asserted directly rather than by implication."""
    async with _connect(era) as (owner, a), _connect(era) as (other, b):
        await owner.call_tool("evaluate_sage", {"code": "private_value = 97", **a})
        probe = await other.call_tool(
            "evaluate_sage", {"code": "'private_value' in dir()", **b}
        )
        assert "False" in _text(probe), "one client's variable reached another's workspace"


@pytest.mark.asyncio
async def test_repeated_state_transitions_are_not_cached(python_manager, era):
    """reset must actually reset each time, not return a cached success."""
    async with _connect(era) as (client, a):
        await client.call_tool("evaluate_sage", {"code": "keeper = 7", **a})
        await client.call_tool("reset_sage_session", {**a})

        gone = await client.call_tool(
            "evaluate_sage", {"code": "keeper", **a}, raise_on_error=False
        )
        assert gone.is_error, "reset did not clear state"

        await client.call_tool("evaluate_sage", {"code": "keeper = 8", **a})
        await client.call_tool("reset_sage_session", {**a})
        gone_again = await client.call_tool(
            "evaluate_sage", {"code": "keeper", **a}, raise_on_error=False
        )
        assert gone_again.is_error, (
            "the second reset returned a cached success without resetting"
        )


@pytest.mark.asyncio
async def test_monitoring_resource_does_not_leak_one_clients_error_to_another(
    python_manager, era
):
    """One client's failing evaluation must not surface in another's metrics read.

    `_METRICS` is a process-global singleton, and the monitoring resource is
    unscoped. It used to emit `last_error`/`last_security_violation`/
    `last_error_details`, so any client could read another client's error
    message, rejected code and untruncated stdout there -- the sibling of the
    item 57 session-id leak (item 58). The free-text fields are now dropped
    before the snapshot reaches the wire.
    """
    import json

    from sagemath_mcp import monitoring

    monitoring.reset_metrics()
    marker = "leaky_marker_7f3a9"

    async with _connect(era) as (victim, a), _connect(era) as (attacker, _):
        # The victim runs code that fails with the marker in its error text.
        failed = await victim.call_tool(
            "evaluate_sage", {"code": marker, **a}, raise_on_error=False
        )
        assert failed.is_error, "the probe was expected to fail with a NameError"

        # The marker really did reach the internal record: without this, the
        # test could pass by never exercising the leak path at all.
        assert marker in json.dumps(monitoring.snapshot())

        # The attacker reads the shared resource and must not see the marker.
        payload = (
            await attacker.read_resource("resource://sagemath/monitoring/metrics")
        )[0].text
        assert marker not in payload, "monitoring resource leaked another client's error text"
        snapshot = json.loads(payload)
        assert "last_error" not in snapshot
        assert "last_security_violation" not in snapshot
        assert "last_error_details" not in snapshot
        # The safe aggregates are still there.
        assert snapshot["failures"] >= 1


@pytest.mark.asyncio
async def test_monitoring_resource_is_not_stale(python_manager, era):
    """Metrics must reflect work done after the first read."""
    import json

    async with _connect(era) as (client, a):
        first = json.loads((await client.read_resource("resource://sagemath/monitoring/metrics"))[0].text)
        for index in range(3):
            await client.call_tool("evaluate_sage", {"code": f"probe_{index} = {index}", **a})
        second = json.loads((await client.read_resource("resource://sagemath/monitoring/metrics"))[0].text)

    assert second["attempts"] > first["attempts"], "monitoring resource served a stale snapshot"
