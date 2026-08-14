"""Equation solving, matrices, polynomial rings and boolean algebra.

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
    _check_matrix,
    _encode_literal,
    _evaluate_structured,
    _exact_matrix_entries,
    _sage_prelude,
    _validated_expression,
    _validated_identifier,
)
from ..session import (
    DEFAULT_SESSION_NAME,
)
from ..text import SESSION_ARG_DESC as _SESSION_ARG_DESC


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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    session = await runtime.resolve_session(ctx.session_id, session)
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


# How a matrix entry or scalar comes back. Floats stay floats -- changing that
# would alter every existing result -- except where a float cannot hold the
# value: past MAX_SAFE_INTEGER an integral entry is returned exactly, and the
# session then renders it as a decimal string on the way out.
_EXACT_SCALAR = (
    "(lambda _v: int(_v) if (_v in ZZ and abs(_v) > 9007199254740991) "
    "else (float(_v) if _v in RR else str(_v)))"
)


@mcp.tool(description="Multiply two matrices and return the result as nested lists")
async def matrix_multiply(
    matrix_a: Annotated[
        list[list[float | int | str]],
        Field(description="Left matrix (rows of numbers). Integers stay exact; "
              'pass values from 2^53 up as decimal strings, e.g. "9007199254740993".'),
    ],
    matrix_b: Annotated[
        list[list[float | int | str]],
        Field(description="Right matrix (rows of numbers). Integers stay exact."),
    ],
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    # Checked here so a shape mismatch reports the shapes. Left to Sage it
    # surfaced as "unsupported operand parent(s) for *: 'Full MatrixSpace of
    # ...'", which does not say which dimension is wrong.
    _check_matrix(matrix_a, "matrix_a")
    _check_matrix(matrix_b, "matrix_b")
    matrix_a = _exact_matrix_entries(matrix_a, "matrix_a")
    matrix_b = _exact_matrix_entries(matrix_b, "matrix_b")
    if len(matrix_a[0]) != len(matrix_b):
        raise ToolError(
            f"Cannot multiply a {len(matrix_a)}x{len(matrix_a[0])} matrix by a "
            f"{len(matrix_b)}x{len(matrix_b[0])} matrix: the number of columns in "
            "matrix_a must equal the number of rows in matrix_b"
        )
    session = await runtime.resolve_session(ctx.session_id, session)
    code = textwrap.dedent(
        f"""
        from sage.all import *
        A = matrix(SR, {matrix_a})
        B = matrix(SR, {matrix_b})
        C = A * B
        [[{_EXACT_SCALAR}(entry) for entry in row] for row in C.rows()]
        """
    )
    product = await _evaluate_structured(session, code)
    return {"product": product}


@mcp.tool(description=(
        "Linear algebra on one matrix: determinant, inverse, eigenvalues, rank, "
        "reduced row echelon form, transpose. Prefer this over evaluate_sage."
    ))
async def matrix_operation(
    matrix: Annotated[
        list[list[float | int | str]],
        Field(description="Matrix as nested list of numbers. Integers stay exact; "
              'pass values from 2^53 up as decimal strings.'),
    ],
    operation: Annotated[
        str,
        Field(description="One of: determinant, inverse, eigenvalues, rank, rref, transpose"),
    ],
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    operation = operation.strip()
    _check_matrix(matrix, "matrix")
    matrix = _exact_matrix_entries(matrix, "matrix")
    allowed_ops = {"determinant", "inverse", "eigenvalues", "rank", "rref", "transpose"}
    if operation not in allowed_ops:
        raise ToolError(
            f"Unknown operation '{operation}'. "
            f"Must be one of: {', '.join(sorted(allowed_ops))}"
        )
    session = await runtime.resolve_session(ctx.session_id, session)
    # int before float: an integer determinant or entry cast to a double loses
    # exactness for anything past 2^53, and these tools exist to be exact.
    _row_repr = (
        f"[[{_EXACT_SCALAR}(e) for e in row] for row in {{obj}}.rows()]"
    )
    op_code = {
        "determinant": f"{_EXACT_SCALAR}(M.determinant())",
        "inverse": _row_repr.format(obj="M.inverse()"),
        "eigenvalues": f"[{_EXACT_SCALAR}(ev) for ev in M.eigenvalues()]",
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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    operation = operation.strip()
    session = await runtime.resolve_session(ctx.session_id, session)
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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    operation = operation.strip()
    session = await runtime.resolve_session(ctx.session_id, session)
    ring_vars = [_validated_identifier(v, "ring_vars") for v in ring_vars]
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
        + f"_R = PolynomialRing({_validated_expression(base_ring)}, '{var_list}')\n"
        + "_R.inject_variables(verbose=False)\n"
        + f"_I = _R.ideal([{polys_code}])\n"
        + ops[operation]
        + "\n"
    )
    result = await _evaluate_structured(session, code)
    return {"operation": operation, "result": result}
