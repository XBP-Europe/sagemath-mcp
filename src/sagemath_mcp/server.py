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


@mcp.tool(description="""\
Execute arbitrary SageMath code within a persistent session. Variables and definitions \
persist across calls. Use this for any computation not covered by the specialized helpers. \
Examples by domain:

Combinatorics: binomial(10, 3); Permutations(4).cardinality(); Combinations([1,2,3,4], 2).list()
Graph theory: G = graphs.PetersenGraph(); G.chromatic_number()
Number theory: prime_range(100); euler_phi(60); continued_fraction(pi, nterms=10)
Geometry: polytopes.cube().volume(); EllipticCurve([0,0,1,-1,0]).rank()
Probability: RealDistribution('gaussian', 1).cum_distribution_function(1.96)
Group theory: SymmetricGroup(5).order(); AlternatingGroup(4).is_abelian()
Polynomial rings: R.<a,b> = PolynomialRing(QQ); (a+b)^3
Coding theory: codes.HammingCode(GF(2), 3).minimum_distance()
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
        monitoring.record_failure("cancelled", is_security=False, details="evaluation cancelled")
        await SESSION_MANAGER.cancel(ctx.session_id)
        if ctx is not None:
            await ctx.warning("Sage evaluation cancelled; session restarted")
        raise
    except SageEvaluationError as exc:
        monitoring.record_failure(
            exc.error_type or str(exc),
            is_security=exc.error_type == "SecurityViolation",
            details=exc.traceback or exc.stdout,
        )
        if ctx is not None:
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
async def session_resource(scope: str, ctx: Context | None = None) -> str:
    """Expose a resource describing active Sage sessions for observability."""
    import json as _json

    del ctx  # resource does not require request context
    data = SESSION_MANAGER.snapshot()
    if scope != "all":
        data = [entry for entry in data if entry["session_id"] == scope]
    snapshots = [
        SessionSnapshot(
            session_id=entry["session_id"],
            live=bool(entry["live"]),
            started_at=float(entry["started_at"]),
            last_used_at=float(entry["last_used_at"]),
            idle_seconds=float(entry["idle_seconds"]),
        )
        for entry in data
    ]
    return _json.dumps([s.model_dump() for s in snapshots])


@mcp.resource("resource://sagemath/monitoring/{scope}")
async def monitoring_resource(scope: str, ctx: Context | None = None) -> str:
    """Expose aggregated metrics for observability."""
    del ctx
    if scope not in {"metrics", "all"}:
        return "[]"
    snapshot = monitoring.snapshot()
    return MonitoringSnapshot(**snapshot).model_dump_json()


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


async def _evaluate_structured(
    session, code: str, timeout_seconds: float | None = None
) -> object:
    worker_result = await session.evaluate(
        code, want_latex=False, capture_stdout=False, timeout_seconds=timeout_seconds
    )
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


@mcp.tool(description="Solve an equation or system of equations")
async def solve_equation(
    equation: Annotated[
        str | list[str],
        Field(description="Equation string (e.g., 'x^2 - 1 = 0') or list of equations for systems"),
    ],
    variable: Annotated[
        str | list[str],
        Field(description="Variable or list of variables to solve for", default="x"),
    ] = "x",
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await SESSION_MANAGER.get(ctx.session_id)
    equations = [equation] if isinstance(equation, str) else equation
    variables = [variable] if isinstance(variable, str) else variable
    code = (
        _sage_prelude(variables)
        + textwrap.dedent(
            f"""
        _vars = [var(v) for v in {_encode_literal(variables)}]
        _eqs = []
        for _eq_str in {_encode_literal(equations)}:
            parts = _eq_str.split('=')
            if len(parts) == 2:
                left = sage_eval(parts[0].strip(), locals=_locals)
                right = sage_eval(parts[1].strip(), locals=_locals)
                _eqs.append(left == right)
            else:
                _eqs.append(sage_eval(_eq_str, locals=_locals))
        if len(_eqs) == 1 and len(_vars) == 1:
            _solutions = solve(_eqs[0], _vars[0])
        else:
            _solutions = solve(_eqs, _vars)
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
    order: Annotated[
        int,
        Field(description="Order of differentiation (1 = first, 2 = second, etc.)", ge=1),
    ] = 1,
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
        str(diff(_expr, _var, {order}))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"derivative": result, "order": order}


