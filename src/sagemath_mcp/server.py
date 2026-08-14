"""FastMCP server exposing SageMath as a stateful tool."""

from __future__ import annotations

import argparse
import logging

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
    SageProcessError,  # noqa: F401 - re-exported
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

LOGGER = logging.getLogger(__name__)

_SESSION_ARG_DESC = (
    "Named workspace to use. Workspaces have independent variables; "
    f"omit for '{DEFAULT_SESSION_NAME}'."
)


# ---------------------------------------------------------------------------
# HTTP health check endpoint (non-MCP, for Kubernetes probes)
# ---------------------------------------------------------------------------


async def health_check(request: object) -> object:
    """Return 200 with server status for liveness/readiness probes."""
    from starlette.responses import JSONResponse

    sessions = runtime.SESSION_MANAGER.snapshot()
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "active_sessions": len(sessions),
        }
    )




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
    _HEALTH_ROUTE_REGISTERED = True
    LOGGER.debug("Registered /health endpoint")


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
