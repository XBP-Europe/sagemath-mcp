"""Systematic coverage of the input spellings each tool must accept.

`test_math_examples.py` covers one spelling per tool: the documented one.
Clients are language models, which emit many spellings of the same request, and
every defect found so far has lived in that gap -- a tool embedding a string
into generated Sage or Python where valid input stops being valid.

Variants are organised by *parameter kind* rather than by tool. There are ~9
kinds across 30 tools, so one variant set covers every tool sharing a kind.

Three complementary checks:

* EQUIVALENCE -- spellings that mean the same thing must produce the same
  answer. This is the strongest check available: it needs no hardcoded expected
  value and it catches silently-wrong results, not just exceptions. "2^10" and
  "2**10" disagreeing is a bug whichever one is right.
* ACCEPTED -- valid input that must work, with a predicate on the value.
* REJECTED -- invalid input that must fail cleanly. Clients retry on error, so
  a clear failure is a usable outcome; a wrong number is not.
"""

import shutil

import pytest

from sagemath_mcp import server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.session import SageSessionManager

from .conftest import FakeContext

requires_sage = pytest.mark.skipif(
    shutil.which("sage") is None, reason="Sage executable not available"
)

S = server


@pytest.fixture(autouse=True)
def unset_pure_python(monkeypatch):
    monkeypatch.delenv("SAGEMATH_MCP_PURE_PYTHON", raising=False)


def _is_png(value) -> bool:
    """Base64 of the PNG magic bytes, with enough payload to be a real image."""
    return isinstance(value, str) and value.startswith("iVBORw0KGgo") and len(value) > 1000


# --------------------------------------------------------------------------
# Equivalence classes: {group: (result key, [(label, call), ...])}
# Every spelling in a group must yield the same value for that key.
# --------------------------------------------------------------------------
EQUIVALENCE: dict[str, tuple[str, list]] = {
    "expression: power operator": ("string", [
        # Sage's preparser turns ^ into exponentiation. In generated code that
        # is executed as plain Python it would mean XOR instead, which is how
        # geometry_operation once computed a complex distance for a 3-4-5
        # triangle. Both spellings must agree.
        ("caret", lambda c: S.calculate_expression("2^10", ctx=c)),
        ("double star", lambda c: S.calculate_expression("2**10", ctx=c)),
    ]),
    "expression: whitespace": ("string", [
        ("compact", lambda c: S.calculate_expression("2+2", ctx=c)),
        ("spaced", lambda c: S.calculate_expression("  2  +  2  ", ctx=c)),
        # Models wrap and indent freely, so a newline must not be a syntax error.
        ("newline", lambda c: S.calculate_expression("2 +\n2", ctx=c)),
        ("tab", lambda c: S.calculate_expression("2\t+\t2", ctx=c)),
    ]),
    "expression: unicode constant": ("string", [
        ("ascii", lambda c: S.calculate_expression("pi.n()", ctx=c)),
        ("unicode", lambda c: S.calculate_expression("π.n()", ctx=c)),
    ]),
    "equation: equality spelling": ("solutions", [
        ("single equals", lambda c: S.solve_equation("x^2 - 1 = 0", "x", ctx=c)),
        ("double equals", lambda c: S.solve_equation("x^2 - 1 == 0", "x", ctx=c)),
        ("implicit zero", lambda c: S.solve_equation("x^2 - 1", "x", ctx=c)),
        ("sides reversed", lambda c: S.solve_equation("0 = x^2 - 1", "x", ctx=c)),
    ]),
    "equation: variable container": ("solutions", [
        ("string", lambda c: S.solve_equation("x^2 - 1 = 0", "x", ctx=c)),
        ("list", lambda c: S.solve_equation("x^2 - 1 = 0", ["x"], ctx=c)),
    ]),
    "equation: single equation container": ("solutions", [
        ("bare", lambda c: S.solve_equation("x^2 - 1 = 0", "x", ctx=c)),
        ("wrapped in list", lambda c: S.solve_equation(["x^2 - 1 = 0"], "x", ctx=c)),
    ]),
    "ode: function application": ("solution", [
        # The #12 regression, kept here so it is covered by the syntax matrix
        # as well as by its own dedicated test.
        ("applied y(x)", lambda c: S.solve_ode("diff(y(x), x) + y(x) = 0", ctx=c)),
        ("bare y", lambda c: S.solve_ode("diff(y, x) + y = 0", ctx=c)),
    ]),
    "bound: infinity spelling": ("limit", [
        ("oo", lambda c: S.limit_expression("1/x", "x", "oo", ctx=c)),
        ("plus oo", lambda c: S.limit_expression("1/x", "x", "+oo", ctx=c)),
        ("infinity", lambda c: S.limit_expression("1/x", "x", "infinity", ctx=c)),
        ("Infinity", lambda c: S.limit_expression("1/x", "x", "Infinity", ctx=c)),
    ]),
    "bound: numeric spelling": ("integral", [
        ("integer", lambda c: S.integrate_expression(
            "x^2", "x", lower_bound="0", upper_bound="1", ctx=c)),
        ("decimal", lambda c: S.integrate_expression(
            "x^2", "x", lower_bound="0.0", upper_bound="1.0", ctx=c)),
        ("rational", lambda c: S.integrate_expression(
            "x^2", "x", lower_bound="0", upper_bound="2/2", ctx=c)),
    ]),
    "matrix: entry types": ("result", [
        ("integers", lambda c: S.matrix_operation([[1, 2], [3, 4]], "determinant", ctx=c)),
        ("floats", lambda c: S.matrix_operation([[1.0, 2.0], [3.0, 4.0]], "determinant", ctx=c)),
    ]),
    "constructor: named graph spelling": ("result", [
        ("bare name", lambda c: S.graph_operation("PetersenGraph", "order", ctx=c)),
        ("explicit call", lambda c: S.graph_operation("PetersenGraph()", "order", ctx=c)),
        ("padded", lambda c: S.graph_operation("  PetersenGraph  ", "order", ctx=c)),
    ]),
    "boolean: variable spelling": ("result", [
        ("documented x,y,z", lambda c: S.boolean_algebra_operation(
            "x*y + x*z + y*z", "degree", num_variables=3, ctx=c)),
        ("generator x0,x1,x2", lambda c: S.boolean_algebra_operation(
            "x0*x1 + x0*x2 + x1*x2", "degree", num_variables=3, ctx=c)),
    ]),
}