@mcp.tool(description="Integrate an expression (indefinite or definite with bounds)")
async def integrate_expression(
    expression: Annotated[str, Field(description="Expression to integrate")],
    variable: Annotated[str, Field(description="Integration variable", default="x")] = "x",
    lower_bound: Annotated[
        str | None,
        Field(description="Lower bound for definite integral (e.g., '0', '-oo')"),
    ] = None,
    upper_bound: Annotated[
        str | None,
        Field(description="Upper bound for definite integral (e.g., '1', 'oo')"),
    ] = None,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    if (lower_bound is None) != (upper_bound is None):
        raise ToolError("Both lower_bound and upper_bound must be provided for a definite integral")
    session = await SESSION_MANAGER.get(ctx.session_id)
    definite = lower_bound is not None
    if definite:
        code = (
            _sage_prelude([variable])
            + textwrap.dedent(
                f"""
            _var = var({_encode_literal(variable)})
            _expr = sage_eval({_encode_literal(expression)}, locals=_locals)
            _lb = sage_eval({_encode_literal(lower_bound)}, locals=_locals)
            _ub = sage_eval({_encode_literal(upper_bound)}, locals=_locals)
            str(integrate(_expr, _var, _lb, _ub))
            """
            )
        )
    else:
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
    return {"integral": result, "definite": definite}


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


@mcp.tool(description="Simplify a mathematical expression")
async def simplify_expression(
    expression: Annotated[str, Field(description="Expression to simplify")],
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
        str(simplify(_expr))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"simplified": result}


@mcp.tool(description="Expand a mathematical expression")
async def expand_expression(
    expression: Annotated[str, Field(description="Expression to expand")],
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
        str(expand(_expr))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"expanded": result}


@mcp.tool(description="Factor a mathematical expression or integer")
async def factor_expression(
    expression: Annotated[str, Field(description="Expression to factor (e.g., 'x^2 - 1' or '60')")],
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
        str(factor(_expr))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"factored": result}


@mcp.tool(description="Compute the limit of an expression")
async def limit_expression(
    expression: Annotated[str, Field(description="Expression to take the limit of")],
    variable: Annotated[str, Field(description="Variable approaching the point")] = "x",
    point: Annotated[str, Field(description="Point to approach (e.g., '0', 'oo', '-oo')")] = "0",
    direction: Annotated[
        str | None,
        Field(description="Direction: 'plus' (right), 'minus' (left), or omit for both"),
    ] = None,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await SESSION_MANAGER.get(ctx.session_id)
    dir_arg = f", dir={_encode_literal(direction)}" if direction else ""
    code = (
        _sage_prelude([variable])
        + textwrap.dedent(
            f"""
        _var = var({_encode_literal(variable)})
        _expr = sage_eval({_encode_literal(expression)}, locals=_locals)
        _point = sage_eval({_encode_literal(point)}, locals=_locals)
        str(limit(_expr, _var, _point{dir_arg}))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"limit": result}


@mcp.tool(description="Compute a Taylor/Laurent series expansion")
async def series_expansion(
    expression: Annotated[str, Field(description="Expression to expand in series")],
    variable: Annotated[str, Field(description="Variable for expansion")] = "x",
    point: Annotated[str, Field(description="Point around which to expand")] = "0",
    order: Annotated[int, Field(description="Number of terms in the expansion", ge=1)] = 6,
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
        _point = sage_eval({_encode_literal(point)}, locals=_locals)
        str(_expr.series(_var == _point, {order}))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"series": result, "point": point, "order": order}


@mcp.tool(description="Perform a matrix operation (det, inverse, eigenvalues, ...)")
async def matrix_operation(
    matrix: Annotated[
        list[list[float]], Field(description="Matrix as nested list of numbers")
    ],
    operation: Annotated[
        str,
        Field(description="One of: determinant, inverse, eigenvalues, rank, rref, transpose"),
    ],
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    allowed_ops = {"determinant", "inverse", "eigenvalues", "rank", "rref", "transpose"}
    if operation not in allowed_ops:
        raise ToolError(
            f"Unknown operation '{operation}'. "
            f"Must be one of: {', '.join(sorted(allowed_ops))}"
        )
    session = await SESSION_MANAGER.get(ctx.session_id)
    _row_repr = (
        "[[float(e) if e in RR else str(e) for e in row] for row in {obj}.rows()]"
    )
    op_code = {
        "determinant": (
            "float(M.determinant()) if M.determinant() in RR"
            " else str(M.determinant())"
        ),
        "inverse": _row_repr.format(obj="M.inverse()"),
        "eigenvalues": (
            "[float(ev) if ev in RR else str(ev) for ev in M.eigenvalues()]"
        ),
        "rank": "int(M.rank())",
        "rref": _row_repr.format(obj="M.rref()"),
        "transpose": _row_repr.format(obj="M.transpose()"),
    }
    code = textwrap.dedent(
        f"""
        from sage.all import *
        M = matrix(SR, {matrix})
        {op_code[operation]}
        """
    )
    result = await _evaluate_structured(session, code)
    return {"operation": operation, "result": result}


@mcp.tool(description="Solve an ordinary differential equation")
async def solve_ode(
    equation: Annotated[
        str,
        Field(description="ODE string, e.g., \"diff(y(x),x) + y(x) = 0\""),
    ],
    function: Annotated[str, Field(description="Dependent function name (e.g., 'y')")] = "y",
    variable: Annotated[str, Field(description="Independent variable (e.g., 'x')")] = "x",
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await SESSION_MANAGER.get(ctx.session_id)
    code = (
        _sage_prelude([variable])
        + textwrap.dedent(
            f"""
        _x = var({_encode_literal(variable)})
        _y = function({_encode_literal(function)})(_x)
        _ode_locals = dict(_locals)
        _ode_locals[{_encode_literal(function)}] = _y
        _ode_locals['diff'] = diff
        parts = {_encode_literal(equation)}.split('=')
        if len(parts) == 2:
            left = sage_eval(parts[0].strip(), locals=_ode_locals)
            right = sage_eval(parts[1].strip(), locals=_ode_locals)
            _ode = left == right
        else:
            _ode = sage_eval({_encode_literal(equation)}, locals=_ode_locals)
        str(desolve(_ode, _y, ivar=_x))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"solution": result}


@mcp.tool(description="Number theory operations: is_prime, factor_integer, next_prime, gcd, lcm")
async def number_theory_operation(
    operation: Annotated[
        str,
        Field(description="Operation: 'is_prime', 'factor_integer', 'next_prime', 'gcd', 'lcm'"),
    ],
    a: Annotated[int, Field(description="Primary integer argument")],
    b: Annotated[int | None, Field(description="Second integer (required for gcd, lcm)")] = None,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    allowed_ops = {"is_prime", "factor_integer", "next_prime", "gcd", "lcm"}
    if operation not in allowed_ops:
        raise ToolError(
            f"Unknown operation '{operation}'. "
            f"Must be one of: {', '.join(sorted(allowed_ops))}"
        )
    if operation in {"gcd", "lcm"} and b is None:
        raise ToolError(f"Operation '{operation}' requires both 'a' and 'b' arguments")
    session = await SESSION_MANAGER.get(ctx.session_id)
    op_code = {
        "is_prime": f"bool(is_prime({a}))",
        "factor_integer": f"str(factor({a}))",
        "next_prime": f"int(next_prime({a}))",
        "gcd": f"int(gcd({a}, {b}))",
        "lcm": f"int(lcm({a}, {b}))",
    }
    code = _sage_prelude() + op_code[operation] + "\n"
    result = await _evaluate_structured(session, code)
    return {"operation": operation, "result": result}


@mcp.tool(description="Plot an expression and return a base64-encoded PNG image")
async def plot_expression(
    expression: Annotated[str, Field(description="Expression to plot")],
    variable: Annotated[str, Field(description="Plot variable")] = "x",
    range_min: Annotated[float, Field(description="Lower bound of plot range")] = -10.0,
    range_max: Annotated[float, Field(description="Upper bound of plot range")] = 10.0,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await SESSION_MANAGER.get(ctx.session_id)
    code = (
        _sage_prelude([variable])
        + textwrap.dedent(
            f"""
        import base64
        import io as _io
        _var = var({_encode_literal(variable)})
        _expr = sage_eval({_encode_literal(expression)}, locals=_locals)
        _plt = plot(_expr, (_var, {range_min}, {range_max}))
        _buf = _io.BytesIO()
        _plt.save(_buf, format='png')
        _buf.seek(0)
        base64.b64encode(_buf.read()).decode('ascii')
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"image_base64": result, "format": "png"}


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - CLI entrypoint
    parser = argparse.ArgumentParser(description="Run the SageMath MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "streamable-http", "sse"],
        default="stdio",
        help="Transport protocol to use.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for HTTP transports.")
    parser.add_argument("--port", type=int, default=8314, help="Port for HTTP transports.")
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
