import shutil

import pytest

from sagemath_mcp import runtime, server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.models import EvaluateResult
from sagemath_mcp.session import SageSessionManager

from .conftest import FakeContext

requires_sage = pytest.mark.skipif(
    shutil.which("sage") is None, reason="Sage executable not available"
)


@requires_sage
@pytest.mark.asyncio
async def test_use_cases_cover_manual_examples(monkeypatch):
    original_manager = runtime.SESSION_MANAGER
    settings = SageSettings()
    manager = SageSessionManager(settings)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)

    ctx = FakeContext("manual-use-cases")

    try:
        # Calculus: differentiation + integration
        deriv: EvaluateResult = await server.evaluate_sage(
            "var('x'); f = cos(x)**2; diff(f, x)",
            ctx=ctx,
        )
        assert "sin(x)" in deriv.result

        integral: EvaluateResult = await server.evaluate_sage(
            "integral(diff(cos(x)**2, x), x)",
            ctx=ctx,
        )
        assert "cos(x)^2" in integral.result

        # Rings and factorisation
        factor = await server.evaluate_sage(
            "var('x'); factor(x**3 - 2*x**2 - x + 2)",
            ctx=ctx,
        )
        assert {"(x - 2)", "(x - 1)", "(x + 1)"}.issubset(set(factor.result.split("*")))

        # Matrix algebra
        matrix_inverse = await server.evaluate_sage(
            "A = matrix(QQ,[[1,2],[3,5]]); A.inverse()",
            ctx=ctx,
        )
        assert "[ 3 -1]" in (matrix_inverse.result or "")

        product = await server.matrix_multiply([[1, 2], [3, 4]], [[5, 6], [7, 8]], ctx=ctx)
        assert product["product"][0][0] == 19.0

        # Series / sums
        series_sum = await server.evaluate_sage(
            "sum(n**2 for n in range(1, 11))",
            ctx=ctx,
        )
        assert series_sum.result == "385"

        # Statistics helper tool (pure Python)
        stats = await server.statistics_summary([1, 2, 3, 4, 5], ctx=ctx)
        assert stats["mean"] == pytest.approx(3.0)

        # Solve equation tool (linked to sage_eval)
        solutions = await server.solve_equation("x^2 - 4 = 0", ctx=ctx)
        assert "x == 2" in solutions["solutions"]

        # Ensure progress events were recorded
        assert ctx.progress_events
    finally:
        await manager.shutdown()
        runtime.SESSION_MANAGER = original_manager


