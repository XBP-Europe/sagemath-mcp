"""Systematic real-Sage coverage of every Sage-backed MCP tool.

Issue #12 was a tool rejecting the exact input its own docstring advertised.
That class of bug is invisible to unit tests, which stub the Sage worker and
therefore never evaluate the generated code.

Two rules keep this suite able to catch it:

1. Every tool is exercised with the examples from its own ``Field``
   descriptions, so a documented input that does not work fails here.
2. Every case asserts a *value*. Checking only that no exception was raised
   would have missed ``distribution_operation(..., "mean")``, which returned a
   random sample, and ``"variance"``, which returned ``None``.

Cases are grouped per tool. Each group runs all of its cases and reports every
failure at once, rather than stopping at the first.
"""

import math
import shutil

import pytest

from sagemath_mcp import runtime, server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.session import SageSessionManager

from .conftest import FakeContext

requires_sage = pytest.mark.skipif(
    shutil.which("sage") is None, reason="Sage executable not available"
)


@pytest.fixture(autouse=True)
def unset_pure_python(monkeypatch):
    monkeypatch.delenv("SAGEMATH_MCP_PURE_PYTHON", raising=False)


def approx(value: float, tolerance: float = 1e-6):
    """Match a float result within a tolerance."""

    def check(actual):
        return actual is not None and math.isclose(float(actual), value, rel_tol=tolerance,
                                                   abs_tol=tolerance)

    check.__name__ = f"approx({value})"
    return check


def contains(*fragments: str):
    """Match a stringified result containing every fragment."""

    def check(actual):
        text = str(actual)
        return all(fragment in text for fragment in fragments)

    check.__name__ = f"contains{fragments}"
    return check


def _matches(expected, actual) -> bool:
    if callable(expected):
        return bool(expected(actual))
    return expected == actual


# Each entry: (case id, coroutine factory, key into the result dict, expected).
# "doc:" marks an example taken verbatim from the tool's own Field description.
S = server

