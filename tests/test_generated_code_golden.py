"""The Sage code every tool generates, pinned byte for byte.

This exists to make the 2026-09 refactor provable (REFACTOR_PLAN.md), the way
test_tool_inventory made the server.py split provable. Moving the verify ladder
out of its f-string, splitting codegen.py and centralising the session lookup
are large diffs a reviewer cannot check line by line. The question "does any
tool now send different code to Sage?" is answered mechanically instead.

Each case calls a tool against a recording session and captures every code
string the tool hands to `session.evaluate`, together with whether it asked for
the trusted policy -- generated code runs under `trusted_policy()`, so that
flag is part of what is pinned. The stub's reply is not what the tool expects,
so most tools raise after sending their code; the capture is what matters. A
tool that would make a second call depending on the first reply only has its
first call pinned.

The shared prelude is stored once and marked `<<PRELUDE>>` wherever a case
begins with it, so the fixture stays readable in a diff.

Regenerate deliberately, never to make a red test green:

    python -m tests.test_generated_code_golden --write
"""

from __future__ import annotations

import asyncio
import difflib
from pathlib import Path

import pytest

from sagemath_mcp import runtime, server
from sagemath_mcp.prelude import sage_prelude
from sagemath_mcp.session import SageSessionManager, WorkerResult

from .conftest import FakeContext

SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "generated_code.txt"
PRELUDE_MARK = "<<PRELUDE>>"