@requires_sage
@pytest.mark.asyncio
async def test_use_cases_cover_the_sympy_mcp_showcase(monkeypatch):
    """sympy-mcp's own examples and test cases, translated to this server.

    sympy-mcp -- the most-starred symbolic MCP server -- demonstrates itself
    with a fixed set of workloads: polynomial and trigonometric derivatives,
    matrix determinants and eigenvalues, substitution, the damped harmonic
    oscillator, a coupled two-tank ODE system checked against its algebraic
    steady state, general relativity through predefined and custom metrics, and
    unit conversion (its tests/ and README, surveyed 2026-08-24). Every one is
    reachable here through `evaluate_sage` alone, in a single session whose
    state carries across calls -- no expression handles -- which is the
    architectural claim this test pins.

    The relativity cases double as the manifolds coverage the roadmap's
    field-survey item calls for: `Manifold` and the `manifolds` catalog are
    allowlisted, and this asserts the policy accepts the whole curvature
    workflow, not merely the names. Deliberately absent: sympy-mcp's LaTeX
    assertions, because `latex` is withheld here by design -- results come
    back as text.
    """
    original_manager = runtime.SESSION_MANAGER
    settings = SageSettings()
    manager = SageSessionManager(settings)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)

    ctx = FakeContext("sympy-mcp-showcase")

    try:
        # test_calculus: first, second and third derivative of x^3.
        derivs = await server.evaluate_sage(
            "x = var('x')\n[diff(x^3, x, k) for k in (1, 2, 3)]",
            ctx=ctx,
        )
        assert derivs.result == "[3*x^2, 6*x, 6]"

        # test_linalg: determinant and eigenvalues of its fixture matrices.
        det = await server.evaluate_sage("matrix(QQ, [[1, 2], [3, 4]]).det()", ctx=ctx)
        assert det.result == "-2"
        eigen = await server.evaluate_sage(
            "matrix(QQ, [[3, 1], [1, 3]]).eigenvalues()", ctx=ctx
        )
        assert eigen.result == "[4, 2]"

        # test_linalg substitution -- `x` survives from the first call, which is
        # the session model sympy-mcp's expression handles stand in for.
        subs = await server.evaluate_sage(
            "y = var('y')\n(x^2 + y^2).subs(y=y + 1)", ctx=ctx
        )
        assert subs.result == "x^2 + (y + 1)^2"

        # README example 1: the damped harmonic oscillator (underdamped instance).
        oscillator = await server.evaluate_sage(
            "t = var('t')\n"
            "xf = function('x')(t)\n"
            "desolve(diff(xf, t, 2) + 2*diff(xf, t) + 5*xf == 0, xf, ivar=t)",
            ctx=ctx,
        )
        assert "cos(2*t)" in oscillator.result
        assert "e^(-t)" in oscillator.result

        # README example 3: the coupled two-tank system. The long-term limits of
        # the ODE solution must agree with the algebraic steady state.
        tanks = await server.evaluate_sage(
            "h1 = function('h1')(t)\n"
            "h2 = function('h2')(t)\n"
            "eqs = [diff(h1, t) == (1/2 - 3/10*(h1 - h2))/2,\n"
            "       diff(h2, t) == (3/10*(h1 - h2) - 3/10*h2)/1]\n"
            "sol = desolve_system(eqs, [h1, h2], ics=[0, 0, 0])\n"
            "[limit(s.rhs(), t=oo) for s in sol]",
            ctx=ctx,
        )
        assert tanks.result == "[10/3, 5/3]"
        steady = await server.evaluate_sage(
            "a, b = var('a b')\n"
            "solve([1/2 - 3/10*(a - b) == 0, 3/10*(a - b) - 3/10*b == 0], a, b)",
            ctx=ctx,
        )
        assert "a == (10/3)" in steady.result
        assert "b == (5/3)" in steady.result

        # test_relativity custom metric: flat 2D Lorentzian, vanishing curvature.
        flat = await server.evaluate_sage(
            "M = Manifold(2, 'M', structure='Lorentzian')\n"
            "X.<u,v> = M.chart()\n"
            "g = M.metric('g')\n"
            "g[0,0] = -1\n"
            "g[1,1] = 1\n"
            "g.ricci_scalar().expr()",
            ctx=ctx,
        )
        assert flat.result == "0"

        # README example 2 in two dimensions: constant negative scalar curvature
        # of the hyperbolic plane, the AdS analogue their AntiDeSitter case pins.
        hyperbolic = await server.evaluate_sage(
            "H = Manifold(2, 'H', structure='Riemannian')\n"
            "XH.<p,q> = H.chart('p q:(0,+oo)')\n"
            "gh = H.metric('gh')\n"
            "gh[0,0] = 1/q^2\n"
            "gh[1,1] = 1/q^2\n"
            "gh.ricci_scalar().expr()",
            ctx=ctx,
        )
        assert hyperbolic.result == "-2"

        # test_relativity predefined metric: a catalog manifold's curvature.
        sphere = await server.evaluate_sage(
            "S = manifolds.Sphere(2)\nS.induced_metric().ricci_scalar().expr()",
            ctx=ctx,
        )
        assert sphere.result == "2"

        # test_units: exact conversion (their speed_of_light case is a physics
        # constant Sage's units module does not carry; distance is the analogue).
        miles = await server.evaluate_sage(
            "units.length.mile.convert(units.length.kilometer)", ctx=ctx
        )
        assert miles.result == "25146/15625*kilometer"
    finally:
        await manager.shutdown()
        runtime.SESSION_MANAGER = original_manager