GROUPS: dict[str, list] = {
    "calculate_expression": [
        ("2+2", lambda c: S.calculate_expression("2+2", ctx=c), "string", "4"),
        ("factorial(10)", lambda c: S.calculate_expression("factorial(10)", ctx=c),
         "string", "3628800"),
        ("sqrt(16)", lambda c: S.calculate_expression("sqrt(16)", ctx=c), "numeric", approx(4.0)),
    ],
    "solve_equation": [
        # doc: "x^2 - 1 = 0"
        ("doc:quadratic", lambda c: S.solve_equation("x^2 - 1 = 0", "x", ctx=c),
         "solutions", ["x == -1", "x == 1"]),
        ("linear system", lambda c: S.solve_equation(["x + y = 3", "x - y = 1"], ["x", "y"], ctx=c),
         "solutions", ["[x == 2, y == 1]"]),
    ],
    "differentiate_expression": [
        ("product rule", lambda c: S.differentiate_expression("sin(x)*x^2", "x", ctx=c),
         "derivative", "x^2*cos(x) + 2*x*sin(x)"),
        ("second order", lambda c: S.differentiate_expression("x^4", "x", order=2, ctx=c),
         "derivative", "12*x^2"),
    ],
    "integrate_expression": [
        ("indefinite", lambda c: S.integrate_expression("x^2", "x", ctx=c), "integral", "1/3*x^3"),
        # doc: lower '0' / upper '1'
        ("doc:definite 0..1",
         lambda c: S.integrate_expression("x^2", "x", lower_bound="0", upper_bound="1", ctx=c),
         "integral", "1/3"),
        # doc: '-oo' / 'oo' -- the Gaussian integral
        ("doc:gaussian -oo..oo",
         lambda c: S.integrate_expression("exp(-x^2)", "x", lower_bound="-oo", upper_bound="oo",
                                          ctx=c),
         "integral", "sqrt(pi)"),
    ],
    "simplify_expression": [
        ("pythagorean identity",
         lambda c: S.simplify_expression("sin(x)^2 + cos(x)^2", ctx=c),
         "simplified", contains("sin(x)^2", "cos(x)^2")),
    ],
    "expand_expression": [
        ("binomial cube", lambda c: S.expand_expression("(x+1)^3", ctx=c),
         "expanded", "x^3 + 3*x^2 + 3*x + 1"),
    ],
    "factor_expression": [
        # doc: 'x^2 - 1'
        ("doc:polynomial", lambda c: S.factor_expression("x^2 - 1", ctx=c),
         "factored", "(x + 1)*(x - 1)"),
        # doc: '60'
        ("doc:integer", lambda c: S.factor_expression("60", ctx=c), "factored", "2^2 * 3 * 5"),
    ],
    "limit_expression": [
        # doc: point '0'
        ("doc:sinc at 0", lambda c: S.limit_expression("sin(x)/x", "x", "0", ctx=c), "limit", "1"),
        # doc: point 'oo'
        ("doc:1/x at oo", lambda c: S.limit_expression("1/x", "x", "oo", ctx=c), "limit", "0"),
        ("one-sided from the right",
         lambda c: S.limit_expression("1/x", "x", "0", direction="plus", ctx=c),
         "limit", "+Infinity"),
    ],
    "series_expansion": [
        ("exp about 0", lambda c: S.series_expansion("exp(x)", "x", "0", 5, ctx=c),
         "series", contains("1/2*x^2", "1/6*x^3", "1/24*x^4")),
    ],
    "symbolic_sum": [
        # doc: '1/n^2', 'n', '1', 'oo' -- the Basel problem
        ("doc:basel problem", lambda c: S.symbolic_sum("1/n^2", "n", "1", "oo", ctx=c),
         "result", "1/6*pi^2"),
        ("finite product", lambda c: S.symbolic_sum("n", "n", "1", "5", product=True, ctx=c),
         "result", "120"),
    ],
    "find_root": [
        # doc: 'x - cos(x)' -- the Dottie number
        ("doc:dottie number", lambda c: S.find_root("x - cos(x)", "x", 0.0, 1.0, ctx=c),
         "root", approx(0.7390851332151607, 1e-9)),
        # doc: 'E - 0.6*sin(E) = 0.75' -- Kepler's equation, stated as an
        # equation because that is how it is written and how it arrives.
        ("doc:keplers equation",
         lambda c: S.find_root("E - 0.6*sin(E) = 0.75", "E", 0.0, 3.0, ctx=c),
         "root", approx(1.3331346926634313, 1e-9)),
        ("equation with ==",
         lambda c: S.find_root("E - 0.6*sin(E) == 0.75", "E", 0.0, 3.0, ctx=c),
         "root", approx(1.3331346926634313, 1e-9)),
        # The same root the plain-expression way: the two spellings must agree.
        ("equation rearranged by hand",
         lambda c: S.find_root("E - 0.6*sin(E) - 0.75", "E", 0.0, 3.0, ctx=c),
         "root", approx(1.3331346926634313, 1e-9)),
        # A keyword argument is not an equation. This is why the split happens
        # only after the whole string fails to parse.
        ("keyword argument is not an equation",
         lambda c: S.find_root("log(x, base=2) - 1", "x", 1.0, 4.0, ctx=c),
         "root", approx(2.0, 1e-9)),
    ],
    "matrix_multiply": [
        ("2x2", lambda c: S.matrix_multiply([[1, 2], [3, 4]], [[5, 6], [7, 8]], ctx=c),
         "product", [[19.0, 22.0], [43.0, 50.0]]),
    ],
    "matrix_operation": [
        ("determinant", lambda c: S.matrix_operation([[1, 2], [3, 4]], "determinant", ctx=c),
         "result", approx(-2.0)),
        ("inverse", lambda c: S.matrix_operation([[1, 2], [3, 4]], "inverse", ctx=c),
         "result", [[-2.0, 1.0], [1.5, -0.5]]),
        ("rank", lambda c: S.matrix_operation([[1, 2], [3, 4]], "rank", ctx=c), "result", 2),
        ("rref", lambda c: S.matrix_operation([[1, 2], [3, 4]], "rref", ctx=c),
         "result", [[1.0, 0.0], [0.0, 1.0]]),
        ("transpose", lambda c: S.matrix_operation([[1, 2], [3, 4]], "transpose", ctx=c),
         "result", [[1.0, 3.0], [2.0, 4.0]]),
        ("singular determinant is 0",
         lambda c: S.matrix_operation([[1, 2], [2, 4]], "determinant", ctx=c),
         "result", approx(0.0)),
    ],
    "number_theory_operation": [
        ("is_prime", lambda c: S.number_theory_operation("is_prime", 7, ctx=c), "result", True),
        ("is_prime composite", lambda c: S.number_theory_operation("is_prime", 9, ctx=c),
         "result", False),
        ("factor_integer", lambda c: S.number_theory_operation("factor_integer", 360, ctx=c),
         "result", "2^3 * 3^2 * 5"),
        ("next_prime", lambda c: S.number_theory_operation("next_prime", 100, ctx=c),
         "result", 101),
        ("gcd", lambda c: S.number_theory_operation("gcd", 12, 18, ctx=c), "result", 6),
        ("lcm", lambda c: S.number_theory_operation("lcm", 4, 6, ctx=c), "result", 12),
    ],
    "combinatorics_operation": [
        ("binomial", lambda c: S.combinatorics_operation("binomial", 10, 3, ctx=c), "result", 120),
        ("permutations", lambda c: S.combinatorics_operation("permutations", 5, ctx=c),
         "result", 120),
        ("combinations", lambda c: S.combinatorics_operation("combinations", 5, 2, ctx=c),
         "result", 10),
        ("partitions", lambda c: S.combinatorics_operation("partitions", 5, ctx=c), "result", 7),
        ("factorial", lambda c: S.combinatorics_operation("factorial", 6, ctx=c), "result", 720),
        ("catalan", lambda c: S.combinatorics_operation("catalan", 5, ctx=c), "result", 42),
        ("fibonacci", lambda c: S.combinatorics_operation("fibonacci", 10, ctx=c), "result", 55),
        ("bell", lambda c: S.combinatorics_operation("bell", 5, ctx=c), "result", 52),
    ],
    "statistics_summary": [
        ("mean", lambda c: S.statistics_summary([1, 2, 3, 4, 5], ctx=c), "mean", approx(3.0)),
        ("median", lambda c: S.statistics_summary([1, 2, 3, 4, 5], ctx=c), "median", approx(3.0)),
        ("population variance", lambda c: S.statistics_summary([1, 2, 3, 4, 5], ctx=c),
         "population_variance", approx(2.0)),
        ("sample variance", lambda c: S.statistics_summary([1, 2, 3, 4, 5], ctx=c),
         "sample_variance", approx(2.5)),
    ],
    "distribution_operation": [
        # doc: [0, 1] for standard normal
        ("doc:standard normal pdf at 0",
         lambda c: S.distribution_operation("normal", [0, 1], "pdf", x=0.0, ctx=c),
         "result", approx(1 / math.sqrt(2 * math.pi))),
        ("doc:standard normal cdf at 0",
         lambda c: S.distribution_operation("normal", [0, 1], "cdf", x=0.0, ctx=c),
         "result", approx(0.5)),
        # Regression: "mean" used to return a random sample.
        ("standard normal mean is 0",
         lambda c: S.distribution_operation("normal", [0, 1], "mean", ctx=c),
         "result", approx(0.0)),
        # Regression: "variance" used to be hardcoded None.
        ("standard normal variance is 1",
         lambda c: S.distribution_operation("normal", [0, 1], "variance", ctx=c),
         "result", approx(1.0)),
        # Regression: mu was ignored and sigma was dropped unless len == 1.
        ("normal [5,2] mean honours mu",
         lambda c: S.distribution_operation("normal", [5, 2], "mean", ctx=c),
         "result", approx(5.0)),
        ("normal [5,2] variance honours sigma",
         lambda c: S.distribution_operation("normal", [5, 2], "variance", ctx=c),
         "result", approx(4.0)),
        ("normal [5,2] pdf peaks at mu",
         lambda c: S.distribution_operation("normal", [5, 2], "pdf", x=5.0, ctx=c),
         "result", approx(1 / (2 * math.sqrt(2 * math.pi)))),
        ("uniform [0,10] mean",
         lambda c: S.distribution_operation("uniform", [0, 10], "mean", ctx=c),
         "result", approx(5.0)),
        ("uniform [0,10] variance",
         lambda c: S.distribution_operation("uniform", [0, 10], "variance", ctx=c),
         "result", approx(100 / 12)),
        ("uniform cdf at midpoint",
         lambda c: S.distribution_operation("uniform", [0, 1], "cdf", x=0.5, ctx=c),
         "result", approx(0.5)),
        ("exponential pdf at 1",
         lambda c: S.distribution_operation("exponential", [1], "pdf", x=1.0, ctx=c),
         "result", approx(math.exp(-1))),
        ("exponential mean",
         lambda c: S.distribution_operation("exponential", [2], "mean", ctx=c),
         "result", approx(2.0)),
        ("poisson pdf",
         lambda c: S.distribution_operation("poisson", [3], "pdf", x=2.0, ctx=c),
         "result", approx(math.exp(-3) * 9 / 2)),
        ("poisson mean equals lambda",
         lambda c: S.distribution_operation("poisson", [3], "mean", ctx=c),
         "result", approx(3.0)),
        ("chi_squared mean equals k",
         lambda c: S.distribution_operation("chi_squared", [4], "mean", ctx=c),
         "result", approx(4.0)),
        ("chi_squared variance is 2k",
         lambda c: S.distribution_operation("chi_squared", [4], "variance", ctx=c),
         "result", approx(8.0)),
    ],
    "vector_calculus_operation": [
        # doc: variables ['x', 'y', 'z']
        ("gradient", lambda c: S.vector_calculus_operation("gradient", "x^2 + y^2", ["x", "y"],
                                                           ctx=c),
         "result", ["2*x", "2*y"]),
        ("divergence", lambda c: S.vector_calculus_operation("divergence", ["x", "y", "z"],
                                                             ["x", "y", "z"], ctx=c),
         "result", "3"),
        ("curl of rotation field",
         lambda c: S.vector_calculus_operation("curl", ["-y", "x", "0"], ["x", "y", "z"], ctx=c),
         "result", ["0", "0", "2"]),
        ("laplacian", lambda c: S.vector_calculus_operation("laplacian", "x^2 + y^2", ["x", "y"],
                                                            ctx=c),
         "result", "4"),
    ],
    "graph_operation": [
        # doc: named graph 'PetersenGraph'
        ("doc:petersen order", lambda c: S.graph_operation("PetersenGraph", "order", ctx=c),
         "result", 10),
        ("doc:petersen size", lambda c: S.graph_operation("PetersenGraph", "size", ctx=c),
         "result", 15),
        ("petersen chromatic number",
         lambda c: S.graph_operation("PetersenGraph", "chromatic_number", ctx=c), "result", 3),
        ("petersen is connected",
         lambda c: S.graph_operation("PetersenGraph", "is_connected", ctx=c), "result", True),
        ("petersen is not planar",
         lambda c: S.graph_operation("PetersenGraph", "is_planar", ctx=c), "result", False),
        ("petersen diameter", lambda c: S.graph_operation("PetersenGraph", "diameter", ctx=c),
         "result", 2),
        ("petersen is 3-regular",
         lambda c: S.graph_operation("PetersenGraph", "degree_sequence", ctx=c),
         "result", [3] * 10),
        # doc: adjacency dict '{0:[1,2], 1:[0,2], 2:[0,1]}'
        ("doc:adjacency dict",
         lambda c: S.graph_operation("{0:[1,2], 1:[0,2], 2:[0,1]}", "order", ctx=c), "result", 3),
    ],
    "group_operation": [
        # doc: 'SymmetricGroup(5)'
        ("doc:S5 order is 120", lambda c: S.group_operation("SymmetricGroup(5)", "order", ctx=c),
         "result", 120),
        # doc: 'DihedralGroup(4)'
        ("doc:D4 order is 8", lambda c: S.group_operation("DihedralGroup(4)", "order", ctx=c),
         "result", 8),
        # doc: 'CyclicPermutationGroup(6)'
        ("doc:C6 is cyclic",
         lambda c: S.group_operation("CyclicPermutationGroup(6)", "is_cyclic", ctx=c),
         "result", True),
        ("S3 is not abelian",
         lambda c: S.group_operation("SymmetricGroup(3)", "is_abelian", ctx=c), "result", False),
        ("D4 centre has order 2",
         lambda c: S.group_operation("DihedralGroup(4)", "center_order", ctx=c), "result", 2),
        ("S4 has 5 conjugacy classes",
         lambda c: S.group_operation("SymmetricGroup(4)", "conjugacy_classes_count", ctx=c),
         "result", 5),
        ("C6 exponent is 6",
         lambda c: S.group_operation("CyclicPermutationGroup(6)", "exponent", ctx=c), "result", 6),
        # doc: 'AlternatingGroup(5)' -- order 5!/2, and the smallest
        # non-abelian simple group, so its centre is trivial.
        ("doc:A5 order is 60",
         lambda c: S.group_operation("AlternatingGroup(5)", "order", ctx=c), "result", 60),
        ("A5 is not abelian",
         lambda c: S.group_operation("AlternatingGroup(5)", "is_abelian", ctx=c), "result", False),
    ],
    "elliptic_curve_operation": [
        # doc: short Weierstrass [a, b] for y^2 = x^3 + a*x + b
        ("doc:short form discriminant",
         lambda c: S.elliptic_curve_operation([0, -1], "discriminant", ctx=c), "result", "-432"),
        ("j-invariant is 0 when a=0",
         lambda c: S.elliptic_curve_operation([0, -1], "j_invariant", ctx=c), "result", "0"),
        ("rank", lambda c: S.elliptic_curve_operation([0, -1], "rank", ctx=c), "result", 0),
        ("torsion order", lambda c: S.elliptic_curve_operation([0, -1], "torsion_order", ctx=c),
         "result", 2),
        ("conductor", lambda c: S.elliptic_curve_operation([0, -1], "conductor", ctx=c),
         "result", 144),
        # doc: [a1,a2,a3,a4,a6] -- curve 37a, the smallest conductor of rank 1
        ("doc:long form rank",
         lambda c: S.elliptic_curve_operation([0, 0, 1, -1, 0], "rank", ctx=c), "result", 1),
        ("curve 37a conductor",
         lambda c: S.elliptic_curve_operation([0, 0, 1, -1, 0], "conductor", ctx=c), "result", 37),
    ],
    "coding_theory_operation": [
        # doc: 'HammingCode(GF(2),3)' -- the [7,4,3] Hamming code
        ("doc:hamming length", lambda c: S.coding_theory_operation("HammingCode(GF(2),3)",
                                                                   "length", ctx=c), "result", 7),
        ("doc:hamming dimension", lambda c: S.coding_theory_operation("HammingCode(GF(2),3)",
                                                                      "dimension", ctx=c),
         "result", 4),
        ("hamming minimum distance",
         lambda c: S.coding_theory_operation("HammingCode(GF(2),3)", "minimum_distance", ctx=c),
         "result", 3),
        ("hamming rate is 4/7",
         lambda c: S.coding_theory_operation("HammingCode(GF(2),3)", "rate", ctx=c),
         "result", approx(4 / 7)),
        # doc: 'GeneralizedReedSolomonCode(GF(7).list()[:6],3)'
        ("doc:reed-solomon length",
         lambda c: S.coding_theory_operation("GeneralizedReedSolomonCode(GF(7).list()[:6],3)",
                                             "length", ctx=c), "result", 6),
        ("reed-solomon dimension",
         lambda c: S.coding_theory_operation("GeneralizedReedSolomonCode(GF(7).list()[:6],3)",
                                             "dimension", ctx=c), "result", 3),
    ],
    "boolean_algebra_operation": [
        # doc: 'x*y + x*z + y*z'. This spelling used to fail with
        # "name 'x' is not defined" because the ring generators are x0, x1, x2.
        ("doc:majority function variables",
         lambda c: S.boolean_algebra_operation("x*y + x*z + y*z", "variables", num_variables=3,
                                               ctx=c),
         "result", ["x0", "x1", "x2"]),
        ("doc:majority function degree",
         lambda c: S.boolean_algebra_operation("x*y + x*z + y*z", "degree", num_variables=3,
                                               ctx=c),
         "result", 2),
        ("doc:majority function is not zero",
         lambda c: S.boolean_algebra_operation("x*y + x*z + y*z", "is_zero", num_variables=3,
                                               ctx=c),
         "result", False),
        # The generator spelling must keep working alongside the documented one.
        ("generator spelling still parses",
         lambda c: S.boolean_algebra_operation("x0*x1 + x0*x2 + x1*x2", "degree",
                                               num_variables=3, ctx=c),
         "result", 2),
        ("x + x cancels over GF(2)",
         lambda c: S.boolean_algebra_operation("x + x", "is_zero", num_variables=2, ctx=c),
         "result", True),
    ],
    "polynomial_ring_operation": [
        # doc: ring_vars ['a','b','c'], polynomials ['a^2+b', 'b^2-1']
        ("doc:groebner basis",
         lambda c: S.polynomial_ring_operation(["a", "b", "c"], ["a^2+b", "b^2-1"],
                                               "groebner_basis", ctx=c),
         "result", ["a^2 + b", "b^2 - 1"]),
        ("doc:ideal dimension",
         lambda c: S.polynomial_ring_operation(["a", "b", "c"], ["a^2+b", "b^2-1"],
                                               "ideal_dimension", ctx=c),
         "result", 1),
        ("doc:is groebner",
         lambda c: S.polynomial_ring_operation(["a", "b", "c"], ["a^2+b", "b^2-1"],
                                               "is_groebner", ctx=c),
         "result", True),
    ],
    "geometry_operation": [
        # Regression: this used "^" inside generated Python, where it is XOR,
        # so the 3-4-5 triangle produced a complex number instead of 5.
        ("3-4-5 triangle distance",
         lambda c: S.geometry_operation("distance", [[0, 0], [3, 4]], ctx=c),
         "result", approx(5.0)),
        ("unit distance along an axis",
         lambda c: S.geometry_operation("distance", [[0, 0, 0], [0, 0, 1]], ctx=c),
         "result", approx(1.0)),
        ("rectangle area",
         lambda c: S.geometry_operation("polygon_area", [[0, 0], [4, 0], [4, 3], [0, 3]], ctx=c),
         "result", approx(12.0)),
        ("unit tetrahedron volume",
         lambda c: S.geometry_operation("polytope_volume",
                                        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], ctx=c),
         "result", approx(1 / 6)),
        ("square is convex",
         lambda c: S.geometry_operation("is_convex", [[0, 0], [1, 0], [1, 1], [0, 1]], ctx=c),
         "result", True),
        ("interior point is not a hull vertex",
         lambda c: S.geometry_operation("convex_hull_vertices",
                                        [[0, 0], [1, 0], [0, 1], [1, 1], [0.5, 0.5]], ctx=c),
         "result", lambda v: len(v) == 4),
    ],
    "plot_expression": [
        # A PNG payload starts with the base64 of the PNG magic bytes.
        ("doc:sin renders a png",
         lambda c: S.plot_expression("sin(x)", "x", -3.14, 3.14, ctx=c),
         "image_base64", contains("iVBORw0KGgo")),
    ],
    "plot_multi_expression": [
        # doc: ['sin(x)', 'cos(x)']
        ("doc:two curves render a png",
         lambda c: S.plot_multi_expression(["sin(x)", "cos(x)"], ctx=c),
         "image_base64", contains("iVBORw0KGgo")),
    ],
}


