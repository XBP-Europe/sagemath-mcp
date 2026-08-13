"""Number theory, combinatorics, graphs, groups, curves and codes.

One of the tool modules imported by :mod:`sagemath_mcp.server` for its
registration side effect. Decorating against the shared ``mcp`` object keeps
every tool name exactly as it was; FastMCP's mount/import_server composition
would have prefixed them.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from .. import runtime
from ..app import mcp
from ..codegen import (
    _NAMED_GRAPH_RE,
    _encode_literal,
    _evaluate_structured,
    _exact_int,
    _sage_prelude,
    _validated_expression,
)
from ..session import (
    DEFAULT_SESSION_NAME,
)
from ..text import SESSION_ARG_DESC as _SESSION_ARG_DESC


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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
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
    session = await runtime.resolve_session(ctx.session_id, session)
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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required for stateful execution")
    operation = operation.strip()
    session = await runtime.resolve_session(ctx.session_id, session)
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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    operation = operation.strip()
    session = await runtime.resolve_session(ctx.session_id, session)
    # A named graph is an identifier, optionally already called with arguments.
    # Matching on a "Graph" suffix missed every parameterised constructor:
    # "CompleteGraph(4)" ends in ")", so it fell through to Graph(CompleteGraph(4))
    # and failed with "name 'CompleteGraph' is not defined". Most named graphs
    # take parameters, so that was the majority of the catalogue.
    # Validated as an expression in its own right: this string is interpolated
    # into code that runs under the trusted policy, where sage_eval is allowed.
    graph = _validated_expression(graph)
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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    operation = operation.strip()
    session = await runtime.resolve_session(ctx.session_id, session)
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
    code = _sage_prelude() + f"_G = {_validated_expression(group)}\n" + ops[operation] + "\n"
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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    operation = operation.strip()
    session = await runtime.resolve_session(ctx.session_id, session)
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
    session: Annotated[str, Field(description=_SESSION_ARG_DESC)] = DEFAULT_SESSION_NAME,
    ctx: Context | None = None,
) -> dict:
    if ctx is None or ctx.session_id is None:
        raise ToolError("MCP context with session_id is required")
    operation = operation.strip()
    session = await runtime.resolve_session(ctx.session_id, session)
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
        + f"_C = codes.{_validated_expression(code_type)}\n"
        + ops[operation]
        + "\n"
    )
    result = await _evaluate_structured(session, code)
    return {"operation": operation, "result": result}