# --------------------------------------------------------------------------
# Valid input that must be accepted, with a predicate on the result.
# --------------------------------------------------------------------------
ACCEPTED: dict[str, list] = {
    "bound: symbolic": [
        # An integral to a symbolic limit is ordinary calculus. The prelude
        # declares only x, y, z, t, so anything else used to raise NameError.
        ("integrate to a", lambda c: S.integrate_expression(
            "x", "x", lower_bound="0", upper_bound="a", ctx=c), "integral", "1/2*a^2"),
        ("limit at a", lambda c: S.limit_expression("x^2", "x", "a", ctx=c), "limit", "a^2"),
        # n and N are numerical_approx in Sage's namespace; as a summation
        # bound they must still be treated as free symbols.
        ("sum to n", lambda c: S.symbolic_sum("k", "k", "1", "n", ctx=c),
         "result", "1/2*n^2 + 1/2*n"),
        ("sum to N", lambda c: S.symbolic_sum("k", "k", "1", "N", ctx=c),
         "result", "1/2*N^2 + 1/2*N"),
    ],
    "bound: constants must not be shadowed": [
        # The mirror of the case above: these names must keep their Sage
        # meaning. Declaring them as symbols would silently change the answer.
        ("integrate to e is ln(e) = 1", lambda c: S.integrate_expression(
            "1/x", "x", lower_bound="1", upper_bound="e", ctx=c), "integral", "1"),
        ("integrate sin to pi is 2", lambda c: S.integrate_expression(
            "sin(x)", "x", lower_bound="0", upper_bound="pi", ctx=c), "integral", "2"),
        ("integrate cos to pi/2 is 1", lambda c: S.integrate_expression(
            "cos(x)", "x", lower_bound="0", upper_bound="pi/2", ctx=c), "integral", "1"),
        ("sum to oo is basel", lambda c: S.symbolic_sum("1/n^2", "n", "1", "oo", ctx=c),
         "result", "1/6*pi^2"),
    ],
    "constructor: parameterised graphs": [
        # Matching on a "Graph" suffix rejected every constructor taking
        # arguments, which is most of Sage's catalogue.
        ("CompleteGraph(4) order", lambda c: S.graph_operation(
            "CompleteGraph(4)", "order", ctx=c), "result", 4),
        ("CompleteGraph(4) size", lambda c: S.graph_operation(
            "CompleteGraph(4)", "size", ctx=c), "result", 6),
        ("CycleGraph(6) size", lambda c: S.graph_operation(
            "CycleGraph(6)", "size", ctx=c), "result", 6),
        ("CompleteBipartiteGraph(2,3)", lambda c: S.graph_operation(
            "CompleteBipartiteGraph(2,3)", "order", ctx=c), "result", 5),
        ("adjacency dict still works", lambda c: S.graph_operation(
            "{0:[1,2], 1:[0,2], 2:[0,1]}", "order", ctx=c), "result", 3),
    ],
    "variable: naming": [
        ("multi-character name", lambda c: S.differentiate_expression(
            "t1^2", "t1", ctx=c), "derivative", "2*t1"),
        ("greek word name", lambda c: S.differentiate_expression(
            "alpha^3", "alpha", ctx=c), "derivative", "3*alpha^2"),
        ("non-default variable", lambda c: S.integrate_expression(
            "u^2", "u", ctx=c), "integral", "1/3*u^3"),
    ],
    "expression: numeric literals": [
        ("rational stays exact", lambda c: S.calculate_expression("1/3", ctx=c),
         "string", "1/3"),
        ("unary minus", lambda c: S.calculate_expression("-2^2", ctx=c), "string", "-4"),
        ("nested parentheses", lambda c: S.expand_expression("((x+1)*(x-1))", ctx=c),
         "expanded", "x^2 - 1"),
        ("scientific notation", lambda c: S.calculate_expression("1e3", ctx=c),
         "numeric", 1000.0),
    ],
    "variable: names that shadow Sage objects": [
        # e, I and N all mean something in Sage's namespace. Used as the
        # variable of differentiation they must still behave as symbols,
        # because the tool declares them explicitly.
        ("e as a variable", lambda c: S.differentiate_expression("e^2", "e", ctx=c),
         "derivative", "2*e"),
        ("N as a variable", lambda c: S.differentiate_expression("N^2", "N", ctx=c),
         "derivative", "2*N"),
        ("I as a variable", lambda c: S.differentiate_expression("I^2", "I", ctx=c),
         "derivative", "2*I"),
        ("gamma as a variable", lambda c: S.differentiate_expression("gamma^2", "gamma", ctx=c),
         "derivative", "2*gamma"),
    ],
    "operation: surrounding whitespace": [
        # Tool arguments arrive as JSON from a model, so a stray space in an
        # enum should not be the difference between working and not.
        ("matrix", lambda c: S.matrix_operation([[1, 2], [3, 4]], " determinant ", ctx=c),
         "result", -2.0),
        ("graph", lambda c: S.graph_operation("PetersenGraph", " order ", ctx=c), "result", 10),
        ("group", lambda c: S.group_operation("SymmetricGroup(4)", " order ", ctx=c),
         "result", 24),
        ("number theory", lambda c: S.number_theory_operation(" is_prime ", 7, ctx=c),
         "result", True),
    ],
    "range: numeric spans": [
        ("negative span", lambda c: S.plot_expression("sin(x)", "x", -6.28, -3.14, ctx=c),
         "image_base64", _is_png),
        ("reversed bounds", lambda c: S.plot_expression("sin(x)", "x", 3.0, -3.0, ctx=c),
         "image_base64", _is_png),
        ("integer bounds", lambda c: S.plot_expression("sin(x)", "x", -3, 3, ctx=c),
         "image_base64", _is_png),
        ("find_root reversed interval",
         lambda c: S.find_root("x - cos(x)", "x", 1.0, 0.0, ctx=c), "root", 0.7390851332151559),
    ],
    "list parameters: arity": [
        ("one expression", lambda c: S.plot_multi_expression(["sin(x)"], ctx=c),
         "image_base64", _is_png),
        ("four expressions",
         lambda c: S.plot_multi_expression(["sin(x)", "cos(x)", "x", "x^2"], ctx=c),
         "image_base64", _is_png),
        ("single ring variable",
         lambda c: S.polynomial_ring_operation(["a"], ["a^2-1"], "groebner_basis", ctx=c),
         "result", ["a^2 - 1"]),
        ("two-dimensional divergence",
         lambda c: S.vector_calculus_operation("divergence", ["x", "y"], ["x", "y"], ctx=c),
         "result", "2"),
    ],
    "matrix: shapes": [
        ("1xN times Nx1", lambda c: S.matrix_multiply([[1, 2, 3]], [[1], [2], [3]], ctx=c),
         "product", [[14.0]]),
        ("rank of a non-square matrix",
         lambda c: S.matrix_operation([[1, 2, 3], [4, 5, 6]], "rank", ctx=c), "result", 2),
        ("1x1 determinant", lambda c: S.matrix_operation([[5]], "determinant", ctx=c),
         "result", 5.0),
    ],
    "distribution: parameter arity": [
        ("normal with no parameters is standard",
         lambda c: S.distribution_operation("normal", [], "mean", ctx=c), "result", 0.0),
        ("normal with no parameters has unit variance",
         lambda c: S.distribution_operation("normal", [], "variance", ctx=c), "result", 1.0),
        ("student_t variance needs nu > 2",
         lambda c: S.distribution_operation("student_t", [5], "variance", ctx=c),
         "result", 5 / 3),
    ],
}


