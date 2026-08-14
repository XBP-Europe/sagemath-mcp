"""General evaluation and the small expression tools built on it.

One of the tool modules imported by :mod:`sagemath_mcp.server` for its
registration side effect. Decorating against the shared ``mcp`` object keeps
every tool name exactly as it was; FastMCP's mount/import_server composition
would have prefixed them.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import textwrap
from typing import Annotated

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from .. import monitoring, runtime
from ..app import mcp
from ..codegen import (
    _encode_literal,
    _evaluate_structured,
    _sage_prelude,
)
from ..config import DEFAULT_SETTINGS
from ..models import (
    EvaluateResult,
)
from ..session import (
    DEFAULT_SESSION_NAME,
    SageEvaluationError,
    SageProcessError,
)
from ..text import SESSION_ARG_DESC as _SESSION_ARG_DESC

LOGGER = logging.getLogger(__name__)


# NOTE ON THIS DESCRIPTION. It used to say "use this for anything not covered by
# the specialized helpers" and then demonstrate fourteen domains that ARE covered
# by them, including codes.HammingCode(...).minimum_distance(). One line of
# instruction against fourteen lines of demonstration: measured against the CLI
# suite, Codex chose evaluate_sage for every single question. The examples below
# are deliberately restricted to work no dedicated tool performs, so that what
# this tool shows and what it says agree.
@mcp.tool(description="""\
Run arbitrary SageMath code in a persistent session; variables persist across calls.

LAST RESORT. A dedicated tool exists for most tasks and should be preferred: it \
validates arguments and returns a typed result instead of a repr string. Reach for \
one of these first:

- calculus: differentiate_expression, integrate_expression, limit_expression, \
series_expansion, symbolic_sum, solve_ode
- algebra: solve_equation, simplify_expression, expand_expression, \
factor_expression, find_root
- linear algebra: matrix_operation (determinant, inverse, eigenvalues, rank, rref, \
transpose), matrix_multiply
- discrete: number_theory_operation, combinatorics_operation (binomial, partitions, \
catalan, fibonacci, bell), graph_operation, group_operation
- specialised: elliptic_curve_operation, coding_theory_operation, \
polynomial_ring_operation, boolean_algebra_operation, geometry_operation, \
vector_calculus_operation
- data: statistics_summary, distribution_operation
- plots: plot_expression, plot3d_expression, plot_multi_expression

Use evaluate_sage only for what those do not cover, for example:

Transforms: var('t s'); laplace(sin(t), t, s); inverse_laplace(1/(s^2+1), s, t)
Modular arithmetic: Mod(17, 5); power_mod(3, 100, 97)
Recurrences: var('n'); f = function('f'); desolve_rec(f(n+2)-f(n+1)-f(n), f, [0, 1])
Continued fractions: continued_fraction(pi).convergents()[:10]
Number fields: K.<a> = NumberField(x^3 - 2); K.class_number()
Multi-step work that builds on values defined earlier in the same session.
""")
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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> EvaluateResult:
    """Run SageMath code, preserving state within the caller's MCP session."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    # Compute the key once and reuse it. Cancelling used to pass ctx.session_id,
    # which restarts the DEFAULT workspace: cancelling work in 'curves' destroyed
    # unrelated default state while the curves worker kept running.
    session_key = runtime.SESSION_MANAGER.key_for(ctx.session_id, session)
    sage_session = await runtime.SESSION_MANAGER.get(session_key)
    await ctx.info("Starting SageMath evaluation")
    progress_task = asyncio.create_task(_progress_heartbeat(ctx))
    try:
        worker_result = await sage_session.evaluate(
            code,
            want_latex=want_latex,
            capture_stdout=capture_stdout,
            timeout_seconds=timeout_seconds,
        )
    except asyncio.CancelledError:
        monitoring.record_failure("cancelled", is_security=False, details="evaluation cancelled")
        await runtime.SESSION_MANAGER.cancel(session_key)
        await ctx.warning(f"Sage evaluation cancelled; session '{session}' restarted")
        raise
    except SageEvaluationError as exc:
        monitoring.record_failure(
            exc.error_type or str(exc),
            is_security=exc.error_type == "SecurityViolation",
            details=exc.traceback or exc.stdout,
        )
        if exc.error_type == "SecurityViolation":
            await ctx.error(f"Sage security policy violation: {exc}")
        else:
            await ctx.error(f"SageMath error: {exc}")
        raise ToolError(exc.args[0]) from exc
    except SageProcessError as exc:
        cause = getattr(exc, "__cause__", None)
        details = repr(cause) if cause is not None else None
        monitoring.record_failure(
            str(exc) or exc.__class__.__name__,
            is_security=False,
            details=details,
        )
        await ctx.error("SageMath process became unavailable; restarting may help")
        raise ToolError(str(exc)) from exc
    finally:
        progress_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await progress_task
        await ctx.report_progress(1.0, 1.0, "Sage evaluation complete")
    monitoring.record_success(worker_result.elapsed_ms)
    return EvaluateResult(
        result_type=worker_result.result_type,
        result=worker_result.result,
        latex=worker_result.latex,
        stdout=_truncate_stdout(worker_result.stdout),
        elapsed_ms=worker_result.elapsed_ms,
    )


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
    settings = runtime.get_session_manager().settings
    limit = getattr(settings, "max_stdout_chars", DEFAULT_SETTINGS.max_stdout_chars)
    if not isinstance(limit, int):  # defensive: shared settings may be class-level descriptors
        limit = DEFAULT_SETTINGS.max_stdout_chars
    if len(stdout) <= limit:
        return stdout
    clipped = stdout[:limit]
    LOGGER.warning(
        "Truncated Sage stdout to %s characters (requested %s)", limit, len(stdout)
    )
    return clipped + "\n… [output truncated]"


