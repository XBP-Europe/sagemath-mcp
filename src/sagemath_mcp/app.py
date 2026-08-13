"""The FastMCP application object and its lifecycle.

Separated from ``server`` to break a cycle: the tool modules need something to
decorate against, and ``server`` needs the tool modules imported so those
decorators run. This module imports neither, so the graph stays a DAG:
``app`` -> ``runtime``, ``tools/*`` -> ``app``, ``server`` -> ``tools``.

FastMCP's own composition (``mount``/``import_server``) is deliberately not used
for that split: it prefixes tool names, which would rename every tool a client
has configured.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastmcp import FastMCP
from fastmcp.server.middleware.caching import (
    CallToolSettings,
    GetPromptSettings,
    ReadResourceSettings,
    ResponseCachingMiddleware,
)
from fastmcp.server.middleware.logging import LoggingMiddleware
from fastmcp.server.middleware.timing import TimingMiddleware

from . import __version__, runtime

LOGGER = logging.getLogger(__name__)

_CULL_TASK: asyncio.Task[None] | None = None


MCP_INSTRUCTIONS = """
You are connected to a dedicated SageMath runtime. Each MCP session gets its own
stateful Sage process, so variables, functions, and assumptions persist between calls
to `evaluate_sage` and the helper tools. Typical workflows include:

- General symbolic/numeric computation via `evaluate_sage` (supports optional LaTeX).
- High-level helpers: `calculate_expression`, `solve_equation`, `differentiate_expression`,
  `integrate_expression`, `matrix_multiply`, and `statistics_summary`.
- Session management: `reset_sage_session` clears state; `cancel_sage_session` restarts the
  worker; monitoring data is exposed via `resource://sagemath/monitoring/metrics`.

Guidance for best results:

- Always provide explicit Sage code; avoid relying on ambient imports beyond standard
  Sage libraries. Use `var('x')`/`matrix(...)` etc. inside the code snippet.
- Chain computations within the same MCP session to reuse definitions (e.g., assign `f =` and
  call `evaluate_sage` again to operate on `f`).
- Long-running jobs emit progress heartbeat events roughly every 1.5 seconds. You can adjust
  timeouts via the `timeout` parameter.
- Capture stdout only when needed; disabling it speeds up large iterations.
- The security policy rejects arbitrary imports, `eval`/`exec`, the indirection helpers
  (`getattr`, `sage_eval`), dunder access, and the `os`/`sys`/`subprocess`/`shutil`/
  `socket`/`pathlib` modules -- wherever those names are read, not only where they are
  called. It is defence in depth against accidents, not a boundary against adversarial
  code; the container is the boundary. If you hit a security violation, rewrite the
  computation with Sage primitives instead.
""".strip()

_CULL_TASK: asyncio.Task[None] | None = None


async def _cull_loop(interval: float = 60.0) -> None:
    """Periodically cull idle Sage sessions according to the manager policy."""
    try:
        while True:
            await asyncio.sleep(interval)
            await runtime.SESSION_MANAGER.cull_idle()
    except asyncio.CancelledError:  # pragma: no cover - background task shutdown
        LOGGER.debug("Session culler cancelled")


@contextlib.asynccontextmanager
async def _lifespan(app: FastMCP) -> AsyncIterator[None]:
    """Manage background tasks and shutdown for the MCP server."""
    del app  # unused but kept for signature compatibility
    global _CULL_TASK
    LOGGER.info("Starting SageMath MCP server (version %s)", __version__)
    _CULL_TASK = asyncio.create_task(_cull_loop())
    try:
        yield
    finally:
        if _CULL_TASK:
            _CULL_TASK.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await _CULL_TASK
        _CULL_TASK = None
        await runtime.SESSION_MANAGER.shutdown()


mcp = FastMCP(
    name="sagemath-mcp",
    instructions=MCP_INSTRUCTIONS,
    version=__version__,
    lifespan=_lifespan,
)
mcp.add_middleware(TimingMiddleware())
mcp.add_middleware(
    LoggingMiddleware(include_payloads=False, include_payload_length=True)
)
# Tool-call and resource caching are OFF, deliberately.
#
# The cache key covers the tool name, arguments and auth identity, but NOT the
# MCP session id, and unauthenticated clients share one anonymous partition.
# Every tool here is stateful, so with the defaults (one hour, all tools) two
# clients making the same call collide: the second gets the first's cached
# response in microseconds without its own worker ever executing, and then finds
# the variable undefined. The reverse is a confidentiality problem -- a
# state-dependent expression can return another client's value.
#
# Repeated reset/cancel/start/stop calls were also skipped while reporting
# success, and the session and monitoring resources served stale snapshots.
#
# Only the list_* caches remain: the tool, resource and prompt catalogues are
# identical for every caller and do not change at runtime.
mcp.add_middleware(
    ResponseCachingMiddleware(
        call_tool_settings=CallToolSettings(enabled=False),
        read_resource_settings=ReadResourceSettings(enabled=False),
        get_prompt_settings=GetPromptSettings(enabled=False),
    )
)