# (case id, tool name, keyword arguments). Every Sage-backed tool appears, and
# every operation of each `*_operation` tool, because each operation is its
# own template.
CASES: list[tuple[str, str, dict]] = [
    ("evaluate_sage", "evaluate_sage", {"code": "a = 2^10\na + 1"}),
    ("evaluate_sage_streaming", "evaluate_sage_streaming", {"code": "print(1)"}),
    ("calculate_expression", "calculate_expression", {"expression": "2^10 + sqrt(2)"}),
    ("simplify_expression", "simplify_expression", {"expression": "sin(x)^2 + cos(x)^2"}),
    ("expand_expression", "expand_expression", {"expression": "(x + y)^3"}),
    ("factor_expression", "factor_expression", {"expression": "x^2 - 1"}),
    ("find_root", "find_root",
     {"expression": "cos(x) - x", "lower_bound": 0, "upper_bound": 1}),
    ("solve_equation", "solve_equation", {"equation": "x^2 - 2 = 0", "variable": "x"}),
    ("differentiate_expression", "differentiate_expression",
     {"expression": "sin(x)*x", "variable": "x", "order": 2}),
    ("integrate_indefinite", "integrate_expression", {"expression": "x^2", "variable": "x"}),
    ("integrate_definite", "integrate_expression",
     {"expression": "x^2", "variable": "x", "lower_bound": "0", "upper_bound": "1"}),
    ("limit_expression", "limit_expression",
     {"expression": "sin(x)/x", "variable": "x", "point": "0"}),
    ("limit_one_sided", "limit_expression",
     {"expression": "1/x", "variable": "x", "point": "0", "direction": "plus"}),
    ("series_expansion", "series_expansion",
     {"expression": "exp(x)", "variable": "x", "point": "0", "order": 4}),
    ("symbolic_sum", "symbolic_sum",
     {"expression": "k^2", "variable": "k", "lower": "1", "upper": "n"}),
    ("symbolic_product", "symbolic_sum",
     {"expression": "k", "variable": "k", "lower": "1", "upper": "n", "product": True}),
    ("solve_ode", "solve_ode",
     {"equation": "diff(y(x),x) + y(x) = 0", "variable": "x", "function": "y"}),
    ("matrix_multiply", "matrix_multiply",
     {"matrix_a": [[1, 2], [3, 4]], "matrix_b": [[0, 1], [1, 0]]}),
    ("statistics_summary", "statistics_summary", {"data": [1, 2, 3, 4, 10]}),
    ("plot_expression", "plot_expression", {"expression": "sin(x)"}),
    ("plot3d_expression", "plot3d_expression", {"expression": "x*y"}),
    ("plot_multi_expression", "plot_multi_expression", {"expressions": ["sin(x)", "cos(x)"]}),
    ("verify_claim", "verify_claim", {"claim": "sin(x)^2 + cos(x)^2 == 1"}),
    ("verify_claim_inequality", "verify_claim", {"claim": "x^2 + 1 > 0"}),
    ("verify_claim_decimals", "verify_claim",
     {"claim": "0.1 + 0.2 == 0.3", "samples": 5, "precision_bits": 64}),
]
CASES += [
    (f"matrix_operation_{op}", "matrix_operation",
     {"matrix": [[2, 1], [1, 3]], "operation": op})
    for op in ("determinant", "inverse", "eigenvalues", "rank", "rref", "transpose")
]
CASES += [
    (f"number_theory_{op}", "number_theory_operation",
     {"operation": op, "a": 84, "b": 36 if op in ("gcd", "lcm") else None})
    for op in ("is_prime", "factor_integer", "next_prime", "gcd", "lcm")
]
CASES += [
    (f"combinatorics_{op}", "combinatorics_operation",
     {"operation": op, "n": 10, "k": 3 if op in ("binomial", "combinations") else None})
    for op in ("binomial", "permutations", "combinations", "partitions", "factorial",
               "catalan", "fibonacci", "bell")
]
CASES += [
    (f"distribution_{dist}_{op}", "distribution_operation",
     {"distribution": dist, "parameters": params, "operation": op, "x": 0.5, "n": 3})
    for dist, params in (
        ("normal", [0, 1]), ("exponential", [2]), ("poisson", [3]),
        ("chi_squared", [4]), ("student_t", [5]), ("uniform", [0, 2]),
        ("beta", [2, 3]), ("gamma", [2, 1]),
    )
    for op in ("pdf", "cdf", "quantile", "mean", "variance", "sample")
]
CASES += [
    (f"vector_calculus_{op}", "vector_calculus_operation",
     {"expression": ["x*y", "y*z", "z*x"] if op in ("divergence", "curl") else "x^2*y + z",
      "operation": op, "variables": ["x", "y", "z"]})
    for op in ("gradient", "divergence", "curl", "laplacian")
]
CASES += [
    (f"graph_{op}", "graph_operation",
     {"graph": "PetersenGraph", "operation": op,
      **({"source": 0, "target": 7} if op == "shortest_path" else {})})
    for op in ("chromatic_number", "is_connected", "is_planar", "diameter", "order",
               "size", "degree_sequence", "adjacency_matrix", "shortest_path")
]
CASES += [("graph_adjacency_dict", "graph_operation",
           {"graph": "{0:[1,2], 1:[0,2], 2:[0,1]}", "operation": "order"})]
CASES += [
    (f"group_{op}", "group_operation", {"group": "DihedralGroup(4)", "operation": op})
    for op in ("order", "is_abelian", "is_cyclic", "center_order",
               "conjugacy_classes_count", "exponent")
]
CASES += [
    (f"elliptic_curve_{op}", "elliptic_curve_operation",
     {"coefficients": [0, 0, 1, -1, 0], "operation": op})
    for op in ("rank", "torsion_order", "discriminant", "j_invariant", "conductor", "gens")
]
CASES += [
    (f"coding_theory_{op}", "coding_theory_operation",
     {"code_type": "HammingCode(GF(2),3)", "operation": op})
    for op in ("length", "dimension", "minimum_distance", "generator_matrix", "rate")
]
CASES += [
    (f"boolean_algebra_{op}", "boolean_algebra_operation",
     {"expression": "x*y + x*z + y*z", "operation": op, "num_variables": 3})
    for op in ("evaluate", "variables", "degree", "is_zero", "is_one", "reduce")
]
CASES += [
    (f"polynomial_ring_{op}", "polynomial_ring_operation",
     {"polynomials": ["a^2+b", "b^2-1"], "ring_vars": ["a", "b"], "operation": op})
    for op in ("groebner_basis", "ideal_dimension", "ideal_variety", "reduce", "is_groebner")
]
CASES += [
    (f"geometry_{op}", "geometry_operation",
     {"operation": op,
      "points": [[0, 0], [3, 4]] if op == "distance" else [[0, 0], [1, 0], [1, 1], [0, 1]]})
    for op in ("distance", "polygon_area", "polytope_volume", "convex_hull_vertices",
               "is_convex")
]