@mcp.tool(description="Evaluate a SageMath expression and return numeric/string forms")
async def calculate_expression(
    expression: Annotated[str, Field(description="SageMath expression to evaluate")],
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await runtime.resolve_session(ctx.session_id, session)
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


@mcp.tool(description="Simplify a mathematical expression")
async def simplify_expression(
    expression: Annotated[str, Field(description="Expression to simplify")],
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await runtime.resolve_session(ctx.session_id, session)
    code = (
        _sage_prelude()
        + textwrap.dedent(
            f"""
        _expr = sage_eval({_encode_literal(expression)}, locals=_locals)
        str(simplify(_expr))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"simplified": result}


@mcp.tool(description="Expand a mathematical expression")
async def expand_expression(
    expression: Annotated[str, Field(description="Expression to expand")],
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await runtime.resolve_session(ctx.session_id, session)
    code = (
        _sage_prelude()
        + textwrap.dedent(
            f"""
        _expr = sage_eval({_encode_literal(expression)}, locals=_locals)
        str(expand(_expr))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"expanded": result}


@mcp.tool(description="Factor a mathematical expression or integer")
async def factor_expression(
    expression: Annotated[str, Field(description="Expression to factor (e.g., 'x^2 - 1' or '60')")],
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await runtime.resolve_session(ctx.session_id, session)
    code = (
        _sage_prelude()
        + textwrap.dedent(
            f"""
        _expr = sage_eval({_encode_literal(expression)}, locals=_locals)
        str(factor(_expr))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"factored": result}


@mcp.tool(description="Find a numeric root of an expression in a given interval")
async def find_root(
    expression: Annotated[str, Field(description="Expression to find root of (e.g. 'x - cos(x)')")],
    variable: Annotated[str, Field(description="Variable")] = "x",
    lower_bound: Annotated[float, Field(description="Left bound of search interval")] = -10.0,
    upper_bound: Annotated[float, Field(description="Right bound of search interval")] = 10.0,
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await runtime.resolve_session(ctx.session_id, session)
    code = (
        _sage_prelude([variable])
        + textwrap.dedent(
            f"""
        _var = var({_encode_literal(variable)})
        _expr = sage_eval({_encode_literal(expression)}, locals=_locals)
        float(find_root(_expr, {lower_bound}, {upper_bound}))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"root": result}


@mcp.tool(
    description="Execute SageMath code and stream intermediate print() output "
    "line by line. Final result is returned as usual."
)
async def evaluate_sage_streaming(
    code: Annotated[str, Field(description="SageMath code to execute")],
    timeout_seconds: Annotated[
        float | None,
        Field(description="Override timeout in seconds", gt=0.0),
    ] = None,
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> EvaluateResult:
    """Like evaluate_sage but emits each stdout line as a progress event."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    sage_session = await runtime.resolve_session(ctx.session_id, session)

    # Forward each line the moment the worker produces it. This used to await
    # the whole evaluation and only then split the accumulated stdout, so a
    # caller saw nothing until the computation had already finished -- which is
    # the opposite of what the tool promises.
    emitted = 0

    async def _forward(line: str) -> None:
        nonlocal emitted
        emitted += 1
        await ctx.report_progress(float(emitted), None, line)

    worker_result = await sage_session.evaluate(
        code,
        want_latex=False,
        capture_stdout=True,
        timeout_seconds=timeout_seconds,
        on_stdout=_forward,
    )
    monitoring.record_success(worker_result.elapsed_ms)
    return EvaluateResult(
        result_type=worker_result.result_type,
        result=worker_result.result,
        latex=None,
        stdout=_truncate_stdout(worker_result.stdout),
        elapsed_ms=worker_result.elapsed_ms,
    )
