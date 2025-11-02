"""FastMCP server exposing SageMath as a stateful tool."""

from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
import json
import logging
import textwrap
from collections.abc import AsyncIterator, Iterable
from typing import Annotated

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware.caching import ResponseCachingMiddleware
from fastmcp.server.middleware.logging import LoggingMiddleware
from fastmcp.server.middleware.timing import TimingMiddleware
from pydantic import Field

from . import __version__, monitoring
from .config import DEFAULT_SETTINGS
from .models import (
    DocumentationLink,
    EvaluateResult,
    MonitoringSnapshot,
    ResetResponse,
    SessionSnapshot,
)
from .session import (
    SageEvaluationError,
    SageProcessError,
    SageSessionManager,
)

LOGGER = logging.getLogger(__name__)

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
- The security sandbox blocks arbitrary imports, `eval`, and filesystem/process APIs. If you
  hit a security violation, rewrite the computation with Sage primitives instead.
""".strip()

SETTINGS = DEFAULT_SETTINGS
SESSION_MANAGER = SageSessionManager(SETTINGS)
_CULL_TASK: asyncio.Task[None] | None = None
DOC_LINKS: list[DocumentationLink] = [
    DocumentationLink(
        title="SageMath Reference Manual",
        url="https://doc.sagemath.org/html/en/reference",
        slug="reference",
        description="Comprehensive API and functionality reference for SageMath.",
    ),
    DocumentationLink(
        title="Sage Tutorial",
        url="https://doc.sagemath.org/html/en/tutorial",
        slug="tutorial",
        description="Gentle introduction to SageMath syntax and workflows.",
    ),
]


async def _cull_loop(interval: float = 60.0) -> None:
    """Periodically cull idle Sage sessions according to the manager policy."""
    try:
        while True:
            await asyncio.sleep(interval)
            await SESSION_MANAGER.cull_idle()
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
        await SESSION_MANAGER.shutdown()


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
mcp.add_middleware(ResponseCachingMiddleware())


@mcp.tool(description="Execute SageMath code within a persistent session")
async def evaluate_sage(
    code: Annotated[str, Field(description="SageMath code to execute")],
    want_latex: Annotated[
        bool, Field(description="Return LaTeX representation when possible")
    ] = False,
    capture_stdout: Annotated[
        bool, Field(description="Capture stdout emitted by Sage code")
    ] = True,
    timeout_seconds: Annotated[
        float | None,
        Field(
            description="Override the evaluation timeout in seconds",
            alias="timeout",
            validation_alias="timeout",
            serialization_alias="timeout",
            gt=0.0,
            default=None,
        ),
    ] = None,
    ctx: Context | None = None,
) -> EvaluateResult:
    """Run SageMath code, preserving state within the caller's MCP session."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await SESSION_MANAGER.get(ctx.session_id)
    progress_task: asyncio.Task[None] | None = None
    if ctx is not None:
        await ctx.info("Starting SageMath evaluation")
        progress_task = asyncio.create_task(_progress_heartbeat(ctx))
    try:
        worker_result = await session.evaluate(
            code,
            want_latex=want_latex,
            capture_stdout=capture_stdout,
            timeout_seconds=timeout_seconds,
        )
    except asyncio.CancelledError:
        monitoring.record_failure("cancelled", is_security=False)
        await SESSION_MANAGER.cancel(ctx.session_id)
        if ctx is not None:
            await ctx.warning("Sage evaluation cancelled; session restarted")
        raise
    except SageEvaluationError as exc:
        monitoring.record_failure(
            exc.error_type or str(exc), is_security=exc.error_type == "SecurityViolation"
        )
        if ctx is not None:
            if exc.error_type == "SecurityViolation":
                await ctx.error(f"Sage security policy violation: {exc}")
            else:
                await ctx.error(f"SageMath error: {exc}")
        raise ToolError(exc.args[0]) from exc
    except SageProcessError as exc:
        monitoring.record_failure(str(exc) or exc.__class__.__name__, is_security=False)
        if ctx is not None:
            await ctx.error("SageMath process became unavailable; restarting may help")
        raise ToolError(str(exc)) from exc
    finally:
        if progress_task:
            progress_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await progress_task
        if ctx is not None:
            await ctx.report_progress(1.0, 1.0, "Sage evaluation complete")
    monitoring.record_success(worker_result.elapsed_ms)
    return EvaluateResult(
        result_type=worker_result.result_type,
        result=worker_result.result,
        latex=worker_result.latex,
        stdout=_truncate_stdout(worker_result.stdout),
        elapsed_ms=worker_result.elapsed_ms,
    )