# --------------------------------------------------------------------------
# Invalid input that must fail cleanly rather than return a wrong answer.
# --------------------------------------------------------------------------
REJECTED: list = [
    # --- expression syntax ---
    # Sage does not support implicit multiplication either; the contract is
    # that it fails rather than silently parsing as something else.
    ("implicit multiplication", lambda c: S.differentiate_expression("2x", "x", ctx=c)),
    ("latex input", lambda c: S.calculate_expression(r"\sqrt{4}", ctx=c)),
    ("wrong case function", lambda c: S.calculate_expression("Sin(0)", ctx=c)),
    ("unbalanced parenthesis", lambda c: S.calculate_expression("(2+3", ctx=c)),
    # --- unknown enum values ---
    ("unknown matrix operation", lambda c: S.matrix_operation([[1]], "nonsense", ctx=c)),
    ("unknown graph operation", lambda c: S.graph_operation("PetersenGraph", "nonsense", ctx=c)),
    ("unknown distribution", lambda c: S.distribution_operation("nonsense", [1], "mean", ctx=c)),
    # --- degenerate collections ---
    # An empty matrix is the dangerous one: Sage reads [] as the 0x0 matrix and
    # reports its determinant as 1.0, which reads like a real answer.
    ("empty matrix", lambda c: S.matrix_operation([], "determinant", ctx=c)),
    ("matrix with empty rows", lambda c: S.matrix_operation([[]], "determinant", ctx=c)),
    ("ragged matrix", lambda c: S.matrix_operation([[1, 2], [3]], "determinant", ctx=c)),
    # Previously raised a bare "list index out of range" from the median.
    ("empty statistics data", lambda c: S.statistics_summary([], ctx=c)),
    ("empty geometry points", lambda c: S.geometry_operation("polygon_area", [], ctx=c)),
    # Previously returned {'result': None} as though that were an answer.
    ("distance from a single point",
     lambda c: S.geometry_operation("distance", [[0, 0]], ctx=c)),
    # --- shape mismatches ---
    ("non-conformable multiplication", lambda c: S.matrix_multiply([[1, 2]], [[1, 2]], ctx=c)),
    ("determinant of a non-square matrix",
     lambda c: S.matrix_operation([[1, 2, 3], [4, 5, 6]], "determinant", ctx=c)),
    ("inverse of a singular matrix",
     lambda c: S.matrix_operation([[1, 2], [2, 4]], "inverse", ctx=c)),
    # --- degenerate ranges ---
    ("zero-width plot range", lambda c: S.plot_expression("sin(x)", "x", 1.0, 1.0, ctx=c)),
    ("root outside the interval", lambda c: S.find_root("x^2 + 1", "x", 0.0, 1.0, ctx=c)),
    # --- undefined mathematics ---
    # The mean of a Cauchy distribution genuinely does not exist; saying so is
    # the correct answer, not a limitation.
    ("student_t mean at nu = 1",
     lambda c: S.distribution_operation("student_t", [1], "mean", ctx=c)),
    ("uniform needs two parameters",
     lambda c: S.distribution_operation("uniform", [1], "mean", ctx=c)),
]


