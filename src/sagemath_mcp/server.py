"""FastMCP server exposing SageMath as a stateful tool."""

from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
import json
import logging
import re
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
from .security import SECURITY_POLICY, SecurityViolation, validate_module
from .session import (
    DEFAULT_SESSION_NAME,
    SageEvaluationError,
    SageProcessError,
    SageSessionManager,
)

LOGGER = logging.getLogger(__name__)

_SESSION_ARG_DESC = (
    "Named workspace to use. Workspaces have independent variables; "
    f"omit for '{DEFAULT_SESSION_NAME}'."
)

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


# ---------------------------------------------------------------------------
# HTTP health check endpoint (non-MCP, for Kubernetes probes)
# ---------------------------------------------------------------------------


async def health_check(request: object) -> object:
    """Return 200 with server status for liveness/readiness probes."""
    from starlette.responses import JSONResponse

    sessions = SESSION_MANAGER.snapshot()
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "active_sessions": len(sessions),
        }
    )


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

Transforms: laplace(sin(t), t, s); inverse_laplace(1/(s^2+1), s, t)
Modular arithmetic: Mod(17, 5); power_mod(3, 100, 97)
Recurrences: desolve_rsolve(f(n+2)-f(n+1)-f(n), f, [0, 1])
Continued fractions: continued_fraction(pi, nterms=10)
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
    sage_session = await SESSION_MANAGER.get(SESSION_MANAGER.key_for(ctx.session_id, session))
    progress_task: asyncio.Task[None] | None = None
    if ctx is not None:
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
async def reset_sage_session(
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> ResetResponse:
    """Reset the Sage session associated with the current MCP session."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to reset state")
    await SESSION_MANAGER.reset(SESSION_MANAGER.key_for(ctx.session_id, session))
    await ctx.info(f"Sage session '{session}' reset")
    return ResetResponse()


@mcp.tool(
    description="Interrupt a running Sage computation while keeping variables defined so far"
)
async def interrupt_sage_session(
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> ResetResponse:
    """Signal the worker to abandon its computation without losing state.

    Prefer this over cancel_sage_session: cancelling restarts the worker and
    discards every variable, which is the worse outcome when the state was
    expensive to build.
    """
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to interrupt work")
    key = SESSION_MANAGER.key_for(ctx.session_id, session)
    interrupted = await SESSION_MANAGER.interrupt(key)
    if not interrupted:
        # No worker to signal: either nothing has run yet in this workspace, or
        # it has already exited. Not an error, but say which.
        await ctx.info(f"No running Sage worker for session '{session}'")
        return ResetResponse(message=f"No running computation in session '{session}'")
    await ctx.warning(f"Interrupted session '{session}'; state preserved")
    return ResetResponse(message=f"Interrupted session '{session}'; state preserved")


@mcp.tool(description="Cancel any running Sage computation and restart the worker")
async def cancel_sage_session(
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> ResetResponse:
    """Cancel in-flight work by restarting the backing Sage worker.

    This discards the namespace. Use interrupt_sage_session to stop a
    computation while keeping it.
    """
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to cancel work")
    await SESSION_MANAGER.cancel(SESSION_MANAGER.key_for(ctx.session_id, session))
    await ctx.warning(f"Sage session '{session}' cancelled and restarted")
    return ResetResponse(message="Session cancelled and restarted")


@mcp.tool(description="Start a named Sage workspace with its own independent variables")
async def start_sage_session(
    name: Annotated[str, Field(description="Workspace name, e.g. 'curves' or 'scratch'")],
    ctx: Context | None = None,
) -> ResetResponse:
    """Create a named workspace so one client can hold several at once.

    Workspaces are independent: a variable defined in one is invisible to the
    others. Calling this for an existing name is harmless.
    """
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to start a session")
    if not name.strip():
        raise ToolError("Session name must not be empty")
    await SESSION_MANAGER.get(SESSION_MANAGER.key_for(ctx.session_id, name))
    await ctx.info(f"Started Sage session '{name}'")
    return ResetResponse(message=f"Session '{name}' ready")


@mcp.tool(description="List the named Sage workspaces belonging to this client")
async def list_sage_sessions(ctx: Context | None = None) -> dict:
    """Report every workspace for this client, with liveness and statement counts."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to list sessions")
    sessions = await SESSION_MANAGER.list_for_scope(ctx.session_id)
    return {"sessions": sessions, "count": len(sessions)}