class _RecordingSession:
    """Records what a tool sends; replies with a value no tool expects."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    async def evaluate(self, code: str, *args, trusted: bool = False, **kwargs):
        self.calls.append((code, trusted))
        return WorkerResult(
            result_type="expression", result="None", latex=None, stdout="", elapsed_ms=0.0
        )


async def _capture() -> dict[str, tuple[list, str | None]]:
    """Per case: the calls made, and the refusal when the tool made none.

    Some combinations never reach Sage -- a distribution without that operation
    is refused up front, a closed-form mean is computed in Python. That is
    behaviour too, so the refusal is pinned in place of code.
    """
    captured: dict[str, tuple[list, str | None]] = {}
    for case_id, tool, kwargs in CASES:
        session = _RecordingSession()
        manager = SageSessionManager(server.DEFAULT_SETTINGS)

        async def fake_get(_key: str, _session=session):
            return _session

        manager.get = fake_get  # type: ignore[method-assign]
        previous = runtime.SESSION_MANAGER
        runtime.SESSION_MANAGER = manager
        outcome: str | None = None
        try:
            result = await getattr(server, tool)(**kwargs, ctx=FakeContext())
            outcome = f"returned {result!r}"
        except Exception as exc:  # the stub reply is meant to be wrong
            outcome = f"raised {type(exc).__name__}: {exc}"
        finally:
            runtime.SESSION_MANAGER = previous
        captured[case_id] = (session.calls, None if session.calls else outcome)
    return captured


def _render(captured: dict[str, tuple[list, str | None]]) -> str:
    prelude = sage_prelude()
    lines = ["=== <<PRELUDE>>", prelude.rstrip("\n"), ""]
    for case_id, (calls, no_code) in captured.items():
        if no_code is not None:
            lines.append(f"=== {case_id} [no code sent]")
            lines.append(no_code)
            lines.append("")
        for index, (code, trusted) in enumerate(calls, start=1):
            if code.startswith(prelude):
                code = PRELUDE_MARK + "\n" + code[len(prelude):]
            lines.append(f"=== {case_id} [call {index}] trusted={trusted}")
            lines.append(code.rstrip("\n"))
            lines.append("")
    return "\n".join(lines) + "\n"


def test_every_sage_backed_tool_has_a_case() -> None:
    cased = {tool for _, tool, _ in CASES}
    infrastructure = {
        "reset_sage_session", "cancel_sage_session", "interrupt_sage_session",
        "start_sage_session", "list_sage_sessions", "stop_sage_session",
        "check_sage_health", "lookup_sage_doc",
    }
    tools = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    missing = sorted(tools - infrastructure - cased)
    assert not missing, f"no golden case for: {missing}"


def test_the_generated_code_is_unchanged() -> None:
    current = _render(asyncio.run(_capture()))
    expected = SNAPSHOT.read_text(encoding="utf-8")
    if current != expected:
        diff = "".join(
            list(difflib.unified_diff(
                expected.splitlines(keepends=True), current.splitlines(keepends=True),
                "fixtures/generated_code.txt", "generated now",
            ))[:200]
        )
        pytest.fail("a tool now generates different Sage code:\n" + diff)


def test_the_capture_is_deterministic() -> None:
    assert _render(asyncio.run(_capture())) == _render(asyncio.run(_capture()))


if __name__ == "__main__":  # pragma: no cover - maintenance helper
    import sys

    if "--write" in sys.argv:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(_render(asyncio.run(_capture())), encoding="utf-8")
        print(f"wrote {SNAPSHOT}")
