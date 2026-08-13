"""Differentiation, integration, limits, series, ODEs and vector calculus.

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
    _declare_free_symbols,
    _encode_literal,
    _evaluate_structured,
    _sage_prelude,
    _validated_identifier,
)
from ..session import (
    DEFAULT_SESSION_NAME,
)
from ..text import SESSION_ARG_DESC as _SESSION_ARG_DESC


@mcp.tool(description="Differentiate an expression with respect to a variable")
async def differentiate_expression(
    expression: Annotated[str, Field(description="Expression to differentiate")],
    variable: Annotated[str, Field(description="Variable for differentiation", default="x")] = "x",
    order: Annotated[
        int,
        Field(description="Order of differentiation (1 = first, 2 = second, etc.)", ge=1),
    ] = 1,
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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    if (lower_bound is None) != (upper_bound is None):
        raise ToolError("Both lower_bound and upper_bound must be provided for a definite integral")
    session = await runtime.resolve_session(ctx.session_id, session)
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


@mcp.tool(description="Compute the limit of an expression")
async def limit_expression(
    expression: Annotated[str, Field(description="Expression to take the limit of")],
    variable: Annotated[str, Field(description="Variable approaching the point")] = "x",
    point: Annotated[str, Field(description="Point to approach (e.g., '0', 'oo', '-oo')")] = "0",
    direction: Annotated[
        str | None,
        Field(description="Direction: 'plus' (right), 'minus' (left), or omit for both"),
    ] = None,
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await runtime.resolve_session(ctx.session_id, session)
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
        {_declare_free_symbols(point)}
        _point = sage_eval({_encode_literal(point)}, locals=_locals)
        str(_expr.series(_var == _point, {order}))
        """
        )
    )
    result = await _evaluate_structured(session, code)
    return {"series": result, "point": point, "order": order}


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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await runtime.resolve_session(ctx.session_id, session)
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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    operation = operation.strip()
    if variables is None:
        variables = ["x", "y", "z"]
    # Also quoted into var('...') below, so gate them here rather than relying on
    # whichever branch happens to call _sage_prelude.
    variables = [_validated_identifier(v, "variables") for v in variables]
    session = await runtime.resolve_session(ctx.session_id, session)
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