@mcp.tool(description="Reset the SageMath session state for the current MCP session")
async def reset_sage_session(ctx: Context | None = None) -> ResetResponse:
    """Reset the Sage session associated with the current MCP session."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to reset state")
    await SESSION_MANAGER.reset(ctx.session_id)
    await ctx.info("Sage session reset")
    return ResetResponse()


@mcp.tool(description="Cancel any running Sage computation and restart the worker")
async def cancel_sage_session(ctx: Context | None = None) -> ResetResponse:
    """Cancel in-flight work by restarting the backing Sage worker."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to cancel work")
    await SESSION_MANAGER.cancel(ctx.session_id)
    await ctx.warning("Sage session cancelled and restarted")
    return ResetResponse(message="Session cancelled and restarted")


@mcp.resource("resource://sagemath/session/{scope}")
async def session_resource(scope: str, ctx: Context | None = None) -> list[SessionSnapshot]:
    """Expose a resource describing active Sage sessions for observability."""
    del ctx  # resource does not require request context
    data = SESSION_MANAGER.snapshot()
    if scope != "all":
        data = [entry for entry in data if entry["session_id"] == scope]
    return [
        SessionSnapshot(
            session_id=entry["session_id"],
            live=bool(entry["live"]),
            started_at=float(entry["started_at"]),
            last_used_at=float(entry["last_used_at"]),
            idle_seconds=float(entry["idle_seconds"]),
        )
        for entry in data
    ]


@mcp.resource("resource://sagemath/monitoring/{scope}")
async def monitoring_resource(scope: str, ctx: Context | None = None) -> list[MonitoringSnapshot]:
    """Expose aggregated metrics for observability."""
    del ctx
    if scope not in {"metrics", "all"}:
        return []
    snapshot = monitoring.snapshot()
    return [MonitoringSnapshot(**snapshot)]


async def _progress_heartbeat(ctx: Context, interval: float = 1.5) -> None:
    """Emit periodic progress updates so clients can show activity."""
    elapsed = 0.0
    try:
        while True:
            await asyncio.sleep(interval)
            elapsed += interval
            await ctx.report_progress(elapsed, None, f"Sage running for {elapsed:.1f}s")
    except asyncio.CancelledError:  # pragma: no cover - background task shutdown
        return


def _truncate_stdout(stdout: str) -> str:
    """Clamp stdout to the configured limit while signalling truncation."""
    limit = getattr(SESSION_MANAGER.settings, "max_stdout_chars", DEFAULT_SETTINGS.max_stdout_chars)
    if not isinstance(limit, int):  # defensive: shared settings may be class-level descriptors
        limit = DEFAULT_SETTINGS.max_stdout_chars
    if len(stdout) <= limit:
        return stdout
    clipped = stdout[:limit]
    LOGGER.warning(
        "Truncated Sage stdout to %s characters (requested %s)", limit, len(stdout)
    )
    return clipped + "\n… [output truncated]"


@mcp.resource("resource://sagemath/docs/{scope}")
async def documentation_resource(scope: str, ctx: Context | None = None) -> list[DocumentationLink]:
    del ctx
    if scope == "all":
        return DOC_LINKS
    return [link for link in DOC_LINKS if link.slug == scope]


def _encode_literal(value: str | Iterable) -> str:
    return json.dumps(value)


async def _evaluate_structured(session, code: str) -> object:
    worker_result = await session.evaluate(code, want_latex=False, capture_stdout=False)
    if worker_result.result is None:
        return None
    try:
        return ast.literal_eval(worker_result.result)
    except Exception:
        return worker_result.result


def _sage_prelude(extra_locals: Iterable[str] | None = None) -> str:
    names = ["x", "y", "z", "t"]
    if extra_locals:
        names.extend(extra_locals)
    locals_list = ", ".join(f"'{n}'" for n in dict.fromkeys(names))
    return textwrap.dedent(
        f"""
        from sage.all import *
        from sage.all import sage_eval
        _locals = {{name: var(name) for name in [{locals_list}]}}
        """
    )


