"""The numerical sessions, where the answer a model *remembers* is wrong.

``test_research_workflows.py`` covers exact mathematics: integers, primes,
elliptic curves. Everything there is right or it is not. This file covers the
other half of what mathematicians and physicists bring to an LLM -- **floating
point** -- and it is the half where the model on its own is not merely imprecise
but confidently, reproducibly wrong:

* it will apply the quadratic formula and report a small root that is 25% off,
* it will "solve" a 12x12 Hilbert system and report numbers with no correct
  digit at all,
* it will integrate a stiff system with an explicit step and report the values
  the recurrence produced before it overflowed,
* it will quote a quadrature routine's error estimate as the accuracy of the
  answer, when the routine was integrating over the wrong domain.

None of that is fixed by a bigger model, because none of it is a knowledge gap.
It is fixed by running the computation, which is what this server is for. Each
test below is one sitting: pose the problem the way it arrives in real work,
compute it the naive way, compute it a way that is trustworthy, and assert that
the two differ by the amount the theory predicts.

The assertions prefer invariants that carry their own justification -- a
second-order method's error must fall by four when the grid halves, an exactly
conserved quantity must stay conserved, Newton's error must square -- over
constants anyone would have to look up. Where a constant does appear it is
standard (pi^4/15, the Hilbert inverse being integral).
"""

from __future__ import annotations

import shutil

import pytest

from sagemath_mcp import runtime, server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.session import SageSessionManager

from .conftest import FakeContext

requires_sage = pytest.mark.skipif(
    shutil.which("sage") is None, reason="Sage executable not available"
)


@pytest.fixture
def numericist(monkeypatch):
    """One Sage session held across a whole workflow, as a person would."""
    manager = SageSessionManager(SageSettings(force_python_worker=False, eval_timeout=180.0))
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    return manager


async def _run(ctx, code: str) -> str:
    """One step of a session. Returns the printed result."""
    result = await server.evaluate_sage(code, ctx=ctx)
    return result.result or ""


def _floats(text: str) -> list[float]:
    """Parse a printed Sage list of numbers."""
    return [float(part) for part in text.strip().strip("()[]").split(",") if part.strip()]


# --- catastrophic cancellation ------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_the_quadratic_formula_loses_the_small_root(numericist) -> None:
    """x^2 + 1e8 x + 1 = 0, which is where every numerical analysis course opens.

    The roots are about -1e8 and -1e-8. The textbook formula computes the small
    one as (-b + sqrt(b^2 - 4ac))/2a, and in double precision that subtracts two
    numbers agreeing in their first sixteen digits: the answer that comes back
    has *no* correct digits. This is the single most common way an LLM's
    arithmetic goes wrong on a physically ordinary problem -- the formula is
    right, the recipe is right, and the answer is 25% off.

    A session fixes it two ways at once, and both are worth having: rearrange to
    the numerically stable form, and compute a reference at 200 bits so the
    error can be *measured* rather than argued about.
    """
    ctx = FakeContext("cancellation")

    await _run(ctx, "a = 1.0\nb = 1e8\nc = 1.0")

    naive = float(await _run(ctx, "naive = (-b + sqrt(b^2 - 4*a*c))/(2*a)\nnaive"))
    stable = float(await _run(ctx, "stable = (2*c)/(-b - sqrt(b^2 - 4*a*c))\nstable"))

    # 200 bits of precision, which is the arbiter neither form gets to argue with.
    await _run(ctx, "R = RealField(200)\nexact = (-R(b) + sqrt(R(b)^2 - 4*R(a)*R(c)))/(2*R(a))")

    assert await _run(ctx, "bool(abs(stable - exact)/abs(exact) < 1e-15)") == "True"
    assert await _run(ctx, "bool(abs(naive - exact)/abs(exact) > 1e-9)") == "True"

    # Concretely: the naive root is wrong in its first significant figure.
    assert abs(stable - naive) / abs(stable) > 0.1, (naive, stable)

    # Both forms are algebraically the same expression -- the difference is
    # entirely arithmetic. Vieta says the product of the roots is c/a = 1.
    assert await _run(ctx, "bool(abs(stable * (-b - stable) - 1) < 1e-6)") == "True"