@requires_sage
@pytest.mark.asyncio
@pytest.mark.parametrize("tool", sorted(GROUPS), ids=sorted(GROUPS))
async def test_documented_examples(monkeypatch, tool):
    """Run every documented example for one tool and report all failures."""

    settings = SageSettings(force_python_worker=False, eval_timeout=120.0)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)

    failures: list[str] = []
    try:
        for case_id, factory, key, expected in GROUPS[tool]:
            ctx = FakeContext(f"examples-{tool}")
            try:
                result = await factory(ctx)
            except Exception as exc:  # report every failure, do not abort the group
                failures.append(f"{case_id}: raised {type(exc).__name__}: {exc}")
                continue
            if key not in result:
                failures.append(f"{case_id}: result has no key {key!r}; got {result!r}")
                continue
            actual = result[key]
            if not _matches(expected, actual):
                wanted = getattr(expected, "__name__", repr(expected))
                failures.append(f"{case_id}: expected {wanted}, got {actual!r}")
    finally:
        await manager.shutdown()

    assert not failures, f"{tool}: {len(failures)} case(s) failed\n" + "\n".join(
        f"  - {failure}" for failure in failures
    )


@requires_sage
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "expression"),
    [
        # doc: 'sin(x)*cos(y)'
        ("doc:sin*cos", "sin(x)*cos(y)"),
        ("paraboloid", "x^2 + y^2"),
        # Singular and partly complex surfaces must render with gaps rather
        # than failing the whole plot.
        ("singular at the axes", "1/(x*y)"),
        ("complex for x < 0", "sqrt(x)"),
        # Degenerate inputs: no variables, and only one of the two.
        ("constant", "1"),
        ("single variable", "x"),
    ],
)
async def test_plot3d_expression_renders_png(monkeypatch, label, expression):
    """plot3d_expression must return a PNG payload.

    This previously failed for every input: Graphics3d.save()/save_image()
    require a filesystem path and reject a BytesIO, there is no .matplotlib()
    figure on a Graphics3d, and a temp file is unreachable from the sandbox.
    It now samples the surface and renders through matplotlib's 3D axes.
    """

    settings = SageSettings(force_python_worker=False, eval_timeout=120.0)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    ctx = FakeContext("examples-plot3d")

    try:
        result = await S.plot3d_expression(expression, ctx=ctx)
        assert result["format"] == "png"
        payload = result["image_base64"]
        # Base64 of the PNG magic bytes.
        assert payload.startswith("iVBORw0KGgo"), f"{label}: not a PNG payload"
        assert len(payload) > 1000, f"{label}: payload suspiciously small"
    finally:
        await manager.shutdown()