@mcp.tool(description="Evaluate a SageMath expression and return numeric/string forms")
async def calculate_expression(
    expression: Annotated[str, Field(description="SageMath expression to evaluate")],
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await SESSION_MANAGER.get(ctx.session_id)
    code = (
        _sage_prelude()
        + textwrap.dedent(
            f"""
        _expr = sage_eval({_encode_literal(expression)}, locals=_locals)
        if hasattr(_expr, 'n'):
            try:
                _numeric = float(_expr.n())
            except (TypeError, ValueError):
                _numeric = None
        else:
            try:
                _numeric = float(_expr)
            except (TypeError, ValueError):
                _numeric = None
        _payload = {{'string': str(_expr)}}
        if _numeric is not None:
            _payload['numeric'] = _numeric
        _payload
        """
        )
    )
    payload = await _evaluate_structured(session, code)
    if not isinstance(payload, dict):
        return {"string": str(payload)}
    return payload


@mcp.tool(description="Solve an equation for a single variable")
async def solve_equation(
    equation: Annotated[str, Field(description="Equation string, e.g., 'x^2 - 1 = 0'")],
    variable: Annotated[str, Field(description="Variable to solve for", default="x")] = "x",
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await SESSION_MANAGER.get(ctx.session_id)
    code = (
        _sage_prelude([variable])
        + textwrap.dedent(
            f"""
        _var = var({_encode_literal(variable)})
        parts = {_encode_literal(equation)}.split('=')
        if len(parts) == 2:
            left = sage_eval(parts[0], locals=_locals)
            right = sage_eval(parts[1], locals=_locals)
            _solutions = solve(left == right, _var)
        else:
            expr = sage_eval({_encode_literal(equation)}, locals=_locals)
            _solutions = solve(expr, _var)
        [str(sol) for sol in _solutions]
        """
        )
    )
    solutions = await _evaluate_structured(session, code)
    return {"solutions": solutions}


@mcp.tool(description="Differentiate an expression with respect to a variable")
async def differentiate_expression(
    expression: Annotated[str, Field(description="Expression to differentiate")],
    variable: Annotated[str, Field(description="Variable for differentiation", default="x")] = "x",
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await SESSION_MANAGER.get(ctx.session_id)
    code = (
        _sage_prelude([variable])
        + textwrap.dedent(
            f"""
        _var = var({_encode_literal(variable)})
        _expr = sage_eval({_encode_literal(expression)}, locals=_locals)
        str(diff(_expr, _var))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"derivative": result}


@mcp.tool(description="Integrate an expression with respect to a variable")
async def integrate_expression(
    expression: Annotated[str, Field(description="Expression to integrate")],
    variable: Annotated[str, Field(description="Integration variable", default="x")] = "x",
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await SESSION_MANAGER.get(ctx.session_id)
    code = (
        _sage_prelude([variable])
        + textwrap.dedent(
            f"""
        _var = var({_encode_literal(variable)})
        _expr = sage_eval({_encode_literal(expression)}, locals=_locals)
        str(integrate(_expr, _var))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"integral": result}


@mcp.tool(description="Compute descriptive statistics for a dataset")
async def statistics_summary(
    data: Annotated[list[float], Field(description="List of numeric values")],
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await SESSION_MANAGER.get(ctx.session_id)
    code = textwrap.dedent(
        f"""
        import statistics as _stats
        data = {data}
        stats = {{
            'mean': float(_stats.mean(data)),
            'median': float(_stats.median(data)),
            'population_variance': float(_stats.pvariance(data)),
            'sample_variance': float(_stats.variance(data)),
            'population_std_dev': float(_stats.pstdev(data)),
            'sample_std_dev': float(_stats.stdev(data)),
            'min': float(min(data)),
            'max': float(max(data)),
        }}
        stats
        """
    )
    return await _evaluate_structured(session, code)


@mcp.tool(description="Multiply two matrices and return the result as nested lists")
async def matrix_multiply(
    matrix_a: Annotated[list[list[float]], Field(description="Left matrix (rows of numbers)")],
    matrix_b: Annotated[list[list[float]], Field(description="Right matrix (rows of numbers)")],
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await SESSION_MANAGER.get(ctx.session_id)
    code = textwrap.dedent(
        f"""
        from sage.all import *
        A = matrix(SR, {matrix_a})
        B = matrix(SR, {matrix_b})
        C = A * B
        [[float(entry) if entry in RR else str(entry) for entry in row] for row in C.rows()]
        """
    )
    product = await _evaluate_structured(session, code)
    return {"product": product}


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - CLI entrypoint
    parser = argparse.ArgumentParser(description="Run the SageMath MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "streamable-http", "sse"],
        default="stdio",
        help="Transport protocol to use.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for HTTP transports.")
    parser.add_argument("--port", type=int, default=31415, help="Port for HTTP transports.")
    parser.add_argument(
        "--path",
        default=None,
        help="HTTP path when using streamable-http or SSE transports.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Root logging level (default: INFO).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    transport_kwargs: dict[str, object] = {}
    if args.transport != "stdio":
        transport_kwargs.update({"host": args.host, "port": args.port})
        if args.path:
            transport_kwargs["path"] = args.path

    mcp.run(transport=args.transport, **transport_kwargs)


if __name__ == "__main__":  # pragma: no cover
    main()