@requires_sage
@pytest.mark.asyncio
@pytest.mark.parametrize("group", sorted(EQUIVALENCE), ids=sorted(EQUIVALENCE))
async def test_equivalent_spellings_agree(monkeypatch, group):
    """Spellings that mean the same thing must produce the same answer."""

    key, cases = EQUIVALENCE[group]
    settings = SageSettings(force_python_worker=False, eval_timeout=120.0)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)

    observed: dict[str, object] = {}
    failures: list[str] = []
    try:
        for label, factory in cases:
            ctx = FakeContext(f"variants-{group}")
            try:
                result = await factory(ctx)
            except Exception as exc:
                failures.append(f"{label}: raised {type(exc).__name__}: {exc}")
                continue
            if key not in result:
                failures.append(f"{label}: result has no key {key!r}; got {result!r}")
                continue
            observed[label] = result[key]
    finally:
        await manager.shutdown()

    assert not failures, f"{group}:\n" + "\n".join(f"  - {f}" for f in failures)
    distinct = {repr(v) for v in observed.values()}
    assert len(distinct) == 1, (
        f"{group}: spellings disagree, but they describe the same value\n"
        + "\n".join(f"  - {label} -> {value!r}" for label, value in observed.items())
    )


@requires_sage
@pytest.mark.asyncio
@pytest.mark.parametrize("group", sorted(ACCEPTED), ids=sorted(ACCEPTED))
async def test_valid_spellings_are_accepted(monkeypatch, group):
    """Valid input must be accepted and produce the right value."""

    settings = SageSettings(force_python_worker=False, eval_timeout=120.0)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)

    failures: list[str] = []
    try:
        for label, factory, key, expected in ACCEPTED[group]:
            ctx = FakeContext(f"variants-{group}")
            try:
                result = await factory(ctx)
            except Exception as exc:
                failures.append(f"{label}: raised {type(exc).__name__}: {exc}")
                continue
            actual = result.get(key)
            if callable(expected):
                ok = bool(expected(actual))
            elif isinstance(expected, float):
                ok = actual is not None and abs(float(actual) - expected) < 1e-9
            else:
                ok = actual == expected
            if not ok:
                wanted = getattr(expected, "__name__", repr(expected))
                failures.append(f"{label}: expected {wanted}, got {str(actual)[:80]!r}")
    finally:
        await manager.shutdown()

    assert not failures, f"{group}:\n" + "\n".join(f"  - {f}" for f in failures)


@requires_sage
@pytest.mark.asyncio
async def test_invalid_input_fails_cleanly(monkeypatch):
    """Invalid input must raise with a usable message, never return a value.

    Returning a wrong number here would be the worst outcome: the client has no
    way to tell it apart from a correct one. An error is recoverable, because
    the caller can correct the request and retry.
    """

    settings = SageSettings(force_python_worker=False, eval_timeout=120.0)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)

    failures: list[str] = []
    try:
        for label, factory in REJECTED:
            ctx = FakeContext("variants-invalid")
            try:
                result = await factory(ctx)
            except Exception as exc:
                message = str(exc).strip()
                if not message:
                    failures.append(f"{label}: raised {type(exc).__name__} with an empty message")
                continue
            failures.append(f"{label}: accepted invalid input and returned {result!r}")
    finally:
        await manager.shutdown()

    assert not failures, "invalid input handling:\n" + "\n".join(f"  - {f}" for f in failures)
