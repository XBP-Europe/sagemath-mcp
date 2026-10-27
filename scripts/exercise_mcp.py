"""Manual driver to exercise the SageMath MCP server over HTTP."""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Callable

from mcp import ClientSession
from mcp.client.session_group import ClientSessionGroup, StreamableHttpParameters
from mcp.types import CallToolResult, TextContent

URL = os.getenv("SAGEMATH_MCP_URL", "http://127.0.0.1:8314/mcp")
# How long a running loop may take to show up, and to stop once told to.
STOP_DEADLINE = 60.0


async def _connect_with_retry(
    group: ClientSessionGroup,
    *,
    attempts: int = 20,
    delay_seconds: float = 3.0,
    initial_delay: float = 5.0,
) -> tuple:
    """Attempt to connect and initialize with basic retry logic to handle startup delays."""
    last_error: Exception | None = None
    if initial_delay > 0:
        await asyncio.sleep(initial_delay)
    for attempt in range(1, attempts + 1):
        session = None
        try:
            session = await group.connect_to_server(StreamableHttpParameters(url=URL))
            initialize_result = await session.initialize()
            return session, initialize_result
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - resilience helper
            last_error = exc
            if session is not None:
                with contextlib.suppress(Exception):
                    await group.disconnect_from_server(session)
            print(f"Connect attempt {attempt}/{attempts} failed: {exc!r}")
        await asyncio.sleep(delay_seconds)
    raise RuntimeError("Unable to connect to Sage MCP server after retries") from last_error


async def _exercise(progress_cb: Callable[[float, float | None, str | None], None]) -> None:
    async with ClientSessionGroup() as group:
        session, initialize_result = await _connect_with_retry(group)
        server_info = initialize_result.server_info
        print(f"Connected to {server_info.name} (version={server_info.version})")

        result1 = await session.call_tool("evaluate_sage", {"code": "value = 7"})
        print("evaluate_sage ->", result1.model_dump())
        assert not result1.is_error, f"assignment failed: {result1.model_dump()}"

        # Asserted, not just printed. Under fastmcp 4.0.3 the second call ran in
        # a fresh session, came back "'value' is not a name this server offers",
        # and this smoke test still reported success -- the one workflow it
        # exists to guard is the stateful one, so its failure must be loud.
        result2 = await session.call_tool("evaluate_sage", {"code": "value * 6"})
        print("stateful evaluate ->", result2.model_dump())
        assert not result2.is_error, f"stateful read failed: {result2.model_dump()}"
        rendered = _text(result2)
        assert "42" in rendered, f"stateful read returned the wrong value: {rendered!r}"

        # Stopping a computation is only tested if one is running. This step
        # used to send `import time` + `time.sleep`, which the policy refuses
        # at once: the cancel reached an idle worker and the "long-running"
        # call had already failed, so neither interrupting nor cancelling was
        # ever exercised. A plain loop is allowed and runs for hours.
        await _stop_a_running_computation(session, progress_cb, "interrupt_sage_session")
        # Interrupting keeps the namespace: that is the point of the tool.
        kept = await session.call_tool("evaluate_sage", {"code": "value * 6"})
        print("after interrupt ->", kept.model_dump())
        assert _result(kept) == "42", (
            f"interrupting discarded the session's variables: {kept.model_dump()}"
        )

        await _stop_a_running_computation(session, progress_cb, "cancel_sage_session")
        # Cancelling restarts the worker: the variables are gone, and the new
        # worker answers.
        gone = await session.call_tool("evaluate_sage", {"code": "value * 6"})
        print("after cancel ->", gone.model_dump())
        assert gone.is_error, f"cancelling kept the session's variables: {gone.model_dump()}"
        fresh = await session.call_tool("evaluate_sage", {"code": "1 + 1"})
        print("restarted worker ->", fresh.model_dump())
        assert _result(fresh) == "2", f"the restarted worker did not answer: {fresh.model_dump()}"


def _text(result: CallToolResult) -> str:
    return "".join(block.text for block in result.content if isinstance(block, TextContent))


def _result(result: CallToolResult) -> str | None:
    """evaluate_sage's answer, or None for an error."""
    if result.is_error or not result.structured_content:
        return None
    return result.structured_content.get("result")


async def _stop_a_running_computation(
    session: ClientSession,
    progress_cb: Callable[[float, float | None, str | None], None],
    tool: str,
) -> None:
    """Start a loop that never finishes on its own, stop it with *tool*, and
    assert the call it was running in comes back as stopped."""
    running = asyncio.Event()

    async def progress_wrapper(
        progress: float,
        total: float | None,
        message: str | None,
    ) -> None:
        progress_cb(progress, total, message)
        # The server's heartbeat says "Sage running for N.Ns" while the
        # evaluation is in flight.
        if message and message.startswith("Sage running"):
            running.set()

    long_running = asyncio.create_task(
        session.call_tool(
            "evaluate_sage",
            {"code": "s = 0\nfor i in range(10^12):\n    s += i\n", "timeout": 600},
            progress_callback=progress_wrapper,
        )
    )
    try:
        await asyncio.wait_for(running.wait(), timeout=STOP_DEADLINE)
    except TimeoutError:
        if long_running.done():
            raise AssertionError(
                f"the loop ended before {tool} was sent: {long_running.result().model_dump()}"
            ) from None
        raise AssertionError(f"no progress heartbeat within {STOP_DEADLINE}s") from None

    stop = await session.call_tool(tool, {})
    print(f"{tool} ->", stop.model_dump())
    assert not stop.is_error, f"{tool} failed: {stop.model_dump()}"
    # interrupt_sage_session answers "No running computation" when it found
    # nothing to signal, which here means the loop was not running after all.
    assert "No running computation" not in _text(stop), f"{tool} found nothing running"

    # Bounded: a stop that does not work would otherwise wait out the loop's
    # 600 s timeout and look like a slow pass.
    try:
        stopped = await asyncio.wait_for(long_running, timeout=STOP_DEADLINE)
    except TimeoutError:
        raise AssertionError(f"the loop was still running {STOP_DEADLINE}s after {tool}") from None
    print("long running result ->", stopped.model_dump())
    assert stopped.is_error, f"the loop finished instead of stopping: {stopped.model_dump()}"


async def main() -> None:
    progress_events: list[tuple[float, float | None, str | None]] = []

    def record_progress(progress: float, total: float | None, message: str | None) -> None:
        progress_events.append((progress, total, message))
        print(f"progress: {progress=} {total=} {message=}")

    await _exercise(record_progress)

    print("Progress events captured:")
    for event in progress_events:
        print("  -", event)


if __name__ == "__main__":
    asyncio.run(main())
