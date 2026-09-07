"""FastMCP server exposing SageMath as a stateful tool."""

from __future__ import annotations

import argparse
import logging
import time

from fastmcp.exceptions import ToolError  # noqa: F401 - re-exported for callers and tests

from . import (
    __version__,
    runtime,
    tools,  # noqa: F401 - imported for its registration side effect
)
from .app import mcp
from .config import DEFAULT_SETTINGS  # noqa: F401 - part of this module's long-standing surface
from .session import (
    DEFAULT_SESSION_NAME,
    SageProcessError,
)

# The tool functions are re-exported here because `sagemath_mcp.server` is the
# documented import surface: the console script, `python -m sagemath_mcp.server`,
# the CLI integration configs and the test suite all reach for it. Importing the
# tools package is what registers them; these names keep the old spelling working.
from .tools.algebra import (  # noqa: F401
    boolean_algebra_operation,
    matrix_multiply,
    matrix_operation,
    polynomial_ring_operation,
    solve_equation,
)
from .tools.calculus import (  # noqa: F401
    differentiate_expression,
    integrate_expression,
    limit_expression,
    series_expansion,
    solve_ode,
    symbolic_sum,
    vector_calculus_operation,
)
from .tools.core import (  # noqa: F401
    calculate_expression,
    evaluate_sage,
    evaluate_sage_streaming,
    expand_expression,
    factor_expression,
    find_root,
    simplify_expression,
)
from .tools.diagnostics import (  # noqa: F401
    check_sage_health,
    lookup_sage_doc,
)
from .tools.discrete import (  # noqa: F401
    coding_theory_operation,
    combinatorics_operation,
    elliptic_curve_operation,
    graph_operation,
    group_operation,
    number_theory_operation,
)
from .tools.plotting import (  # noqa: F401
    geometry_operation,
    plot3d_expression,
    plot_expression,
    plot_multi_expression,
)
from .tools.session import (  # noqa: F401
    cancel_sage_session,
    documentation_resource,
    interrupt_sage_session,
    list_sage_sessions,
    monitoring_resource,
    reset_sage_session,
    session_resource,
    start_sage_session,
    stop_sage_session,
)
from .tools.stats import (  # noqa: F401
    distribution_operation,
    statistics_summary,
)
from .tools.verify import (  # noqa: F401
    verify_claim,
)

LOGGER = logging.getLogger(__name__)

_SESSION_ARG_DESC = (
    "Named workspace to use. Workspaces have independent variables; "
    f"omit for '{DEFAULT_SESSION_NAME}'."
)


# ---------------------------------------------------------------------------
# HTTP health check endpoint (non-MCP, for Kubernetes probes)
# ---------------------------------------------------------------------------


async def health_check(request: object) -> object:
    """Liveness: is the server process up and answering HTTP?

    Deliberately shallow. This must not depend on a Sage worker: a liveness
    probe that fails because a computation is wedged tells Kubernetes to kill
    and restart the whole pod, which is the wrong response to a busy backend.
    Readiness -- "can it do mathematics right now?" -- is /ready below.
    """
    from starlette.responses import JSONResponse

    sessions = runtime.SESSION_MANAGER.snapshot()
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "active_sessions": len(sessions),
        }
    )


# A session key reserved for the readiness probe, so repeated probes reuse one
# warm worker instead of creating a session per call (which would fight the
# idle culler and the session ceiling). It is a normal session otherwise.
_READINESS_SESSION_KEY = "__readiness_probe__"
_READINESS_TIMEOUT_SECONDS = 10.0


async def readiness_check(request: object) -> object:
    """Readiness: can the server actually evaluate mathematics right now?

    A TCP connect or the shallow /health both pass while the Sage backend is
    unusable -- a worker that cannot spawn, a Sage install that imports but
    cannot compute. This runs the real path (worker spawn, protocol round trip,
    `1 + 1`) and answers 503 when it cannot, so a Service stops routing to a pod
    whose backend is broken instead of sending it traffic it will fail.
    """
    from starlette.responses import JSONResponse

    from .session import SageEvaluationError

    backend = "pure-python" if runtime.SETTINGS.force_python_worker else "sagemath"
    started = time.perf_counter()
    try:
        sage = await runtime.SESSION_MANAGER.get(_READINESS_SESSION_KEY)
        result = await sage.evaluate(
            "1 + 1",
            want_latex=False,
            capture_stdout=False,
            timeout_seconds=min(_READINESS_TIMEOUT_SECONDS, runtime.SETTINGS.eval_timeout),
        )
        ready = result.result == "2"
    except (SageProcessError, SageEvaluationError, TimeoutError) as exc:
        return JSONResponse(
            {"status": "unready", "backend": backend, "reason": str(exc)},
            status_code=503,
        )
    payload = {
        "status": "ready" if ready else "unready",
        "backend": backend,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    return JSONResponse(payload, status_code=200 if ready else 503)


_HEALTH_ROUTE_REGISTERED = False


def _register_health_route() -> None:
    """Attach /health to the HTTP app.

    This used to hunt for a Starlette app among mcp.http_app / _app / app and
    insert a Route into its list. Under FastMCP 3.x http_app is a bound method
    that BUILDS the app, so it has no `routes`, the guard was false and this
    registered nothing at all -- silently, because the whole body sat in a
    try/except pass. The documented health endpoint answered 404 in every HTTP
    deployment, and the Kubernetes probes pointed at it.

    custom_route registers with FastMCP itself, so every app it builds has the
    route. Tested against the built app rather than trusted.
    """
    global _HEALTH_ROUTE_REGISTERED
    if _HEALTH_ROUTE_REGISTERED:
        # main() can run more than once in a process, and each call would add
        # another identical route to every app built afterwards.
        return
    mcp.custom_route("/health", methods=["GET"])(health_check)
    mcp.custom_route("/ready", methods=["GET"])(readiness_check)
    _HEALTH_ROUTE_REGISTERED = True
    LOGGER.debug("Registered /health endpoint")


# Addresses that mean "only this machine". Binding anything else on an HTTP
# transport exposes the evaluator beyond the host.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "::ffff:127.0.0.1"})


def _exposure_warning(host: str, has_auth: bool) -> str | None:
    """The warning to log for an HTTP bind, or None when the bind is safe.

    Binding a non-loopback host publishes an unauthenticated code evaluator to
    whatever can route to it. Inside a container that is the correct bind -- the
    host maps a loopback-published port to it -- but on a bare host it is a hole.
    Warn unless the bind is loopback, or a bearer token is required.
    """
    if has_auth or host in _LOOPBACK_HOSTS:
        return None
    return (
        f"HTTP transport is binding {host!r} with NO authentication -- anyone who "
        "can reach this address can execute code. This is only safe behind a "
        "loopback-published container port or an authenticating proxy. Require a "
        "token with SAGEMATH_MCP_HTTP_AUTH_TOKEN, or bind locally with "
        "--host 127.0.0.1."
    )


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
        has_auth = mcp.auth is not None
        if has_auth:
            LOGGER.info("HTTP bearer-token authentication is enabled.")
        warning = _exposure_warning(args.host, has_auth)
        if warning:
            LOGGER.warning(warning)

    mcp.run(transport=args.transport, **transport_kwargs)


if __name__ == "__main__":  # pragma: no cover
    main()