@mcp.tool(description="Stop a named Sage workspace and release its worker")
async def stop_sage_session(
    name: Annotated[str, Field(description="Workspace name to stop")],
    ctx: Context | None = None,
) -> ResetResponse:
    """Terminate one workspace. Other workspaces are unaffected."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required to stop a session")
    stopped = await SESSION_MANAGER.stop(ctx.session_id, name)
    if not stopped:
        raise ToolError(f"No Sage session named '{name}' for this client")
    await ctx.info(f"Stopped Sage session '{name}'")
    return ResetResponse(message=f"Session '{name}' stopped")


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


# Samples per axis for the 3D surface. 48x48 keeps the rendered surface smooth
# while staying well inside the evaluation timeout.
_PLOT3D_GRID = 48


def _normalize_source(value):
    """Collapse whitespace in strings destined for sage_eval.

    Every tool here evaluates its input as a *single* expression, so an
    embedded newline is a syntax error ("2 +\\n2" fails). Clients are language
    models, which wrap and indent freely, so runs of whitespace are folded to a
    single space. evaluate_sage does not pass through here: it takes real
    multi-line code and keeps its newlines.
    """
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, (list, tuple)):
        return [_normalize_source(item) for item in value]
    return value


def _validated_expression(text: str) -> str:
    """Check a caller-supplied fragment before it is embedded in generated code.

    The helper tools wrap caller input in sage_eval("<text>"). The AST validator
    sees only a string constant there, so until this existed the entire
    specialised tool surface evaluated caller code unchecked:
    calculate_expression("__import__('os').getuid()") returned the container uid.

    Validating the fragment as an expression in its own right closes that, and
    is what makes the trusted worker path in _evaluate_structured safe.
    """
    if not isinstance(text, str):
        return text
    stripped = text.strip()
    if not stripped:
        return text
    try:
        parsed = ast.parse(stripped, mode="eval")
    except SyntaxError:
        # Not parseable as a Python expression. Sage's preparser accepts things
        # Python does not (R.<a,b> = ...), so this is not automatically a
        # violation; let the worker report the real error.
        return text
    try:
        validate_module(
            ast.Module(body=[ast.Expr(value=parsed.body)], type_ignores=[]),
            code=stripped,
            policy=SECURITY_POLICY,
        )
    except SecurityViolation as exc:
        raise ToolError(f"Rejected by the security policy: {exc}") from exc
    return text


def _encode_literal(value: str | Iterable) -> str:
    if isinstance(value, str):
        _validated_expression(value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str):
                _validated_expression(item)
    return json.dumps(_normalize_source(value))


# Identifiers in a bound or point, e.g. the "a" in an integral up to a.
_IDENTIFIER_RE = re.compile(r"\b([A-Za-z_]\w*)\b")

# A bare index-style name such as n, k, N or x1.
_SHORT_NAME_RE = re.compile(r"^[A-Za-z]\d*$")

# Single-letter names that are constants in Sage, not free variables.
_PROTECTED_CONSTANTS = frozenset({"e", "i", "I"})

# A named graph from Sage's catalogue: "PetersenGraph", "PetersenGraph()" or a
# parameterised one such as "CompleteGraph(4)".
_NAMED_GRAPH_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*(?P<call>\(.*\))?$", re.DOTALL)


def _declare_free_symbols(*sources: str | None) -> str:
    """Code that declares any unknown identifier in *sources* as a symbol.

    A bound may legitimately be symbolic -- integrating to "a", or summing to
    "n" -- but the prelude only declares x, y, z, t plus the tool's own
    variable, so anything else raised "name 'a' is not defined".

    Names Sage already defines are left alone. Declaring them would shadow the
    real object and break the very inputs that do work today: var('oo') would
    turn infinity into an ordinary symbol, and the same applies to pi, e, I and
    every function name such as sin or sqrt.
    """
    names: set[str] = set()
    for source in sources:
        if source:
            names.update(_IDENTIFIER_RE.findall(source))
    if not names:
        return ""
    # Short names win over anything Sage happens to define, because Sage's
    # namespace collides with ordinary index names: "n" and "N" are
    # numerical_approx, so summing to n resolved the bound to a function rather
    # than a symbol. The true constants are the exception and must never be
    # shadowed -- e is Euler's number, and i and I are the imaginary unit.
    forced = sorted(
        name for name in names if _SHORT_NAME_RE.match(name) and name not in _PROTECTED_CONSTANTS
    )
    # Longer names keep the conservative check, so sin, sqrt, pi, oo, gamma and
    # every other spelled-out Sage object continues to mean what it says.
    conditional = sorted(names.difference(forced))

    # Emitted as a single physical line. These snippets are interpolated into
    # templates that are then passed through textwrap.dedent, and a multi-line
    # block would arrive unindented, destroying the common prefix dedent relies
    # on ("unexpected indent" at import time).
    parts = ["import sage.all as _sage_ns"]
    if forced:
        parts.append(f"_locals.update({{_n: var(_n) for _n in {forced!r} if _n not in _locals}})")
    if conditional:
        parts.append(
            f"_locals.update({{_n: var(_n) for _n in {conditional!r} "
            "if _n not in _locals and not hasattr(_sage_ns, _n)})"
        )
    return "; ".join(parts)


# Beyond 2^53 a JSON number is no longer exactly representable as an IEEE
# double, which is what JavaScript-based MCP clients parse numbers into.
_EXACT_JSON_INT_LIMIT = 2**53


def _exact_int(value: int | str | float, name: str) -> int:
    """Coerce a tool argument to an exact integer, refusing lossy input.

    A float here means the value already went through a double. 10^30 arrives
    as 1000000000000000019884624838656, and next_prime() on that returns a
    perfectly plausible wrong answer -- the failure mode is a wrong number, not
    an error, which is why this rejects rather than rounds.
    """
    if isinstance(value, bool):  # bool is an int subclass; never meant here
        raise ToolError(f"'{name}' must be an integer, got a boolean")
    if isinstance(value, str):
        text = value.strip().replace("_", "")
        try:
            return int(text, 10)
        except ValueError:
            raise ToolError(f"'{name}' is not a decimal integer: {value!r}") from None
    if isinstance(value, float):
        if not value.is_integer():
            raise ToolError(f"'{name}' must be a whole number, got {value!r}")
        if abs(value) > _EXACT_JSON_INT_LIMIT:
            raise ToolError(
                f"'{name}' arrived as a floating-point number larger than 2^53, so its "
                "exact value is already lost. Pass it as a decimal string instead, "
                f'for example "{int(value)}".'
            )
        return int(value)
    return int(value)


def _check_matrix(rows: list[list[float]], name: str) -> None:
    """Reject shapes Sage would only complain about obscurely, or not at all.

    An empty matrix is the dangerous one: Sage treats [] as the 0x0 matrix and
    reports its determinant as 1.0, which looks like a real answer.
    """
    if not rows or not all(isinstance(row, (list, tuple)) for row in rows):
        raise ToolError(f"'{name}' must be a non-empty list of rows")
    if not rows[0]:
        raise ToolError(f"'{name}' rows must be non-empty")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        widths = sorted({len(row) for row in rows})
        raise ToolError(
            f"'{name}' rows must all have the same length; found lengths {widths}"
        )


def _normal_parameters(parameters: list[float]) -> tuple[float, float]:
    """Return (mu, sigma) for the documented [mu, sigma] parameter list."""
    if len(parameters) >= 2:
        return float(parameters[0]), float(parameters[1])
    if len(parameters) == 1:
        # A single parameter is the standard deviation, matching how the
        # previous implementation treated a one-element list.
        return 0.0, float(parameters[0])
    return 0.0, 1.0


def _distribution_mean(distribution: str, parameters: list[float]) -> float:
    """Analytic mean for the supported continuous distributions."""
    p = [float(v) for v in parameters]
    if distribution == "normal":
        return _normal_parameters(p)[0]
    if distribution == "exponential":
        # Sage parameterises RealDistribution('exponential', mu) by the mean.
        return p[0] if p else 1.0
    if distribution == "uniform":
        if len(p) < 2:
            raise ToolError("uniform requires parameters [a, b]")
        return (p[0] + p[1]) / 2
    if distribution == "chi_squared":
        return p[0] if p else 1.0
    if distribution == "student_t":
        nu = p[0] if p else 1.0
        if nu <= 1:
            raise ToolError("student_t mean is undefined for degrees of freedom <= 1")
        return 0.0
    if distribution == "beta":
        if len(p) < 2:
            raise ToolError("beta requires parameters [a, b]")
        return p[0] / (p[0] + p[1])
    if distribution == "gamma":
        if len(p) < 2:
            raise ToolError("gamma requires parameters [shape, scale]")
        return p[0] * p[1]
    raise ToolError(f"No analytic mean available for distribution '{distribution}'")


def _distribution_variance(distribution: str, parameters: list[float]) -> float:
    """Analytic variance for the supported continuous distributions."""
    p = [float(v) for v in parameters]
    if distribution == "normal":
        return _normal_parameters(p)[1] ** 2
    if distribution == "exponential":
        mu = p[0] if p else 1.0
        return mu**2
    if distribution == "uniform":
        if len(p) < 2:
            raise ToolError("uniform requires parameters [a, b]")
        return (p[1] - p[0]) ** 2 / 12
    if distribution == "chi_squared":
        return 2 * (p[0] if p else 1.0)
    if distribution == "student_t":
        nu = p[0] if p else 1.0
        if nu <= 2:
            raise ToolError("student_t variance is undefined for degrees of freedom <= 2")
        return nu / (nu - 2)
    if distribution == "beta":
        if len(p) < 2:
            raise ToolError("beta requires parameters [a, b]")
        a, b = p[0], p[1]
        return a * b / ((a + b) ** 2 * (a + b + 1))
    if distribution == "gamma":
        if len(p) < 2:
            raise ToolError("gamma requires parameters [shape, scale]")
        return p[0] * p[1] ** 2
    raise ToolError(f"No analytic variance available for distribution '{distribution}'")


async def _evaluate_structured(
    session, code: str, timeout_seconds: float | None = None
) -> object:
    """Run a snippet this server generated.

    trusted=True permits sage_eval, which every helper template is built on.
    That is only safe because the caller-supplied fragments interpolated into
    the template are validated separately by _validated_expression before they
    get here -- otherwise the helpers would be an unguarded path straight past
    the AST policy, which is exactly what they were.
    """
    worker_result = await session.evaluate(
        code,
        want_latex=False,
        capture_stdout=False,
        timeout_seconds=timeout_seconds,
        trusted=True,
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
            {_declare_free_symbols(lower_bound, upper_bound)}
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


@mcp.tool(description=(
        "Descriptive statistics for a list of numbers: mean, median, population "
        "and sample variance and standard deviation, min and max. Prefer this "
        "over evaluate_sage for summary statistics."
    ))
async def statistics_summary(
    data: Annotated[list[float], Field(description="List of numeric values")],
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    # Without this the generated code raised a bare "list index out of range"
    # from the median calculation, which says nothing about what to send instead.
    if not data:
        raise ToolError("statistics_summary requires at least one value in 'data'")
    session = await SESSION_MANAGER.get(ctx.session_id)
    code = (
        _sage_prelude()
        + textwrap.dedent(
            f"""
        _data = {_encode_literal(data)}
        _n = len(_data)
        _mean = float(mean(_data))
        _sorted = sorted(_data)
        _mid = _n // 2
        _median = float((_sorted[_mid] + _sorted[~_mid]) / 2)
        _pvar = float(sum((x - _mean)**2 for x in _data) / _n)
        _svar = float(sum((x - _mean)**2 for x in _data) / (_n - 1)) if _n > 1 else 0.0
        {{
            'mean': _mean,
            'median': _median,
            'population_variance': _pvar,
            'sample_variance': _svar,
            'population_std_dev': float(sqrt(_pvar)),
            'sample_std_dev': float(sqrt(_svar)),
            'min': float(min(_data)),
            'max': float(max(_data)),
        }}
        """
        )
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
    # Checked here so a shape mismatch reports the shapes. Left to Sage it
    # surfaced as "unsupported operand parent(s) for *: 'Full MatrixSpace of
    # ...'", which does not say which dimension is wrong.
    _check_matrix(matrix_a, "matrix_a")
    _check_matrix(matrix_b, "matrix_b")
    if len(matrix_a[0]) != len(matrix_b):
        raise ToolError(
            f"Cannot multiply a {len(matrix_a)}x{len(matrix_a[0])} matrix by a "
            f"{len(matrix_b)}x{len(matrix_b[0])} matrix: the number of columns in "
            "matrix_a must equal the number of rows in matrix_b"
        )
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
        {_declare_free_symbols(point)}
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
        {_declare_free_symbols(point)}
        _point = sage_eval({_encode_literal(point)}, locals=_locals)
        str(_expr.series(_var == _point, {order}))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"series": result, "point": point, "order": order}


@mcp.tool(description=(
        "Linear algebra on one matrix: determinant, inverse, eigenvalues, rank, "
        "reduced row echelon form, transpose. Prefer this over evaluate_sage."
    ))
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
    operation = operation.strip()
    _check_matrix(matrix, "matrix")
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


@mcp.tool(description=(
        "Solve an ordinary differential equation of any order, returning the "
        "general solution with arbitrary constants. Prefer this over evaluate_sage."
    ))
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
        _ode_function = function({_encode_literal(function)})
        _y = _ode_function(_x)
        _ode_text = {_encode_literal(equation)}

        def _build_ode(_binding):
            _ode_locals = dict(_locals)
            _ode_locals[{_encode_literal(function)}] = _binding
            _ode_locals['diff'] = diff
            parts = _ode_text.split('=')
            if len(parts) == 2:
                left = sage_eval(parts[0].strip(), locals=_ode_locals)
                right = sage_eval(parts[1].strip(), locals=_ode_locals)
                return left == right
            return sage_eval(_ode_text, locals=_ode_locals)

        # Bind the bare name to the undefined function so the documented
        # "diff(y(x), x)" form parses. Binding the applied expression instead
        # turns "y(x)" into "(y(x))(x)", which Sage rejects with "Substitution
        # using function-call syntax and unnamed arguments has been removed".
        # Fall back to the applied expression so a bare "diff(y, x)" still
        # works, since that form cannot be parsed against the function itself.
        try:
            _ode = _build_ode(_ode_function)
        except Exception:
            _ode = _build_ode(_y)
        str(desolve(_ode, _y, ivar=_x))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"solution": result}


@mcp.tool(description=(
        "Number theory: primality testing, integer factorisation, the next "
        "prime above n, gcd and lcm. Prefer this over evaluate_sage for any of these."
    ))
async def number_theory_operation(
    operation: Annotated[
        str,
        Field(description="Operation: 'is_prime', 'factor_integer', 'next_prime', 'gcd', 'lcm'"),
    ],
    a: Annotated[
        int | str,
        Field(
            description=(
                "Primary integer. Pass values above 2^53 as a decimal STRING: "
                "JSON numbers are IEEE doubles in JavaScript-based clients, so "
                "10^30 arrives as 1000000000000000019884624838656 and the answer "
                "is silently wrong."
            )
        ),
    ],
    b: Annotated[
        int | str | None,
        Field(description="Second integer, required for gcd and lcm. Same string rule."),
    ] = None,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    operation = operation.strip()
    a = _exact_int(a, "a")
    b = _exact_int(b, "b") if b is not None else None
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


@mcp.tool(description=(
        "Closed form of a symbolic sum or product over an index variable, "
        "including infinite series. Prefer this over evaluate_sage for summations."
    ))
async def symbolic_sum(
    expression: Annotated[str, Field(description="Expression to sum (e.g. '1/n^2')")],
    variable: Annotated[str, Field(description="Index variable (e.g. 'n')")] = "n",
    lower: Annotated[str, Field(description="Lower bound (e.g. '1')")] = "1",
    upper: Annotated[str, Field(description="Upper bound (e.g. 'oo' for infinity)")] = "oo",
    product: Annotated[
        bool, Field(description="If true, compute a product instead of a sum")
    ] = False,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await SESSION_MANAGER.get(ctx.session_id)
    op = "product" if product else "sum"
    code = (
        _sage_prelude([variable])
        + textwrap.dedent(
            f"""
        _var = var({_encode_literal(variable)})
        _expr = sage_eval({_encode_literal(expression)}, locals=_locals)
        {_declare_free_symbols(lower, upper)}
        _lo = sage_eval({_encode_literal(lower)}, locals=_locals)
        _hi = sage_eval({_encode_literal(upper)}, locals=_locals)
        str({op}(_expr, _var, _lo, _hi))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"result": result, "operation": op}