# --- conditioning -------------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_a_hilbert_system_has_no_correct_digits_in_double_precision(numericist) -> None:
    """Fitting a polynomial in the monomial basis, which is how this is met in the wild.

    H_ij = 1/(i+j+1) is exactly the normal-equation matrix of a least-squares
    polynomial fit on [0,1], so this is not a contrived example: it is what
    happens when someone fits a degree-11 polynomial to data the obvious way.
    The condition number passes 1e16 at n=12, which is the reciprocal of double
    precision's epsilon -- so the computed solution is not merely inaccurate, it
    shares no significant digit with the truth.

    Sage can do what a model cannot: solve the same system exactly over the
    rationals and put a number on the damage.
    """
    ctx = FakeContext("hilbert")

    await _run(ctx, "n = 12\nHq = matrix(QQ, n, n, lambda i, j: 1/(i+j+1))\nb = vector(QQ, [1]*n)")
    await _run(ctx, "xq = Hq.solve_right(b)")

    # The inverse of a Hilbert matrix is integral, so the exact solution is a
    # vector of integers. That is a check on the exact solve that needs no table.
    assert await _run(ctx, "all(v in ZZ for v in xq)") == "True"

    await _run(ctx, "Hd = matrix(RDF, n, n, lambda i, j: 1.0/(i+j+1))")
    await _run(ctx, "xd = Hd.solve_right(vector(RDF, [1.0]*n))")

    kappa = float(await _run(ctx, "kappa = Hd.condition()\nkappa"))
    assert kappa > 1e15, kappa

    # Not "inaccurate": wrong. The largest exact entry is order 1e10 and the
    # double-precision answer misses it by a comparable amount.
    relative = float(await _run(
        ctx,
        "max(abs(float(xd[i]) - float(xq[i])) for i in range(n))/max(abs(float(v)) for v in xq)",
    ))
    assert relative > 1e-4, relative

    # And the classic rule of thumb holds: about log10(kappa) digits are gone,
    # out of the ~16 double precision ever had.
    assert await _run(ctx, "bool(log(kappa, 10) > 15)") == "True"

    # The residual, meanwhile, looks *fine*. Anyone checking their work by
    # ||Hx - b|| would conclude the double-precision solve had succeeded, which
    # is why conditioning has to be computed rather than eyeballed.
    residual = float(await _run(ctx, "(Hd*xd - vector(RDF, [1.0]*n)).norm()"))
    assert residual < 1e-6, residual
    # Nine orders between "the residual is small" and "the answer is right".
    assert residual < relative * 1e-3, (residual, relative)


# --- Newton's method ----------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_newtons_method_on_keplers_equation_converges_quadratically(numericist) -> None:
    """M = E - e sin E: where a satellite is at time t. Solved a few billion times a day.

    Kepler's equation has no closed form, so every orbit propagator iterates it.
    The property worth asserting is not the root -- it is the *rate*: Newton
    doubles the number of correct digits per step, so the error ratio
    e_{k+1}/e_k^2 stays bounded while the error itself falls from 1e-1 to 1e-15
    in four steps. A model that reports "the answer converged" has asserted
    nothing; this measures it.

    Uses `f(E) = ...`, Sage's own function-definition syntax and the first thing
    in its tutorial, which this server refused until the preparser's `__tmp__`
    was allowed through.
    """
    ctx = FakeContext("newton")

    await _run(ctx, "M0 = 0.75\necc = 0.6\nf(E) = E - ecc*sin(E) - M0")

    # The bracketing solver, as the independent answer.
    root = float(await _run(ctx, "root = find_root(f, 0, 3)\nroot"))
    assert 1.3 < root < 1.4, root

    await _run(ctx, (
        "def newton(E0, steps):\n"
        "    seq = [E0]\n"
        "    E = E0\n"
        "    for _ in range(steps):\n"
        "        E = E - (E - ecc*sin(E) - M0)/(1 - ecc*cos(E))\n"
        "        seq.append(E)\n"
        "    return seq\n"
        "seq = newton(M0, 5)"
    ))

    errors = _floats(await _run(ctx, "[float(abs(v - root)) for v in seq]"))
    assert errors[0] > 0.1, errors
    assert errors[-1] < 1e-14, errors
    assert all(errors[i + 1] < errors[i] for i in range(len(errors) - 1)), errors

    # Quadratic convergence: e_{k+1} <= C e_k^2 with C of order one, for as long
    # as the error is above the arithmetic's noise floor.
    ratios = [errors[i + 1] / errors[i] ** 2 for i in range(3)]
    assert all(0.05 < r < 5 for r in ratios), ratios

    # Both methods land in the same place, and the residual is at rounding.
    assert abs(float(await _run(ctx, "float(seq[-1])")) - root) < 1e-12
    assert await _run(ctx, "bool(abs(f(root)) < 1e-12)") == "True"


