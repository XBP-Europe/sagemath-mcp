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
