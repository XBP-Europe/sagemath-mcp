"""Manual driver to exercise the SageMath MCP server over HTTP."""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Callable

from mcp.client.session_group import ClientSessionGroup, StreamableHttpParameters

URL = os.getenv("SAGEMATH_MCP_URL", "http://127.0.0.1:8314/mcp")


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
        server_info = initialize_result.serverInfo
        print(f"Connected to {server_info.name} (version={server_info.version})")

        result1 = await session.call_tool("evaluate_sage", {"code": "value = 7"})
        print("evaluate_sage ->", result1.model_dump())
        assert not result1.isError, f"assignment failed: {result1.model_dump()}"

        # Asserted, not just printed. Under fastmcp 4.0.3 the second call ran in
        # a fresh session, came back "'value' is not a name this server offers",
        # and this smoke test still reported success -- the one workflow it
        # exists to guard is the stateful one, so its failure must be loud.
        result2 = await session.call_tool("evaluate_sage", {"code": "value * 6"})
        print("stateful evaluate ->", result2.model_dump())
        assert not result2.isError, f"stateful read failed: {result2.model_dump()}"
        rendered = "".join(
            block.text for block in result2.content if getattr(block, "text", None)
        )
        assert "42" in rendered, f"stateful read returned the wrong value: {rendered!r}"

        async def progress_wrapper(
            progress: float,
            total: float | None,
            message: str | None,
        ) -> None:
            progress_cb(progress, total, message)

        long_running = asyncio.create_task(
            session.call_tool(
                "evaluate_sage",
                {
                    "code": "import time\nfor i in range(60):\n    time.sleep(1)\n",
                    "timeout": 600,
                },
                progress_callback=progress_wrapper,
            )
        )

        await asyncio.sleep(5)
        cancel = await session.call_tool("cancel_sage_session", {})
        print("cancel ->", cancel.model_dump())

        try:
            lr_result = await long_running
            print("long running result ->", lr_result.model_dump())
        except Exception as exc:  # pragma: no cover - manual diagnostic script
            print("long running raised ->", type(exc).__name__, exc)


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
