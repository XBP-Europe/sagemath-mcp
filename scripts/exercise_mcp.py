"""Manual driver to exercise the SageMath MCP server over HTTP."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable

from mcp.client.session_group import ClientSessionGroup, StreamableHttpParameters

URL = os.getenv("SAGEMATH_MCP_URL", "http://127.0.0.1:31415/mcp")


async def _connect_with_retry(group: ClientSessionGroup) -> tuple:
    """Attempt to connect with basic retry logic to handle startup delays."""
    last_error: Exception | None = None
    for attempt in range(1, 11):
        try:
            return await group.connect_to_server(StreamableHttpParameters(url=URL))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - resilience helper
            last_error = exc
            await asyncio.sleep(3)
    raise RuntimeError("Unable to connect to Sage MCP server after retries") from last_error


async def _exercise(progress_cb: Callable[[float, float | None, str | None], None]) -> None:
    async with ClientSessionGroup() as group:
        session = await _connect_with_retry(group)
        initialize_result = await session.initialize()
        server_info = initialize_result.serverInfo
        print(f"Connected to {server_info.name} (version={server_info.version})")

        result1 = await session.call_tool("evaluate_sage", {"code": "value = 7"})
        print("evaluate_sage ->", result1.model_dump())

        result2 = await session.call_tool("evaluate_sage", {"code": "value * 6"})
        print("stateful evaluate ->", result2.model_dump())

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
