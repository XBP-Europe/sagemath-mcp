"""Two MCP clients must not share tool results.

FastMCP's response cache keys on tool name, arguments and auth identity, but not
on the MCP session. With the defaults every tool was cached for an hour, so a
second client making an identical call received the first client's response
without its own worker ever running -- and then found the variable undefined.

The reverse is a confidentiality problem: a state-dependent expression could
return another client's value.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

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


@pytest.mark.asyncio
async def test_two_clients_do_not_share_tool_results(python_manager):
    """The identical call from two clients must execute twice, not once."""
    async with Client(server.mcp) as first, Client(server.mcp) as second:
        # Same arguments in both clients: the cache key would collide.
        await first.call_tool("evaluate_sage", {"code": "cache_probe = 41"})
        await second.call_tool("evaluate_sage", {"code": "cache_probe = 41"})

        # If the second call was served from cache, its worker never ran and
        # the variable does not exist there.
        second_read = await second.call_tool("evaluate_sage", {"code": "cache_probe"})
        assert "41" in _text(second_read), (
            "second client's assignment did not execute; it was served from cache"
        )

        first_read = await first.call_tool("evaluate_sage", {"code": "cache_probe"})
        assert "41" in _text(first_read)


@pytest.mark.asyncio
async def test_repeated_state_transitions_are_not_cached(python_manager):
    """reset must actually reset each time, not return a cached success."""
    async with Client(server.mcp) as client:
        await client.call_tool("evaluate_sage", {"code": "keeper = 7"})
        await client.call_tool("reset_sage_session", {})

        gone = await client.call_tool(
            "evaluate_sage", {"code": "keeper"}, raise_on_error=False
        )
        assert gone.is_error, "reset did not clear state"

        await client.call_tool("evaluate_sage", {"code": "keeper = 8"})
        await client.call_tool("reset_sage_session", {})
        gone_again = await client.call_tool(
            "evaluate_sage", {"code": "keeper"}, raise_on_error=False
        )
        assert gone_again.is_error, (
            "the second reset returned a cached success without resetting"
        )


@pytest.mark.asyncio
async def test_monitoring_resource_does_not_leak_one_clients_error_to_another(python_manager):
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

    async with Client(server.mcp) as victim, Client(server.mcp) as attacker:
        # The victim runs code that fails with the marker in its error text.
        failed = await victim.call_tool(
            "evaluate_sage", {"code": marker}, raise_on_error=False
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
async def test_monitoring_resource_is_not_stale(python_manager):
    """Metrics must reflect work done after the first read."""
    import json

    async with Client(server.mcp) as client:
        first = json.loads((await client.read_resource("resource://sagemath/monitoring/metrics"))[0].text)
        for index in range(3):
            await client.call_tool("evaluate_sage", {"code": f"probe_{index} = {index}"})
        second = json.loads((await client.read_resource("resource://sagemath/monitoring/metrics"))[0].text)

    assert second["attempts"] > first["attempts"], "monitoring resource served a stale snapshot"
