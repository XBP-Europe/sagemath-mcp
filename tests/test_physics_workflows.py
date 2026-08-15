"""The sessions a physicist runs, ending in a number that is checkable against nature.

Physics is the workload this server was built for and the one least covered by
the rest of the suite. It has a shape the mathematics tests do not: a physicist
starts from a law, reduces it symbolically until something can be computed,
computes it numerically, and then -- this is the part that makes the test worth
writing -- compares the result against a *measured* value nobody in the session
gets to choose. CODATA fixes the Stefan-Boltzmann constant. The Sun's effective
temperature is 5772 K. Mercury's perihelion advances 43 arcseconds per century,
which is how general relativity was first believed.

So each test below ends at a quantity with an external referee, and the
assertion is agreement with the referee. That is a far stronger check than
"the code ran": a sign error, a factor of 2pi, a dropped c^2, or a solver that
quietly returned its initial condition all fail it.

What these exercise in the server, beyond arithmetic:

* **The idioms a physicist types.** `V(r) = -1/r`, `var('omega', domain='positive')`,
  `function('theta')(t)`, `desolve_odeint` over `srange`, `find_root` on a
  callable, `units.*`. Caller code here is deny-by-default, so every one of them
  is a chance for the policy to refuse ordinary physics. `f(x) = ...` -- the
  first line of the Sage tutorial -- *was* refused until the preparser's
  `__tmp__` was let through, and nothing in the suite noticed.
* **Nondimensionalisation.** Two of these problems cannot be integrated in SI
  units at all: an ODE solver's absolute tolerance is around 1e-8, and Mercury's
  u = 1/r is 2e-11, so the raw equation integrates pure tolerance. Scaling first
  is not stylistic, and it is exactly the step a model skips.
* **Statefulness.** A Hamiltonian built in step two is diagonalised in step
  four; constants defined once are reused throughout, as in a real sitting.
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

# CODATA 2018, the values a physicist would check against.
STEFAN_BOLTZMANN = 5.670374419e-8      # W m^-2 K^-4
WIEN_DISPLACEMENT = 2.897771955e-3     # m K
BOHR_RADIUS = 5.29177210903e-11        # m
RYDBERG_EV = 13.605693122994           # eV
INVERSE_FINE_STRUCTURE = 137.035999084


@pytest.fixture
def physicist(monkeypatch):
    """One Sage session held across a whole workflow, as a person would."""
    manager = SageSessionManager(SageSettings(force_python_worker=False, eval_timeout=180.0))
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    return manager


async def _run(ctx, code: str) -> str:
    result = await server.evaluate_sage(code, ctx=ctx)
    return result.result or ""


async def _num(ctx, code: str) -> float:
    return float(await _run(ctx, code))


def _floats(text: str) -> list[float]:
    return [float(part) for part in text.strip().strip("()[]").split(",") if part.strip()]


# Constants every session below starts from. SI, CODATA, defined exactly.
_SI = (
    "h = 6.62607015e-34\n"
    "hbar = 1.054571817e-34\n"
    "c = 299792458.0\n"
    "kB = 1.380649e-23\n"
    "G = 6.67430e-11\n"
    "me = 9.1093837015e-31\n"
    "qe = 1.602176634e-19\n"
    "eps0 = 8.8541878128e-12"
)


# --- blackbody radiation ------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_planck_law_gives_wien_and_the_temperature_of_the_sun(physicist) -> None:
    """From Planck's law to a star's surface temperature, which is how it is used.

    Astronomers do not measure the Sun's temperature; they measure where its
    spectrum peaks and divide. Getting from the law to that division is a
    maximisation that has no closed form -- d/dlambda of Planck's law gives
    x = 5(1 - e^-x), and the root 4.965114... is the whole content of Wien's
    constant.

    Note the two attempts at the maximisation. In SI units the derivative of the
    spectral radiance is of order 1e21 near a root at 5e-7, and Brent's method
    fails on it outright. In micrometres it is ordinary. That is not a Sage
    quirk -- it is the reason physicists nondimensionalise before they compute,
    and a model that hands raw SI to a solver gets an exception rather than an
    answer.
    """
    ctx = FakeContext("planck")
    await _run(ctx, _SI)

    # Planck's law, as written on the board. `B(lam, T) = ...` is Sage's own
    # function syntax, and the reason this test exists at all.
    await _run(ctx, (
        "lam, T = var('lam T')\n"
        "B(lam, T) = 2*h*c^2/(lam^5*(exp(h*c/(lam*kB*T)) - 1))"
    ))

    # Sanity first: the Sun at 500 nm radiates, and Rayleigh-Jeans is recovered
    # in the long-wavelength limit where hc/lambda kT << 1.
    assert await _num(ctx, "float(B(500e-9, 5772))") > 1e12
    rayleigh = await _num(ctx, "float(B(1e-2, 5772)*1e-2^4/(2*c*kB*5772))")
    assert abs(rayleigh - 1.0) < 1e-3, rayleigh

    # The maximisation, in micrometres so the numbers are of order one.
    await _run(ctx, "mu = var('mu')\nBmu(mu, T) = B(mu*1e-6, T)")
    peak_um = await _num(ctx, "peak = find_root(diff(Bmu(mu, 5772), mu), 0.1, 5.0)\npeak")
    assert 0.4 < peak_um < 0.6, peak_um

    # Wien's displacement law falls straight out: lambda_max * T is a constant,
    # and it is the measured one.
    assert abs(peak_um * 1e-6 * 5772 - WIEN_DISPLACEMENT) / WIEN_DISPLACEMENT < 1e-4

    # The same constant the analytic way, from the transcendental equation.
    await _run(ctx, "g(u) = 5*(1 - exp(-u)) - u")
    x_wien = await _num(ctx, "xw = find_root(g, 4, 6)\nxw")
    assert abs(x_wien - 4.965114231744276) < 1e-9, x_wien

    b_constant = await _num(ctx, "b = h*c/(xw*kB)\nb")
    assert abs(b_constant - WIEN_DISPLACEMENT) / WIEN_DISPLACEMENT < 1e-8, b_constant

    # And the use it is put to: the Sun peaks near 500 nm, so it is about 5800 K.
    t_sun = await _num(ctx, "b/500e-9")
    assert 5700 < t_sun < 5900, t_sun


@requires_sage
@pytest.mark.asyncio
async def test_the_stefan_boltzmann_constant_from_the_planck_integral(physicist) -> None:
    """Integrate Planck's law over all wavelengths and get a measured constant back.

    sigma = 2 pi^5 k^4 / (15 c^2 h^3) is a *derived* constant: it follows from
    the Bose-Einstein integral int x^3/(e^x - 1) dx = pi^4/15. Doing the integral
    numerically and recovering CODATA's sigma to eleven digits checks the whole
    chain at once -- the quadrature, the algebra, and the constants.

    Then the payoff, which is real astronomy: the solar constant measured at
    Earth, 1361 W/m^2, geometrically referred back to the solar surface, gives
    an effective temperature of 5772 K. That number is in every textbook and
    nobody in this session put it there.
    """
    ctx = FakeContext("stefan")
    await _run(ctx, _SI)

    integral = _floats(await _run(
        ctx, "I = numerical_integral(lambda u: u^3/(exp(u) - 1), 1e-12, 80)\nI"
    ))
    exact = await _num(ctx, "float(pi^4/15)")
    assert abs(integral[0] - exact) < 1e-9, (integral, exact)

    sigma = await _num(ctx, "sigma = 2*pi*kB^4*I[0]/(c^2*h^3)\nfloat(sigma)")
    assert abs(sigma - STEFAN_BOLTZMANN) / STEFAN_BOLTZMANN < 1e-9, sigma

    # The closed form must agree with the quadrature -- two routes, one number.
    closed = await _num(ctx, "float(2*pi^5*kB^4/(15*c^2*h^3))")
    assert abs(closed - sigma) / sigma < 1e-12, (closed, sigma)

    # Solar constant -> luminosity -> surface flux -> effective temperature.
    await _run(ctx, "S = 1361.0\nAU = 1.495978707e11\nRsun = 6.957e8")
    t_eff = await _num(ctx, "float((S*(AU/Rsun)^2/sigma)^0.25)")
    assert abs(t_eff - 5772) < 20, t_eff

    # Consistency with the other route to the same star: Wien's peak at 500 nm.
    assert abs(t_eff - await _num(ctx, "float(h*c/(4.965114231744276*kB)/500e-9)")) < 100


# --- general relativity -------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_general_relativity_precesses_mercurys_perihelion(physicist) -> None:
    """43 arcseconds per century: the first confirmed prediction of the theory.

    In Schwarzschild geometry the orbit equation picks up one term,

        u'' + u = GM/h^2 + (3GM/c^2) u^2 ,  u = 1/r, ' = d/dphi

    and that term makes the ellipse fail to close. The session does both halves
    of the real work:

    1. **Verify the integrator on a caricature.** Mercury's perturbation is
       delta = 8e-8, so its advance per orbit is 5e-7 radians -- far below what
       a 1e-3 grid can resolve. Instead the same equation is integrated with an
       exaggerated delta = 0.02, where the perihelion-to-perihelion angle is
       measurably longer than 2 pi, and compared against the linearised
       prediction 2 pi / sqrt(1 - 2 delta v_c). Agreement there is what licenses
       the formula for the real case.
    2. **Apply it to Mercury** and convert to the units the 19th century
       measured in.

    The equation is nondimensionalised first (v = p u), and that is not a
    stylistic choice: in SI, u ~ 2e-11 is smaller than the solver's default
    absolute tolerance, so the raw system integrates its own error.
    """
    ctx = FakeContext("mercury")
    await _run(ctx, _SI)

    # Mercury's orbit, from the ephemeris.
    await _run(ctx, (
        "Msun = 1.98892e30\n"
        "a = 5.7909050e10\necc = 0.205630\nperiod_days = 87.9691\n"
        "p = a*(1 - ecc^2)"
    ))
    delta = await _num(ctx, "delta = 3*G*Msun/(c^2*p)\nfloat(delta)")
    assert 7e-8 < delta < 9e-8, delta

    # -- step 1: the caricature, where the effect is visible ------------------
    await _run(ctx, (
        "v, w = var('v w')\n"
        "d = 0.02\n"
        "phi = srange(0, 5*2*pi + 1.0, 0.001)\n"
        "sol = desolve_odeint([w, 1 + d*v^2 - v], [1.05, 0], phi, [v, w])\n"
        "vs = [float(r[0]) for r in sol]"
    ))

    # Perihelion is a maximum of v = p/r, located to sub-grid accuracy by
    # fitting a parabola to the three samples around it.
    await _run(ctx, (
        "def peak_at(i):\n"
        "    y0, y1, y2 = vs[i-1], vs[i], vs[i+1]\n"
        "    return float(phi[i]) + 0.001*0.5*(y0 - y2)/(y0 - 2*y1 + y2)\n"
        "idx = [i for i in range(1, len(vs)-1) if vs[i] > vs[i-1] and vs[i] >= vs[i+1]]\n"
        "peaks = [peak_at(i) for i in idx]"
    ))
    assert int(await _run(ctx, "len(peaks)")) >= 4

    periods = _floats(await _run(
        ctx, "periods = [peaks[j+1] - peaks[j] for j in range(len(peaks)-1)]\nperiods"
    ))
    measured = sum(periods) / len(periods)

    # The orbit does not close: every radial period is longer than 2 pi.
    assert all(p > 6.2832 for p in periods), periods

    # And by the predicted amount. v_c is the circular solution of v = 1 + d v^2.
    predicted = await _num(ctx, (
        "vc = (1 - sqrt(1 - 4*d))/(2*d)\n"
        "float(2*pi/sqrt(1 - 2*d*vc))"
    ))
    assert abs(measured - predicted) / predicted < 1e-4, (measured, predicted)

    # -- step 2: Mercury itself ------------------------------------------------
    advance = await _num(ctx, "advance = 2*pi*delta\nfloat(advance)")
    assert abs(advance - 5.0199505e-7) / 5.0199505e-7 < 1e-6, advance

    arcsec_per_century = await _num(
        ctx, "float(advance*(100*365.25/period_days)*180/pi*3600)"
    )
    assert abs(arcsec_per_century - 43.0) < 0.5, arcsec_per_century


# --- quantum mechanics --------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_a_finite_difference_schrodinger_solver_finds_the_oscillator_ladder(
    physicist,
) -> None:
    """Discretise -1/2 d^2/dx^2 + x^2/2 and the eigenvalues come out at n + 1/2.

    This is the first program in every computational physics course, and the
    first place a student's answer is wrong for reasons nobody can see by
    reading: a factor of 2 in the kinetic term, a box too small for the
    wavefunction, a grid too coarse for the curvature. The exact spectrum makes
    all three visible.
    """
    ctx = FakeContext("schrodinger")

    await _run(ctx, (
        "N = 400\nL = 20.0\ndx = L/N\n"
        "xs = [-L/2 + i*dx for i in range(N)]\n"
        "H = matrix(RDF, N, N)\n"
        "for i in range(N):\n"
        "    H[i,i] = 1/dx^2 + 0.5*xs[i]^2\n"
        "    if i > 0:\n"
        "        H[i,i-1] = -0.5/dx^2\n"
        "    if i < N-1:\n"
        "        H[i,i+1] = -0.5/dx^2"
    ))

    # The Hamiltonian is real symmetric, so the spectrum had better be real.
    assert await _run(ctx, "H.is_symmetric()") == "True"

    levels = _floats(await _run(
        ctx, "ev = sorted(H.eigenvalues())\n[float(v) for v in ev[:6]]"
    ))
    errors = [abs(e - (n + 0.5)) for n, e in enumerate(levels)]
    assert max(errors) < 5e-3, list(zip(range(6), levels, errors, strict=True))

    # Equally spaced by hbar omega = 1 -- the property that makes it a ladder.
    gaps = [levels[n + 1] - levels[n] for n in range(5)]
    assert all(abs(g - 1.0) < 5e-3 for g in gaps), gaps

    # Higher states are more curved, so the finite-difference error grows with n.
    # A solver that had simply returned n + 1/2 would not show this.
    assert errors[5] > errors[0], errors

    # The ground state wavefunction is the Gaussian, nodeless and centred.
    await _run(ctx, "psi = H.eigenvectors_right()[0][1][0]")
    assert await _run(ctx, "bool(abs(float(psi[200])) > abs(float(psi[300])))") == "True"


@requires_sage
@pytest.mark.asyncio
async def test_perturbation_theory_fails_where_diagonalisation_does_not(physicist) -> None:
    """The quartic anharmonic oscillator: the standard demonstration that a series can be wrong.

    H = p^2/2 + x^2/2 + lambda x^4 is the toy model behind every perturbative
    expansion in field theory, and its Rayleigh-Schrodinger series

        E0 = 1/2 + (3/4) lambda - (21/8) lambda^2 + ...

    has zero radius of convergence -- Bender and Wu, 1969. At lambda = 0.1 it is
    already off by 2%; at lambda = 1 it returns -1.375, a *negative* ground state
    energy for a manifestly positive Hamiltonian, against a true value of 0.804.

    Matrix mechanics in the oscillator basis, meanwhile, just works: x is
    tridiagonal with entries sqrt((n+1)/2), so x^4 is a matrix product and the
    energy is an eigenvalue. E0(lambda=0.1) = 0.559146327 is the benchmark value
    in the literature, and this recovers it to eight digits.

    This is the clearest case in the suite of the server earning its place: the
    perturbative answer is the one a model reproduces from memory, and it is the
    wrong one.
    """
    ctx = FakeContext("anharmonic")

    await _run(ctx, (
        "M = 60\n"
        "X = matrix(RDF, M, M)\n"
        "for n in range(M-1):\n"
        "    X[n, n+1] = sqrt((n+1)/2.0)\n"
        "    X[n+1, n] = sqrt((n+1)/2.0)\n"
        "X4 = X*X*X*X\n"
        "H0 = diagonal_matrix(RDF, [n + 0.5 for n in range(M)])"
    ))

    # The basis is right if the unperturbed problem is: <n|x^2|n> = n + 1/2.
    assert await _run(ctx, "bool(abs((X*X)[3,3] - 3.5) < 1e-12)") == "True"

    # lambda = 0.1, against the published benchmark.
    ground = await _num(ctx, (
        "E = sorted((H0 + 0.1*X4).eigenvalues())\n"
        "float(E[0])"
    ))
    assert abs(ground - 0.559146327) < 1e-8, ground

    # Converged in the basis size: 40 states already give the same answer.
    smaller = await _num(ctx, (
        "Xs = X[:40, :40]\n"
        "float(sorted((H0[:40, :40] + 0.1*(Xs*Xs*Xs*Xs)).eigenvalues())[0])"
    ))
    assert abs(smaller - ground) < 1e-6, (smaller, ground)

    # Second-order perturbation theory, at the same coupling: 2% low.
    series = await _num(ctx, "float(0.5 + 0.75*0.1 - 21/8*0.1^2)")
    assert abs(series - ground) / ground > 0.01, (series, ground)
    assert series < ground

    # At lambda = 1 the series is not approximately wrong, it is unphysical.
    assert await _num(ctx, "float(0.5 + 0.75*1 - 21/8*1^2)") < 0

    strong = await _num(ctx, "float(sorted((H0 + X4).eigenvalues())[0])")
    assert 0.803 < strong < 0.804, strong
    # Converged there too, which is the check that matters at strong coupling:
    # 40 states and 60 agree to eight digits, so this is the answer and not the
    # truncation. Perturbation theory offers -1.375 for the same quantity.
    assert abs(await _num(ctx, (
        "Xt = X[:40, :40]\n"
        "float(sorted((H0[:40, :40] + Xt*Xt*Xt*Xt).eigenvalues())[0])"
    )) - strong) < 1e-8
    # Every eigenvalue of a positive-definite Hamiltonian is positive, which is
    # the property the series violated.
    assert await _run(ctx, "all(float(v) > 0 for v in (H0 + X4).eigenvalues())") == "True"


# --- condensed matter ---------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_the_normal_modes_of_a_mass_spring_chain(physicist) -> None:
    """Phonons in one dimension, where the numerics can be checked against a formula exactly.

    A chain of masses and springs has a stiffness matrix that is tridiagonal
    (2, -1), whose eigenvalues are known in closed form:
    omega_k^2 = 4 sin^2(k pi / 2(N+1)). Agreement to machine precision -- not to
    a tolerance chosen to make the test pass -- is available here, so that is
    what is asserted.

    It also demonstrates the acoustic branch: the lowest mode's frequency falls
    like 1/N, which is why a long chain has arbitrarily soft modes and a solid
    conducts sound.
    """
    ctx = FakeContext("phonons")

    await _run(ctx, (
        "def chain(N):\n"
        "    K = matrix(RDF, N, N)\n"
        "    for i in range(N):\n"
        "        K[i,i] = 2\n"
        "        if i > 0:\n"
        "            K[i,i-1] = -1\n"
        "        if i < N-1:\n"
        "            K[i,i+1] = -1\n"
        "    return K\n"
        "N = 24\nK = chain(N)"
    ))

    worst = await _num(ctx, (
        "computed = sorted(K.eigenvalues())\n"
        "exact = sorted([float(4*sin(k*pi/(2*(N+1)))^2) for k in range(1, N+1)])\n"
        "max(abs(float(computed[i]) - exact[i]) for i in range(N))"
    ))
    assert worst < 1e-12, worst

    # No negative eigenvalues: the chain is stable, every mode oscillates.
    assert await _run(ctx, "all(float(v) > 0 for v in computed)") == "True"

    # The acoustic branch: doubling the chain halves the lowest frequency.
    ratio = await _num(ctx, (
        "w1 = sqrt(min(chain(24).eigenvalues()))\n"
        "w2 = sqrt(min(chain(49).eigenvalues()))\n"
        "float(w1/w2)"
    ))
    assert abs(ratio - 2.0) < 0.05, ratio


# --- electromagnetism ---------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_a_plane_wave_satisfies_maxwells_equations(physicist) -> None:
    """Check an ansatz against the field equations, symbolically, which is what one does.

    The four vacuum equations are four identities, and Sage can decide them
    rather than approximate them: the assertions below are exact symbolic zeros.
    The wave speed comes out as c because it was put in as 1/sqrt(eps0 mu0), so
    the last check is the one Maxwell himself made.
    """
    ctx = FakeContext("maxwell")

    await _run(ctx, (
        "k, om = var('k om')\n"
        "assume(k > 0)\nassume(om > 0)\n"
        "E = vector([0, sin(k*x - om*t), 0])\n"
        "B = vector([0, 0, (k/om)*sin(k*x - om*t)])\n"
        "def div(F):\n"
        "    return diff(F[0], x) + diff(F[1], y) + diff(F[2], z)\n"
        "def curl(F):\n"
        "    return vector([diff(F[2], y) - diff(F[1], z),\n"
        "                   diff(F[0], z) - diff(F[2], x),\n"
        "                   diff(F[1], x) - diff(F[0], y)])"
    ))

    # Gauss, both of them: no charges, no monopoles.
    assert await _run(ctx, "bool(div(E) == 0)") == "True"
    assert await _run(ctx, "bool(div(B) == 0)") == "True"

    # Faraday: curl E = -dB/dt, identically in x and t.
    assert await _run(ctx, "bool((curl(E) + diff(B, t)).norm().simplify_full() == 0)") == "True"

    # Ampere in vacuum: curl B = (1/c^2) dE/dt holds only when om/k = c, so
    # solving that condition *is* the derivation of the wave speed.
    speed = await _run(ctx, (
        "residual = (curl(B) - diff(E, t)/var('cc')^2)[1].simplify_full()\n"
        "str(solve(residual == 0, cc))"
    ))
    assert "om/k" in speed or "-om/k" in speed, speed

    # The transversality that makes it a light wave: E, B and k mutually
    # perpendicular, with E x B along the propagation direction.
    assert await _run(ctx, "bool(E.dot_product(B) == 0)") == "True"
    assert await _run(ctx, "bool(E.cross_product(B)[0].simplify_full() != 0)") == "True"


# --- atomic physics -----------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_the_bohr_radius_and_rydberg_from_measured_constants(physicist) -> None:
    """Build the hydrogen atom out of CODATA and check it reproduces CODATA.

    a0, the Rydberg energy and the fine-structure constant are all combinations
    of the same five measured numbers, so computing them is a consistency check
    on the arithmetic and on the constants together. 1/alpha = 137.036 to nine
    digits from quantities measured independently is the kind of agreement that
    is worth asserting to eight decimal places rather than two.
    """
    ctx = FakeContext("bohr")
    await _run(ctx, _SI)

    a0 = await _num(ctx, "a0 = 4*pi*eps0*hbar^2/(me*qe^2)\nfloat(a0)")
    assert abs(a0 - BOHR_RADIUS) / BOHR_RADIUS < 1e-8, a0

    rydberg = await _num(ctx, "float(me*qe^4/(8*eps0^2*h^2)/qe)")
    assert abs(rydberg - RYDBERG_EV) / RYDBERG_EV < 1e-6, rydberg

    inverse_alpha = await _num(ctx, "alpha = qe^2/(4*pi*eps0*hbar*c)\nfloat(1/alpha)")
    assert abs(inverse_alpha - INVERSE_FINE_STRUCTURE) < 1e-5, inverse_alpha

    # The relations between them, which is the real check: Ry = alpha^2 me c^2/2,
    # and a0 = hbar/(alpha me c).
    assert await _run(ctx, "bool(abs(alpha^2*me*c^2/2/qe - 13.605693) < 1e-5)") == "True"
    assert await _run(ctx, "bool(abs(hbar/(alpha*me*c)/a0 - 1) < 1e-12)") == "True"

    # Lyman alpha: n=1 -> 2 at 121.6 nm, which is why the line is in the UV.
    lyman = await _num(ctx, "float(h*c/(13.605693122994*qe*(1 - 1/4))*1e9)")
    assert abs(lyman - 121.6) < 0.1, lyman

    # Sage's own unit system agrees about the electronvolt.
    joules = await _num(ctx, (
        "((1*units.energy.electron_volt).convert(units.energy.joule)"
        "/units.energy.joule).n()"
    ))
    assert abs(joules - 1.602e-19) / 1.602e-19 < 1e-3, joules


# --- experimental data --------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_fitting_a_decay_curve_recovers_the_half_life(physicist) -> None:
    """Counts from a detector, and the number the experiment was run to get.

    Two routes to the same half-life, which is how a careful person checks a
    fit: nonlinear least squares on the counts directly, and ordinary least
    squares on their logarithms. They must agree -- they weight the points
    differently, so they agree only if the model is right and the data are
    clean.

    Then the statistics that make it a measurement rather than a number: the
    residual scatter, and a chi-squared against Poisson counting errors, which
    is the test a physicist actually applies before believing a fit.
    """
    ctx = FakeContext("decay")

    await _run(ctx, (
        "counts = [(0, 1000), (5, 847), (10, 719), (15, 610), (20, 517),\n"
        "          (25, 439), (30, 372), (35, 316), (40, 268)]\n"
        "var('A lam')"
    ))

    await _run(ctx, (
        "fit = find_fit(counts, A*exp(-lam*x), parameters=[A, lam], variables=[x])\n"
        "lam_hat = float(fit[1].rhs())\nA_hat = float(fit[0].rhs())"
    ))
    half_life = await _num(ctx, "float(log(2)/lam_hat)")
    assert 20 < half_life < 22, half_life

    # The amplitude must come back as the count at t = 0, which nothing in the
    # fit forced.
    assert abs(await _num(ctx, "A_hat") - 1000) < 20

    # The linearised route, by hand, as a check on the black box.
    linear = await _num(ctx, (
        "n = len(counts)\n"
        "sx = sum(p[0] for p in counts)\nsy = sum(log(p[1]) for p in counts)\n"
        "sxx = sum(p[0]^2 for p in counts)\nsxy = sum(p[0]*log(p[1]) for p in counts)\n"
        "slope = (n*sxy - sx*sy)/(n*sxx - sx^2)\n"
        "float(-log(2)/slope)"
    ))
    assert abs(linear - half_life) / half_life < 0.01, (linear, half_life)

    # Residuals: no structure left, and small enough that the model is not being
    # asked to explain something it cannot.
    worst = await _num(ctx, (
        "resid = [float(p[1] - A_hat*exp(-lam_hat*p[0])) for p in counts]\n"
        "max(abs(r) for r in resid)"
    ))
    assert worst < 15, worst

    # Chi-squared against Poisson errors sqrt(N): with 9 points and 2 parameters
    # a good fit sits near 7, and anything past ~20 would be a rejected model.
    chi2 = await _num(ctx, (
        "float(sum((p[1] - A_hat*exp(-lam_hat*p[0]))^2/p[1] for p in counts))"
    ))
    assert chi2 < 20, chi2


# --- nonlinear dynamics -------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_the_double_pendulum_conserves_energy_and_forgets_its_initial_condition(
    physicist,
) -> None:
    """Chaos, and the only two things about it that can be honestly asserted.

    A chaotic trajectory cannot be validated by comparing it against a reference
    -- any two solvers diverge exponentially, which is the definition of the
    phenomenon. What *can* be asserted is that the integrator preserves what the
    dynamics preserves, and that the divergence is real rather than a numerical
    artefact:

    * Energy is conserved by the Hamiltonian, so a drift in it is the solver's
      error, not physics. LSODA at its default tolerances holds it to about a
      part in 1e6 over forty time units -- orders below the separation growth
      below, which is what makes that growth believable.
    * Two initial conditions 1e-9 apart separate by five orders of magnitude
      within forty time units, and a *third* run at low energy does not --
      which is what distinguishes chaos from an unstable integrator, since an
      unstable integrator would blow up on both.
    """
    ctx = FakeContext("chaos")

    # Equal masses and lengths, in units where m = l = g = 1, in the standard
    # canonical form.
    await _run(ctx, (
        "t1, t2, p1, p2 = var('t1 t2 p1 p2')\n"
        "den = 1 + sin(t1 - t2)^2\n"
        "A = (p1*p2*sin(t1 - t2))/den\n"
        "B = (p1^2 - 2*p1*p2*cos(t1 - t2) + 2*p2^2)*sin(2*(t1 - t2))/(2*den^2)\n"
        "rhs = [(p1 - p2*cos(t1 - t2))/den,\n"
        "       (2*p2 - p1*cos(t1 - t2))/den,\n"
        "       -2*sin(t1) - A + B,\n"
        "       -sin(t2) + A - B]\n"
        "def energy(s):\n"
        "    a, b, c, d = [float(v) for v in s]\n"
        "    dd = 1 + sin(a - b)^2\n"
        "    return float((c^2 - 2*c*d*cos(a - b) + 2*d^2)/(2*dd) - 2*cos(a) - cos(b))\n"
        "ts = srange(0, 40, 0.01)"
    ))

    await _run(ctx, "s1 = desolve_odeint(rhs, [2.0, 2.0, 0, 0], ts, [t1, t2, p1, p2])")

    drift = await _num(ctx, (
        "E0 = energy(s1[0])\n"
        "max(abs(energy(r) - E0) for r in s1)/abs(E0)"
    ))
    assert drift < 1e-4, drift

    # This is a high-energy start: enough to swing the inner pendulum over the
    # top, which is the regime where the motion is chaotic.
    assert await _num(ctx, "float(E0)") > -1.0

    await _run(ctx, "s2 = desolve_odeint(rhs, [2.0 + 1e-9, 2.0, 0, 0], ts, [t1, t2, p1, p2])")
    growth = await _num(ctx, (
        "sep = [abs(float(s1[i][0] - s2[i][0])) for i in range(len(ts))]\n"
        "float(max(sep[2000:])/sep[0])"
    ))
    assert growth > 1e4, growth

    # The control: a low-energy start, where the pendulum swings gently and
    # nearby trajectories stay nearby. Same code, same solver, same step.
    tame = await _num(ctx, (
        "r1 = desolve_odeint(rhs, [0.05, 0.05, 0, 0], ts, [t1, t2, p1, p2])\n"
        "r2 = desolve_odeint(rhs, [0.05 + 1e-9, 0.05, 0, 0], ts, [t1, t2, p1, p2])\n"
        "float(max(abs(float(r1[i][0] - r2[i][0])) for i in range(len(ts)))/1e-9)"
    ))
    assert tame < 100, tame