# --- order of accuracy --------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_the_finite_difference_laplacian_is_second_order(numericist) -> None:
    """Halve the grid, quarter the error -- or the discretisation is not what you think.

    This is the acceptance test for any finite-difference code, and it is
    exactly the check a model cannot perform by reasoning: the claim "this
    scheme is second-order accurate" is a statement about two runs at two
    resolutions, not about the source.

    The problem is the quantum harmonic oscillator's ground state, whose energy
    is exactly 1/2, so the error is known and not merely estimated.
    """
    ctx = FakeContext("order")

    await _run(ctx, (
        "def ground_energy(N, L=16.0):\n"
        "    dx = L/N\n"
        "    xs = [-L/2 + i*dx for i in range(N)]\n"
        "    H = matrix(RDF, N, N)\n"
        "    for i in range(N):\n"
        "        H[i,i] = 1/dx^2 + 0.5*xs[i]^2\n"
        "        if i > 0:\n"
        "            H[i,i-1] = -0.5/dx^2\n"
        "        if i < N-1:\n"
        "            H[i,i+1] = -0.5/dx^2\n"
        "    return min(H.eigenvalues())\n"
    ))

    coarse = float(await _run(ctx, "e1 = float(ground_energy(100))\ne1"))
    fine = float(await _run(ctx, "e2 = float(ground_energy(200))\ne2"))

    # Both are near 1/2, and the finer one is nearer.
    assert abs(coarse - 0.5) < 1e-2, coarse
    assert abs(fine - 0.5) < abs(coarse - 0.5)

    ratio = abs(coarse - 0.5) / abs(fine - 0.5)
    assert 3.5 < ratio < 4.5, f"expected second order (ratio 4), measured {ratio}"

    # Richardson: (4*e2 - e1)/3 cancels the leading error term, and lands two
    # orders of magnitude closer than either run it was built from.
    richardson = float(await _run(ctx, "(4*e2 - e1)/3"))
    assert abs(richardson - 0.5) < abs(fine - 0.5) / 10, richardson


# --- stability ----------------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_the_explicit_heat_solver_blows_up_past_the_cfl_limit(numericist) -> None:
    """u_t = u_xx by forward Euler. Stable at r = 0.4, catastrophic at r = 0.6.

    The stability condition r = dt/dx^2 <= 1/2 is the most-quoted inequality in
    numerical PDEs, and quoting it is not the same as being bounded by it. Below
    the limit the computed decay matches exp(-pi^2 t) to the truncation error;
    above it, the highest grid mode is amplified by |1 - 4r| every step and the
    solution reaches 1e11 while the code raises nothing at all.

    The unstable run is seeded with an explicit sawtooth rather than left to
    rounding error, so the blow-up is deterministic instead of depending on
    which digit the hardware happened to drop.
    """
    ctx = FakeContext("cfl")

    await _run(ctx, (
        "M = 41\ndx = 1.0/(M - 1)\n"
        "def march(u, r, steps):\n"
        "    for _ in range(steps):\n"
        "        u = ([0.0]\n"
        "             + [u[i] + r*(u[i+1] - 2*u[i] + u[i-1]) for i in range(1, len(u)-1)]\n"
        "             + [0.0])\n"
        "    return u\n"
        "smooth = [float(sin(pi*i*dx)) for i in range(M)]"
    ))

    # r = 0.4: 200 steps, and the answer is the analytic decay of the first mode.
    await _run(ctx, "r = 0.4\ndt = r*dx^2\nstable = march(smooth, r, 200)")
    stable_peak = float(await _run(ctx, "max(stable)"))
    analytic = float(await _run(ctx, "float(exp(-pi^2*200*dt))"))
    assert abs(stable_peak - analytic) / analytic < 1e-2, (stable_peak, analytic)

    # The discrepancy that remains is the scheme's own truncation error, which
    # the second-order test above already characterised -- not instability.
    assert abs(stable_peak - analytic) / analytic > 1e-6, (stable_peak, analytic)

    # r = 0.6: same code, same initial data plus a sawtooth at the grid scale.
    await _run(ctx, "seeded = [smooth[i] + 1e-12*(-1)^i for i in range(M)]")
    await _run(ctx, "unstable = march(seeded, 0.6, 200)")
    unstable_peak = float(await _run(ctx, "max(abs(v) for v in unstable)"))

    assert unstable_peak > 1e6, unstable_peak
    # And it is the grid-scale mode that ran away: neighbouring points have
    # opposite signs, the signature of the (-1)^i eigenvector.
    assert await _run(ctx, "unstable[20]*unstable[21] < 0") == "True"

    # The growth rate is the one the amplification factor predicts, |1-4r|^n,
    # which is what makes this a diagnosis rather than an observation.
    predicted = float(await _run(ctx, "float(1e-12*abs(1 - 4*0.6)^200)"))
    assert 0.01 < unstable_peak / predicted < 100, (unstable_peak, predicted)