@mcp.tool(description=(
        "Combinatorics: binomial coefficients, permutations, combinations, "
        "integer partitions, factorial, Catalan, Fibonacci and Bell numbers. "
        "Prefer this over evaluate_sage for any of these."
    ))
async def combinatorics_operation(
    operation: Annotated[
        str,
        Field(
            # Every entry says what it returns. "partitions" alone left it
            # ambiguous whether the result was a count or a list of partitions,
            # and a client asking "how many partitions does 120 have" reached
            # for evaluate_sage rather than risk the wrong shape.
            description="One of: binomial (n choose k), permutations (n!), "
            "combinations (n choose k), partitions (COUNT of integer partitions "
            "of n), factorial (n!), catalan (nth Catalan number), fibonacci "
            "(nth Fibonacci number), bell (nth Bell number). All return a single "
            "integer."
        ),
    ],
    n: Annotated[int, Field(description="Primary integer argument")],
    k: Annotated[
        int | None, Field(description="Secondary argument (for binomial, combinations)")
    ] = None,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    operation = operation.strip()
    session = await SESSION_MANAGER.get(ctx.session_id)
    op_code = {
        "binomial": f"int(binomial({n}, {k or 0}))",
        "permutations": f"int(Permutations({n}).cardinality())"
        if k is None
        else f"int(factorial({n}) // factorial({n} - {k}))",
        "combinations": f"int(binomial({n}, {k or 0}))",
        "partitions": f"int(Partitions({n}).cardinality())",
        "factorial": f"int(factorial({n}))",
        "catalan": f"int(catalan_number({n}))",
        "fibonacci": f"int(fibonacci({n}))",
        "bell": f"int(bell_number({n}))",
    }
    if operation not in op_code:
        raise ToolError(f"Unknown operation '{operation}'. Use: {', '.join(op_code)}")
    code = _sage_prelude() + op_code[operation] + "\n"
    result = await _evaluate_structured(session, code)
    return {"operation": operation, "result": result}


@mcp.tool(description="Plot a 3D surface of a two-variable expression as base64 PNG")
async def plot3d_expression(
    expression: Annotated[
        str, Field(description="Expression of two variables (e.g. 'sin(x)*cos(y)')")
    ],
    x_variable: Annotated[str, Field(description="First variable")] = "x",
    y_variable: Annotated[str, Field(description="Second variable")] = "y",
    x_range_min: Annotated[float, Field(description="X lower bound")] = -5.0,
    x_range_max: Annotated[float, Field(description="X upper bound")] = 5.0,
    y_range_min: Annotated[float, Field(description="Y lower bound")] = -5.0,
    y_range_max: Annotated[float, Field(description="Y upper bound")] = 5.0,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await SESSION_MANAGER.get(ctx.session_id)
    code = (
        _sage_prelude([x_variable, y_variable])
        + textwrap.dedent(
            f"""
        import base64
        import io as _io
        from sage.plot.graphics import Graphics as _Graphics
        _xv = var({_encode_literal(x_variable)})
        _yv = var({_encode_literal(y_variable)})
        _expr = sage_eval({_encode_literal(expression)}, locals=_locals)
        # Sage's plot3d returns a Graphics3d, whose save()/save_image() require
        # a filesystem path and reject a BytesIO. There is no .matplotlib()
        # figure on it either, and a temp file is unreachable from the sandbox
        # (`open` is forbidden, tempfile/os are not importable). So sample the
        # surface and render it through matplotlib's 3D axes, which writes to
        # memory. A 2D Graphics is only used to obtain a Figure without
        # importing matplotlib directly.
        try:
            _f = fast_callable(_expr, vars=(_xv, _yv), domain=float)
        except Exception:
            _f = None

        def _z_at(_a, _b):
            # Singular or complex-valued points become NaN, which matplotlib
            # renders as a gap rather than failing the whole plot.
            try:
                if _f is not None:
                    return float(_f(_a, _b))
                return float(_expr.subs({{_xv: _a, _yv: _b}}))
            except Exception:
                return float('nan')

        _n = {_PLOT3D_GRID}
        _xlo, _xhi = float({x_range_min}), float({x_range_max})
        _ylo, _yhi = float({y_range_min}), float({y_range_max})
        _gx, _gy, _gz = [], [], []
        for _i in range(_n):
            _a = _xlo + (_xhi - _xlo) * _i / (_n - 1)
            for _j in range(_n):
                _b = _ylo + (_yhi - _ylo) * _j / (_n - 1)
                _gx.append(_a)
                _gy.append(_b)
                _gz.append(_z_at(_a, _b))
        _fig = _Graphics().matplotlib()
        _fig.clf()
        _ax = _fig.add_subplot(111, projection='3d')
        # plot_trisurf accepts flat sequences, so no numpy import is needed.
        _ax.plot_trisurf(_gx, _gy, _gz, cmap='viridis')
        _ax.set_xlabel({_encode_literal(x_variable)})
        _ax.set_ylabel({_encode_literal(y_variable)})
        _buf = _io.BytesIO()
        _fig.savefig(_buf, format='png')
        _buf.seek(0)
        base64.b64encode(_buf.read()).decode('ascii')
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"image_base64": result, "format": "png"}


@mcp.tool(
    description="Probability distribution operations: PDF, CDF, quantile, mean, variance, sampling"
)
async def distribution_operation(
    distribution: Annotated[
        str,
        Field(
            description="Distribution name: normal, exponential, poisson, "
            "chi_squared, student_t, uniform, beta, gamma"
        ),
    ],
    parameters: Annotated[
        list[float], Field(description="Distribution parameters (e.g. [0, 1] for standard normal)")
    ],
    operation: Annotated[
        str, Field(description="One of: pdf, cdf, quantile, mean, variance, sample")
    ],
    x: Annotated[float | None, Field(description="Point for pdf/cdf/quantile evaluation")] = None,
    n: Annotated[int | None, Field(description="Number of samples (for sample operation)")] = None,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    operation = operation.strip()
    session = await SESSION_MANAGER.get(ctx.session_id)
    params_str = ", ".join(str(p) for p in parameters)
    # "normal" takes [mu, sigma]. The previous mapping passed parameters[0] as
    # sigma only when exactly one parameter was given and otherwise hardcoded
    # 1, so [0, 3] silently computed with sigma=1, and mu was never applied at
    # all. Sage's gaussian is always centred on 0, so mu is applied by shifting
    # the evaluation point.
    normal_mu, normal_sigma = _normal_parameters(parameters)
    dist_map = {
        "normal": f"RealDistribution('gaussian', {normal_sigma})",
        "exponential": f"RealDistribution('exponential', {parameters[0] if parameters else 1})",
        "uniform": f"RealDistribution('uniform', [{params_str}])",
        "chi_squared": f"RealDistribution('chisquared', {parameters[0] if parameters else 1})",
        "student_t": f"RealDistribution('t', {parameters[0] if parameters else 1})",
        "beta": f"RealDistribution('beta', [{params_str}])",
        "gamma": f"RealDistribution('gamma', [{params_str}])",
    }
    # For distributions not directly in RealDistribution, use scipy-like Sage constructs
    if distribution == "poisson":
        # Poisson is discrete; handle separately
        lam = parameters[0] if parameters else 1
        op_code = {
            "pdf": (
                f"float(exp(-{lam}) * {lam}**{x} / factorial(int({x})))"
                if x is not None else "0"
            ),
            "cdf": (
                f"float(sum(exp(-{lam}) * {lam}**k / factorial(k)"
                f" for k in range(int({x}) + 1)))"
                if x is not None else "0"
            ),
            "mean": f"float({lam})",
            "variance": f"float({lam})",
            "sample": f"[int(numpy_rng.poisson({lam})) for _ in range({n or 1})]",
        }
        if operation not in op_code:
            raise ToolError(f"Unknown operation '{operation}' for Poisson distribution")
        code = _sage_prelude() + op_code.get(operation, "None") + "\n"
    elif distribution in dist_map:
        dist_expr = dist_map[distribution]
        # Only the normal distribution carries a location parameter here; for
        # every other distribution the shift is 0 and these read unchanged.
        shift = normal_mu if distribution == "normal" else 0.0
        shifted = None if x is None else f"({x}) - ({shift})"
        unshift = f"({shift}) + " if distribution == "normal" else ""
        op_code = {
            "pdf": f"float(_d.distribution_function({shifted}))" if x is not None else "None",
            "cdf": (
                f"float(_d.cum_distribution_function({shifted}))"
                if x is not None else "None"
            ),
            "quantile": (
                f"float({unshift}_d.cum_distribution_function_inv({x}))"
                if x is not None else "None"
            ),
            # mean/variance are computed analytically. They previously
            # returned float(_d.get_random_element()) and None respectively,
            # so "mean" reported a random draw from the distribution -- a
            # different wrong answer on every call -- and "variance" was
            # always null.
            "mean": f"float({_distribution_mean(distribution, parameters)})",
            "variance": f"float({_distribution_variance(distribution, parameters)})",
            "sample": f"[float(_d.get_random_element()) for _ in range({n or 1})]",
        }
        if operation not in op_code:
            raise ToolError(
                f"Unknown operation '{operation}'. "
                "Use: pdf, cdf, quantile, mean, variance, sample"
            )
        code = _sage_prelude() + f"_d = {dist_expr}\n" + op_code[operation] + "\n"
    else:
        raise ToolError(
            f"Unknown distribution '{distribution}'. "
            "Use: normal, exponential, poisson, chi_squared, student_t, uniform, beta, gamma"
        )
    result = await _evaluate_structured(session, code)
    return {"distribution": distribution, "operation": operation, "result": result}


@mcp.tool(description="Find a numeric root of an expression in a given interval")
async def find_root(
    expression: Annotated[str, Field(description="Expression to find root of (e.g. 'x - cos(x)')")],
    variable: Annotated[str, Field(description="Variable")] = "x",
    lower_bound: Annotated[float, Field(description="Left bound of search interval")] = -10.0,
    upper_bound: Annotated[float, Field(description="Right bound of search interval")] = 10.0,
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
        float(find_root(_expr, {lower_bound}, {upper_bound}))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"root": result}


@mcp.tool(description="Plot multiple expressions overlaid on a single 2D graph")
async def plot_multi_expression(
    expressions: Annotated[
        list[str], Field(description="List of expressions to plot (e.g. ['sin(x)', 'cos(x)'])")
    ],
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
        _exprs = [sage_eval(e, locals=_locals) for e in {_encode_literal(expressions)}]
        _plt = sum(plot(e, (_var, {range_min}, {range_max})) for e in _exprs)
        _buf = _io.BytesIO()
        # Graphics.save() needs a filesystem path and rejects a BytesIO with
        # "expected str, bytes or os.PathLike object". Going through the
        # matplotlib figure renders to memory, which the sandbox allows.
        _plt.matplotlib().savefig(_buf, format='png')
        _buf.seek(0)
        base64.b64encode(_buf.read()).decode('ascii')
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"image_base64": result, "format": "png"}


@mcp.tool(
    description="Vector calculus operations: gradient, divergence, curl, laplacian"
)
async def vector_calculus_operation(
    operation: Annotated[
        str, Field(description="One of: gradient, divergence, curl, laplacian")
    ],
    expression: Annotated[
        str | list[str],
        Field(
            description="Scalar field (string) for gradient/laplacian, "
            "or vector field components (list) for divergence/curl"
        ),
    ],
    variables: Annotated[
        list[str] | None,
        Field(description="Variable names (e.g. ['x', 'y', 'z'])"),
    ] = None,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    operation = operation.strip()
    if variables is None:
        variables = ["x", "y", "z"]
    session = await SESSION_MANAGER.get(ctx.session_id)
    vars_str = ", ".join(f"var('{v}')" for v in variables)

    if operation == "gradient":
        if not isinstance(expression, str):
            raise ToolError("Gradient requires a scalar expression (string)")
        code = (
            _sage_prelude(variables)
            + textwrap.dedent(
                f"""
            _vars = [{vars_str}]
            _f = sage_eval({_encode_literal(expression)}, locals=_locals)
            [str(diff(_f, v)) for v in _vars]
            """
            )
        )
    elif operation == "divergence":
        if not isinstance(expression, list):
            raise ToolError("Divergence requires a vector field (list of component strings)")
        if len(expression) != len(variables):
            raise ToolError(
                f"Vector field has {len(expression)} components "
                f"but {len(variables)} variables"
            )
        code = (
            _sage_prelude(variables)
            + textwrap.dedent(
                f"""
            _vars = [{vars_str}]
            _components = [sage_eval(c, locals=_locals) for c in {_encode_literal(expression)}]
            str(sum(diff(_components[i], _vars[i]) for i in range(len(_vars))))
            """
            )
        )
    elif operation == "curl":
        if not isinstance(expression, list) or len(expression) != 3:
            raise ToolError("Curl requires exactly 3 vector field components")
        if len(variables) != 3:
            raise ToolError("Curl requires exactly 3 variables")
        code = (
            _sage_prelude(variables)
            + textwrap.dedent(
                f"""
            _vars = [{vars_str}]
            _F = [sage_eval(c, locals=_locals) for c in {_encode_literal(expression)}]
            _curl = [
                str(diff(_F[2], _vars[1]) - diff(_F[1], _vars[2])),
                str(diff(_F[0], _vars[2]) - diff(_F[2], _vars[0])),
                str(diff(_F[1], _vars[0]) - diff(_F[0], _vars[1])),
            ]
            _curl
            """
            )
        )
    elif operation == "laplacian":
        if not isinstance(expression, str):
            raise ToolError("Laplacian requires a scalar expression (string)")
        code = (
            _sage_prelude(variables)
            + textwrap.dedent(
                f"""
            _vars = [{vars_str}]
            _f = sage_eval({_encode_literal(expression)}, locals=_locals)
            str(sum(diff(_f, v, 2) for v in _vars))
            """
            )
        )
    else:
        raise ToolError(
            f"Unknown operation '{operation}'. "
            "Use: gradient, divergence, curl, laplacian"
        )

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
        # Graphics.save() needs a filesystem path and rejects a BytesIO with
        # "expected str, bytes or os.PathLike object". Going through the
        # matplotlib figure renders to memory, which the sandbox allows.
        _plt.matplotlib().savefig(_buf, format='png')
        _buf.seek(0)
        base64.b64encode(_buf.read()).decode('ascii')
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"image_base64": result, "format": "png"}


# ---------------------------------------------------------------------------
# Phase 4 — Niche domain tools
# ---------------------------------------------------------------------------


@mcp.tool(
    description="Graph theory: create named graphs and compute properties "
    "(chromatic_number, is_connected, diameter, etc.)"
)
async def graph_operation(
    graph: Annotated[
        str,
        Field(
            description="Graph constructor: a named graph like 'PetersenGraph' "
            "or an adjacency dict like '{0:[1,2], 1:[0,2], 2:[0,1]}'"
        ),
    ],
    operation: Annotated[
        str,
        Field(
            description="One of: chromatic_number, is_connected, is_planar, "
            "diameter, order, size, degree_sequence, adjacency_matrix, "
            "shortest_path (requires source and target)"
        ),
    ],
    source: Annotated[int | None, Field(description="Source vertex")] = None,
    target: Annotated[int | None, Field(description="Target vertex")] = None,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    operation = operation.strip()
    session = await SESSION_MANAGER.get(ctx.session_id)
    # A named graph is an identifier, optionally already called with arguments.
    # Matching on a "Graph" suffix missed every parameterised constructor:
    # "CompleteGraph(4)" ends in ")", so it fell through to Graph(CompleteGraph(4))
    # and failed with "name 'CompleteGraph' is not defined". Most named graphs
    # take parameters, so that was the majority of the catalogue.
    named = _NAMED_GRAPH_RE.match(graph.strip())
    if named:
        call = named.group("call") or "()"
        graph_code = f"_G = graphs.{named.group('name')}{call}"
    else:
        # Anything else is a literal, such as an adjacency dict.
        graph_code = f"_G = Graph({graph})"
    ops = {
        "chromatic_number": "int(_G.chromatic_number())",
        "is_connected": "bool(_G.is_connected())",
        "is_planar": "bool(_G.is_planar())",
        "diameter": "int(_G.diameter())",
        "order": "int(_G.order())",
        "size": "int(_G.size())",
        "degree_sequence": "sorted(_G.degree_sequence(), reverse=True)",
        "adjacency_matrix": (
            "[[int(x) for x in row] "
            "for row in _G.adjacency_matrix().rows()]"
        ),
        "shortest_path": (
            f"list(_G.shortest_path({source}, {target}))"
            if source is not None and target is not None
            else "None"
        ),
    }
    if operation not in ops:
        raise ToolError(
            f"Unknown operation '{operation}'. "
            f"Use: {', '.join(ops)}"
        )
    code = _sage_prelude() + graph_code + "\n" + ops[operation] + "\n"
    result = await _evaluate_structured(session, code)
    return {"operation": operation, "result": result}


@mcp.tool(
    description="Group theory: construct groups and query properties "
    "(order, is_abelian, center, etc.)"
)
async def group_operation(
    group: Annotated[
        str,
        Field(
            description="Sage group constructor, e.g. "
            "'SymmetricGroup(5)', 'DihedralGroup(4)', "
            "'CyclicPermutationGroup(6)', 'AlternatingGroup(5)'"
        ),
    ],
    operation: Annotated[
        str,
        Field(
            description="One of: order, is_abelian, is_cyclic, "
            "center_order, conjugacy_classes_count, exponent"
        ),
    ],
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    operation = operation.strip()
    session = await SESSION_MANAGER.get(ctx.session_id)
    ops = {
        "order": "int(_G.order())",
        "is_abelian": "bool(_G.is_abelian())",
        "is_cyclic": "bool(_G.is_cyclic())",
        "center_order": "int(_G.center().order())",
        "conjugacy_classes_count": (
            "int(len(_G.conjugacy_classes_representatives()))"
        ),
        "exponent": "int(_G.exponent())",
    }
    if operation not in ops:
        raise ToolError(
            f"Unknown operation '{operation}'. "
            f"Use: {', '.join(ops)}"
        )
    code = _sage_prelude() + f"_G = {group}\n" + ops[operation] + "\n"
    result = await _evaluate_structured(session, code)
    return {"group": group, "operation": operation, "result": result}


@mcp.tool(
    description=(
        "Elliptic curves over Q: rank, torsion order, discriminant, j-invariant, "
        "conductor and generators, from Weierstrass coefficients. Prefer this "
        "over evaluate_sage for curve invariants."
    )
)
async def elliptic_curve_operation(
    coefficients: Annotated[
        list[int],
        Field(
            description="Curve coefficients [a1,a2,a3,a4,a6] or "
            "short Weierstrass [a,b] for y^2 = x^3 + a*x + b"
        ),
    ],
    operation: Annotated[
        str,
        Field(
            description="One of: rank, torsion_order, discriminant, "
            "j_invariant, conductor, gens"
        ),
    ],
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    operation = operation.strip()
    session = await SESSION_MANAGER.get(ctx.session_id)
    ops = {
        "rank": "int(_E.rank())",
        "torsion_order": "int(_E.torsion_order())",
        "discriminant": "str(_E.discriminant())",
        "j_invariant": "str(_E.j_invariant())",
        "conductor": "int(_E.conductor())",
        "gens": "[str(p) for p in _E.gens()]",
    }
    if operation not in ops:
        raise ToolError(
            f"Unknown operation '{operation}'. "
            f"Use: {', '.join(ops)}"
        )
    code = (
        _sage_prelude()
        + f"_E = EllipticCurve({_encode_literal(coefficients)})\n"
        + ops[operation]
        + "\n"
    )
    result = await _evaluate_structured(session, code)
    return {"operation": operation, "result": result}


@mcp.tool(
    description=(
        "Error-correcting codes: length, dimension, minimum distance, rate and "
        "generator matrix for Hamming and generalized Reed-Solomon codes. Prefer "
        "this over evaluate_sage for code parameters."
    )
)
async def coding_theory_operation(
    code_type: Annotated[
        str,
        Field(
            description="Code constructor, e.g. "
            # ReedSolomonCode(GF(7),3,5) was documented here but has never been
            # a valid constructor in current Sage; it raises AttributeError.
            "'HammingCode(GF(2),3)', "
            "'GeneralizedReedSolomonCode(GF(7).list()[:6],3)'"
        ),
    ],
    operation: Annotated[
        str,
        Field(
            description="One of: length, dimension, "
            "minimum_distance, generator_matrix, rate"
        ),
    ],
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    operation = operation.strip()
    session = await SESSION_MANAGER.get(ctx.session_id)
    ops = {
        "length": "int(_C.length())",
        "dimension": "int(_C.dimension())",
        "minimum_distance": "int(_C.minimum_distance())",
        "generator_matrix": (
            "[[int(x) for x in row] "
            "for row in _C.generator_matrix().rows()]"
        ),
        "rate": "float(_C.dimension() / _C.length())",
    }
    if operation not in ops:
        raise ToolError(
            f"Unknown operation '{operation}'. "
            f"Use: {', '.join(ops)}"
        )
    code = (
        _sage_prelude()
        + f"_C = codes.{code_type}\n"
        + ops[operation]
        + "\n"
    )
    result = await _evaluate_structured(session, code)
    return {"operation": operation, "result": result}


@mcp.tool(
    description=(
        "Boolean polynomials over GF(2): evaluate, list variables, degree, and "
        "zero/one tests. Prefer this over evaluate_sage for boolean algebra."
    )
)
async def boolean_algebra_operation(
    expression: Annotated[
        str,
        Field(description="Boolean expression (e.g. 'x*y + x*z + y*z')"),
    ],
    operation: Annotated[
        str,
        Field(
            description="One of: evaluate, variables, degree, "
            "is_zero, is_one, reduce"
        ),
    ],
    num_variables: Annotated[
        int,
        Field(description="Number of boolean variables", ge=1),
    ] = 3,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    operation = operation.strip()
    session = await SESSION_MANAGER.get(ctx.session_id)
    var_names = ", ".join(f"'x{i}'" for i in range(num_variables))
    # The ring generators are x0, x1, ..., but the documented example uses
    # x, y, z. Expose both spellings so either parses, rather than failing
    # with "name 'x' is not defined" on the tool's own documented input.
    ring_setup = (
        f"_R = BooleanPolynomialRing({num_variables}, [{var_names}])\n"
        f"_R.inject_variables(verbose=False)\n"
        "_bool_locals = {str(_g): _g for _g in _R.gens()}\n"
        "for _alias, _gen in zip(['x', 'y', 'z', 'w', 'v', 'u'], _R.gens()):\n"
        "    _bool_locals.setdefault(_alias, _gen)\n"
        f"_bool_expr = _R(sage_eval({_encode_literal(expression)}, "
        "locals=_bool_locals))\n"
    )
    ops = {
        "evaluate": "str(_bool_expr)",
        "variables": "[str(v) for v in _bool_expr.variables()]",
        "degree": "int(_bool_expr.deg())",
        "is_zero": "bool(_bool_expr.is_zero())",
        "is_one": "bool(_bool_expr.is_one())",
        "reduce": "str(_bool_expr)",
    }
    if operation not in ops:
        raise ToolError(
            f"Unknown operation '{operation}'. "
            f"Use: {', '.join(ops)}"
        )
    code = _sage_prelude() + ring_setup + ops[operation] + "\n"
    result = await _evaluate_structured(session, code)
    return {"operation": operation, "result": result}


@mcp.tool(
    description="Polynomial ring operations: construct rings "
    "and compute Groebner bases, ideals, quotients"
)
async def polynomial_ring_operation(
    ring_vars: Annotated[
        list[str],
        Field(description="Variable names, e.g. ['a', 'b', 'c']"),
    ],
    polynomials: Annotated[
        list[str],
        Field(description="Polynomials as strings, e.g. ['a^2+b', 'b^2-1']"),
    ],
    operation: Annotated[
        str,
        Field(
            description="One of: groebner_basis, ideal_dimension, "
            "ideal_variety, reduce, is_groebner"
        ),
    ],
    base_ring: Annotated[str, Field(description="Base ring")] = "QQ",
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    operation = operation.strip()
    session = await SESSION_MANAGER.get(ctx.session_id)
    var_list = ", ".join(ring_vars)
    ops = {
        "groebner_basis": "[str(g) for g in _I.groebner_basis()]",
        "ideal_dimension": "int(_I.dimension())",
        "ideal_variety": "[{str(k): str(v) for k, v in pt.items()} "
        "for pt in _I.variety()]",
        "reduce": (
            f"str(_I.reduce(_R({_encode_literal(polynomials[0])})))"
            if polynomials
            else "''"
        ),
        "is_groebner": "bool(_I.basis_is_groebner())",
    }
    if operation not in ops:
        raise ToolError(
            f"Unknown operation '{operation}'. "
            f"Use: {', '.join(ops)}"
        )
    polys_code = ", ".join(
        f"_R({_encode_literal(p)})" for p in polynomials
    )
    code = (
        _sage_prelude(ring_vars)
        + f"_R = PolynomialRing({base_ring}, '{var_list}')\n"
        + "_R.inject_variables(verbose=False)\n"
        + f"_I = _R.ideal([{polys_code}])\n"
        + ops[operation]
        + "\n"
    )
    result = await _evaluate_structured(session, code)
    return {"operation": operation, "result": result}


@mcp.tool(
    description=(
        "Computational geometry on point sets: euclidean distance, polygon area, "
        "polytope volume, convex hull vertices and convexity tests. Prefer this "
        "over evaluate_sage for these."
    )
)
async def geometry_operation(
    operation: Annotated[
        str,
        Field(
            description="One of: distance, polygon_area, "
            "polytope_volume, convex_hull_vertices, is_convex"
        ),
    ],
    points: Annotated[
        list[list[float]],
        Field(description="List of points as coordinate lists"),
    ],
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    operation = operation.strip()
    if not points:
        raise ToolError("'points' must contain at least one point")
    # distance previously generated the literal "None" for a single point, so
    # the tool returned {'result': None} as though that were an answer.
    if operation == "distance" and len(points) < 2:
        raise ToolError(
            f"Operation 'distance' requires two points, got {len(points)}"
        )
    session = await SESSION_MANAGER.get(ctx.session_id)
    pts = _encode_literal(points)
    ops = {
        "distance": (
            # "**", not "^": this expression is executed as Python, where "^"
            # is XOR. (0-3)^2 evaluates to -1, and the sum then goes negative,
            # so sqrt() returns a complex number and float() fails.
            f"float(sqrt(sum((a-b)**2 for a, b in "
            f"zip({_encode_literal(points[0])}, "
            f"{_encode_literal(points[1])}))))"
            if len(points) >= 2
            else "None"
        ),
        "polygon_area": (
            f"float(Polyhedron(vertices={pts}).volume())"
        ),
        "polytope_volume": (
            f"float(Polyhedron(vertices={pts}).volume())"
        ),
        "convex_hull_vertices": (
            f"[list(v) for v in "
            f"Polyhedron(vertices={pts}).vertices_list()]"
        ),
        "is_convex": (
            f"bool(Polyhedron(vertices={pts}).is_compact())"
        ),
    }
    if operation not in ops:
        raise ToolError(
            f"Unknown operation '{operation}'. "
            f"Use: {', '.join(ops)}"
        )
    code = _sage_prelude() + ops[operation] + "\n"
    result = await _evaluate_structured(session, code)
    return {"operation": operation, "result": result}


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
    ctx: Context | None = None,
) -> EvaluateResult:
    """Like evaluate_sage but emits each stdout line as a progress event."""
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    session = await SESSION_MANAGER.get(ctx.session_id)
    worker_result = await session.evaluate(
        code,
        want_latex=False,
        capture_stdout=True,
        timeout_seconds=timeout_seconds,
    )
    # Emit each stdout line as a progress event so clients can show
    # partial output while the result is being assembled.
    if worker_result.stdout and ctx is not None:
        for i, line in enumerate(worker_result.stdout.splitlines()):
            await ctx.report_progress(
                float(i + 1), None, line,
            )
    monitoring.record_success(worker_result.elapsed_ms)
    return EvaluateResult(
        result_type=worker_result.result_type,
        result=worker_result.result,
        latex=None,
        stdout=_truncate_stdout(worker_result.stdout),
        elapsed_ms=worker_result.elapsed_ms,
    )


def _register_health_route() -> None:
    """Attach /health to the underlying Starlette app if HTTP transport."""
    try:
        from starlette.routing import Route

        app = (
            getattr(mcp, "http_app", None)
            or getattr(mcp, "_app", None)
            or getattr(mcp, "app", None)
        )
        if app and hasattr(app, "routes"):
            app.routes.insert(0, Route("/health", health_check))
            LOGGER.debug("Registered /health endpoint")
    except Exception:  # pragma: no cover - starlette may not be loaded
        pass


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
        _register_health_route()

    mcp.run(transport=args.transport, **transport_kwargs)


if __name__ == "__main__":  # pragma: no cover
    main()
