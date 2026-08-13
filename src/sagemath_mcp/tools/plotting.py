"""2D and 3D plotting, and computational geometry.

One of the tool modules imported by :mod:`sagemath_mcp.server` for its
registration side effect. Decorating against the shared ``mcp`` object keeps
every tool name exactly as it was; FastMCP's mount/import_server composition
would have prefixed them.
"""

from __future__ import annotations

import textwrap
from typing import Annotated

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from .. import runtime
from ..app import mcp
from ..codegen import (
    _encode_literal,
    _evaluate_structured,
    _sage_prelude,
)
from ..session import (
    DEFAULT_SESSION_NAME,
)
from ..text import SESSION_ARG_DESC as _SESSION_ARG_DESC

# Samples per axis for the 3D surface. 48x48 keeps the rendered surface smooth
# while staying well inside the evaluation timeout.
_PLOT3D_GRID = 48

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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await runtime.resolve_session(ctx.session_id, session)
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


@mcp.tool(description="Plot multiple expressions overlaid on a single 2D graph")
async def plot_multi_expression(
    expressions: Annotated[
        list[str], Field(description="List of expressions to plot (e.g. ['sin(x)', 'cos(x)'])")
    ],
    variable: Annotated[str, Field(description="Plot variable")] = "x",
    range_min: Annotated[float, Field(description="Lower bound of plot range")] = -10.0,
    range_max: Annotated[float, Field(description="Upper bound of plot range")] = 10.0,
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


@mcp.tool(description="Plot an expression and return a base64-encoded PNG image")
async def plot_expression(
    expression: Annotated[str, Field(description="Expression to plot")],
    variable: Annotated[str, Field(description="Plot variable")] = "x",
    range_min: Annotated[float, Field(description="Lower bound of plot range")] = -10.0,
    range_max: Annotated[float, Field(description="Upper bound of plot range")] = 10.0,
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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
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
    session = await runtime.resolve_session(ctx.session_id, session)
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