@requires_sage
@pytest.mark.asyncio
async def test_a_stiff_system_defeats_the_explicit_step(numericist) -> None:
    """Robertson's kinetics: the standard stiff test problem, from real chemistry.

    Three reactions whose rate constants span nine orders of magnitude. The
    explicit step that "looks fine" -- dt = 0.1 against a system that relaxes in
    1e-7 -- does not merely lose accuracy: it produces NaN, having passed
    through numbers no concentration can take. The implicit solver holds mass
    conservation to 1e-13 over the same interval.

    Mass conservation is the assertion because it needs no reference solution:
    y1 + y2 + y3 = 1 exactly, for all time, by construction of the reactions.
    """
    ctx = FakeContext("stiff")

    await _run(ctx, (
        "y1, y2, y3 = var('y1 y2 y3')\n"
        "rhs = [-0.04*y1 + 1e4*y2*y3,\n"
        "       0.04*y1 - 1e4*y2*y3 - 3e7*y2^2,\n"
        "       3e7*y2^2]\n"
        "ts = srange(0, 40, 0.01)\n"
        "sol = desolve_odeint(rhs, [1, 0, 0], ts, [y1, y2, y3])"
    ))

    drift = float(await _run(ctx, "max(abs(float(r[0] + r[1] + r[2]) - 1.0) for r in sol)"))
    assert drift < 1e-9, drift

    # Every concentration stays in [0, 1], which no wrong answer here does.
    assert await _run(ctx, "all(-1e-9 <= float(v) <= 1 + 1e-9 for r in sol for v in r)") == "True"

    # The slow species really has decayed -- this is not a solver that stood still.
    final = float(await _run(ctx, "float(sol[-1][0])"))
    assert 0.6 < final < 0.8, final

    # The same system, forward Euler, dt = 0.1: the step is 1e6 times the
    # fastest timescale, and the recurrence diverges.
    await _run(ctx, (
        "def euler(state, dt, steps):\n"
        "    a, b, c = state\n"
        "    for _ in range(steps):\n"
        "        a, b, c = (a + dt*(-0.04*a + 1e4*b*c),\n"
        "                   b + dt*(0.04*a - 1e4*b*c - 3e7*b^2),\n"
        "                   c + dt*(3e7*b^2))\n"
        "    return [a, b, c]\n"
        "blown = euler([1.0, 0.0, 0.0], 0.1, 400)"
    ))

    # NaN compares false against everything, so this catches both the overflow
    # and the NaN it decays into.
    assert await _run(ctx, "all(abs(v) < 10 for v in blown)") == "False"


# --- quadrature ---------------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_quadrature_error_estimates_do_not_cover_the_wrong_domain(numericist) -> None:
    """Three integrals, and the third one is a trap that catches careful people.

    The first two are hard for the integrand's sake -- an endpoint singularity,
    and the Bose-Einstein integral that gives the Stefan-Boltzmann constant --
    and the routine handles both. The third is hard for a reason no error
    estimate can see: integrating sin(x)/x over [0, 100] instead of [0, oo)
    returns an answer accurate to 1e-14 *for the integral that was asked*, and
    wrong in the third digit for the one that was meant.

    That is the failure mode worth a test. A model quoting "error 4e-14" as its
    accuracy is quoting a true number about the wrong question.
    """
    ctx = FakeContext("quadrature")

    # log(x)/sqrt(x) on [0,1]: singular at the endpoint, exactly -4.
    singular = _floats(await _run(ctx, "numerical_integral(lambda u: log(u)/sqrt(u), 0, 1)"))
    assert abs(singular[0] + 4.0) < 1e-6, singular

    # The Bose-Einstein integral: pi^4/15, to fourteen digits.
    planck = _floats(await _run(
        ctx, "numerical_integral(lambda u: u^3/(exp(u) - 1), 1e-12, 80)"
    ))
    exact = float(await _run(ctx, "float(pi^4/15)"))
    assert abs(planck[0] - exact) < 1e-9, (planck, exact)

    # And now the trap.
    truncated = _floats(await _run(ctx, "numerical_integral(sin(x)/x, 0, 100)"))
    value, estimate = truncated[0], truncated[1]
    half_pi = float(await _run(ctx, "float(pi/2)"))

    assert estimate < 1e-10, estimate                    # the routine is confident
    assert abs(value - half_pi) > 1e-3, (value, half_pi)  # and the answer is wrong
    # Wrong by the tail it was never given, which decays like 1/x: cos(100)/100.
    tail = float(await _run(ctx, "float(cos(100)/100)"))
    assert abs(abs(value - half_pi) - abs(tail)) < 5e-4, (value - half_pi, tail)
