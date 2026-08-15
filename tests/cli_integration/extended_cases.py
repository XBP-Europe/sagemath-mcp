"""Tool-forcing CLI cases: questions a model cannot answer from memory.

The existing suite in ``test_cases.py`` validates by grepping the CLI's final
answer. That cannot distinguish "the MCP server computed this" from "the model
already knew it": asked to differentiate x^3 + 2x, every model replies 3x^2 + 2
without touching any tool, and the test passes.

Two changes here:

* Each question has an answer that is impractical to recall or do in-head --
  next_prime(10^30), Bell(25), a 5x5 determinant. A model that skips the tool
  gets it wrong, or refuses.
* Every case additionally asserts, from the proxy's wire log, that the expected
  tool was actually called and did not return an error. That is the part which
  makes this an integration test rather than a quiz.

The `numerics` and `physics` domains push that one step further. There the
model is not merely unable to recall the answer -- it can recall something
*adjacent and wrong*, which is the actual failure mode when a physicist asks an
LLM for a number. pi^2/6 is not the sum to 10^6. The exact ground state of a
discretised oscillator is not 1/2. Mercury's advance is 42.98, not the 43 that
every account of it quotes. A model that reasons instead of computing lands a
few digits off and sounds completely certain, which is why the expected values
below carry more significant figures than anyone memorises.

Expected values were computed with SageMath 10.9 and are exact. They are stored
one digit short of the precision the prompt asks for, because a model that
rounds correctly and a model that truncates disagree in the last place and both
are right: 1.3331346926634 answered to 11 figures is `1.3331346927`, and an
expected value ending `...926` fails a correct answer.

    python -m tests.cli_integration.run_extended --cli all --domain numerics,physics
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolForcingCase:
    id: str
    domain: str
    prompt: str
    # Any one of these in the CLI's answer counts as correct.
    expected_answers: list[str]
    # The tool call the server must actually receive. Several are allowed
    # because a model may legitimately reach the same result another way, for
    # example evaluate_sage instead of the dedicated helper.
    accepted_tools: list[str]
    timeout_seconds: int = 300
    # Substrings that mean the model dodged rather than computed.
    forbidden: list[str] = field(default_factory=lambda: ["cannot", "unable to"])


_SUFFIX = " Use the sagemath MCP server. Reply with ONLY the result, no prose."

EXTENDED_CASES: list[ToolForcingCase] = [
    # ---- number theory -----------------------------------------------------
    ToolForcingCase(
        id="ext-nt-next-prime",
        domain="number_theory",
        # 31 digits: not memorised, and not doable mentally.
        prompt="What is the smallest prime strictly greater than 10^30?" + _SUFFIX,
        expected_answers=["1000000000000000000000000000057"],
        accepted_tools=["number_theory_operation", "evaluate_sage", "calculate_expression"],
    ),
    ToolForcingCase(
        id="ext-nt-factorial-mod",
        domain="number_theory",
        prompt="Compute factorial(50) modulo 1000003." + _SUFFIX,
        expected_answers=["850717"],
        accepted_tools=["evaluate_sage", "calculate_expression", "number_theory_operation"],
    ),
    # ---- combinatorics -----------------------------------------------------
    ToolForcingCase(
        id="ext-comb-bell",
        domain="combinatorics",
        prompt="What is the 25th Bell number?" + _SUFFIX,
        expected_answers=["4638590332229999353"],
        accepted_tools=["combinatorics_operation", "evaluate_sage", "calculate_expression"],
    ),
    ToolForcingCase(
        id="ext-comb-partitions",
        domain="combinatorics",
        prompt="How many integer partitions does 120 have?" + _SUFFIX,
        expected_answers=["1844349560"],
        accepted_tools=["combinatorics_operation", "evaluate_sage", "calculate_expression"],
    ),
    # ---- linear algebra ----------------------------------------------------
    ToolForcingCase(
        id="ext-la-determinant",
        domain="linear_algebra",
        prompt=(
            "Compute the determinant of the 5x5 integer matrix "
            "[[3,1,4,1,5],[9,2,6,5,3],[5,8,9,7,9],[3,2,3,8,4],[6,2,6,4,3]]." + _SUFFIX
        ),
        expected_answers=["-1813"],
        accepted_tools=["matrix_operation", "evaluate_sage"],
    ),
    # ---- elliptic curves ---------------------------------------------------
    ToolForcingCase(
        id="ext-ec-conductor",
        domain="elliptic_curves",
        prompt=(
            "For the elliptic curve with Weierstrass coefficients [0,0,1,-7,6], "
            "what is its conductor?" + _SUFFIX
        ),
        expected_answers=["5077"],
        accepted_tools=["elliptic_curve_operation", "evaluate_sage"],
    ),
    # ---- coding theory -----------------------------------------------------
    ToolForcingCase(
        id="ext-coding-hamming",
        domain="coding_theory",
        prompt=(
            "For the binary Hamming code HammingCode(GF(2),5), give its length "
            "and dimension as 'length,dimension'." + _SUFFIX
        ),
        expected_answers=["31,26", "31, 26"],
        accepted_tools=["coding_theory_operation", "evaluate_sage"],
    ),
    # ---- stateful: impossible to fake ---------------------------------------
    # ---- open problems ------------------------------------------------------
    # A mathematician's questions rather than a calculator's. Each answer needs a
    # real sweep -- none is recallable, and none is doable in-head -- so a model
    # that skips the server cannot bluff its way past the wire-log check. These
    # also exercise the shape the research suite covers: define, sweep, report.
    ToolForcingCase(
        id="ext-open-twin-primes",
        domain="open_problems",
        prompt=(
            "How many twin prime pairs (p, p+2) are there with p+2 below one million? "
            "Twin primes are an open problem, so count them exactly rather than estimating."
        ) + _SUFFIX,
        expected_answers=["8169"],
        accepted_tools=["evaluate_sage", "evaluate_sage_streaming", "number_theory_operation"],
    ),
    ToolForcingCase(
        id="ext-open-collatz-record",
        domain="open_problems",
        prompt=(
            "For the Collatz 3n+1 map, which starting value below 100000 takes the most "
            "steps to reach 1, and how many steps does it take? Answer as 'value, steps'."
        ) + _SUFFIX,
        expected_answers=["77031"],
        accepted_tools=["evaluate_sage", "evaluate_sage_streaming"],
        timeout_seconds=420,
    ),
    ToolForcingCase(
        id="ext-open-prime-gap",
        domain="open_problems",
        prompt=(
            "What is the largest gap between consecutive primes below one million, and "
            "which prime does that gap start at? Answer as 'gap, prime'."
        ) + _SUFFIX,
        expected_answers=["492113"],
        accepted_tools=["evaluate_sage", "evaluate_sage_streaming", "number_theory_operation"],
    ),
    ToolForcingCase(
        id="ext-open-amicable",
        domain="open_problems",
        prompt=(
            "List every amicable pair (a, b) with a < b < 10000, where each number is the "
            "sum of the other's proper divisors."
        ) + _SUFFIX,
        expected_answers=["6232"],
        accepted_tools=["evaluate_sage", "evaluate_sage_streaming"],
    ),
    ToolForcingCase(
        id="ext-open-bsd-rank",
        domain="open_problems",
        prompt=(
            "For the elliptic curve y^2 + y = x^3 - 7x + 6, what is its Mordell-Weil rank "
            "and its conductor? Answer as 'rank, conductor'."
        ) + _SUFFIX,
        expected_answers=["5077"],
        accepted_tools=["elliptic_curve_operation", "evaluate_sage"],
    ),
    # ---- numerical analysis -------------------------------------------------
    # The questions where a model's *memory* is the failure mode rather than its
    # arithmetic. Each has a closed-form neighbour that is famous and wrong for
    # what was asked -- pi^2/6 for a truncated sum, 1/2 for a discretised
    # oscillator, 43 for Mercury -- so answering from recall lands close enough
    # to feel right and fails the digits. There is no way to reach them but to
    # run the computation.
    ToolForcingCase(
        id="ext-num-basel-truncated",
        domain="numerics",
        prompt=(
            "I am estimating the truncation error in a series acceleration scheme. "
            "Compute the partial sum of 1/n^2 for n from 1 to 10^6 in double precision "
            "or higher -- summing over the rationals is exact and far too slow -- and "
            "give the result to 12 significant figures. I want the value of the partial "
            "sum itself, not the limit of the series."
        ) + _SUFFIX,
        # zeta(2) = 1.64493406684..., which is what recall produces. The
        # truncated sum differs in the sixth decimal.
        expected_answers=["1.6449330668"],
        accepted_tools=["evaluate_sage", "evaluate_sage_streaming", "calculate_expression",
                        "symbolic_sum"],
        timeout_seconds=420,
    ),
    ToolForcingCase(
        id="ext-num-kepler",
        domain="numerics",
        prompt=(
            "For an orbit of eccentricity 0.6 at mean anomaly 0.75 radians, solve "
            "Kepler's equation E - 0.6*sin(E) = 0.75 for the eccentric anomaly E. "
            "Give 11 significant figures."
        ) + _SUFFIX,
        expected_answers=["1.333134692"],
        accepted_tools=["find_root", "evaluate_sage", "solve_equation", "calculate_expression"],
    ),
    ToolForcingCase(
        id="ext-num-hilbert-exact",
        domain="numerics",
        prompt=(
            "The 12x12 Hilbert matrix H with H[i][j] = 1/(i+j+1) is the normal-equation "
            "matrix of a degree-11 polynomial fit, and it is too ill-conditioned to solve "
            "in floating point. Solve H*x = b exactly over the rationals, where b is the "
            "all-ones vector, and report the largest absolute value among the entries of x."
        ) + _SUFFIX,
        expected_answers=["249420600"],
        accepted_tools=["evaluate_sage", "matrix_operation", "evaluate_sage_streaming"],
    ),
    ToolForcingCase(
        id="ext-num-planck-integral",
        domain="numerics",
        prompt=(
            "Evaluate the Bose-Einstein integral of x^3/(exp(x) - 1) from 0 to infinity "
            "numerically, to 12 significant figures."
        ) + _SUFFIX,
        expected_answers=["6.4939394022"],
        accepted_tools=["evaluate_sage", "integrate_expression", "calculate_expression"],
    ),
    # ---- physics -------------------------------------------------------------
    ToolForcingCase(
        id="ext-phys-wien-peak",
        domain="physics",
        prompt=(
            "A pyrometer views a furnace at 3000 K. Using Wien's displacement law, "
            "derived by maximising Planck's spectral radiance rather than quoted, at "
            "what wavelength in nanometres does the emission peak? Give 6 significant "
            "figures."
        ) + _SUFFIX,
        expected_answers=["965.92"],
        accepted_tools=["find_root", "evaluate_sage", "differentiate_expression",
                        "calculate_expression"],
    ),
    ToolForcingCase(
        id="ext-phys-schrodinger-fd",
        domain="physics",
        prompt=(
            "Solve the 1D Schrodinger equation for the harmonic oscillator by finite "
            "differences, in units where hbar = m = omega = 1. Use N = 400 grid points "
            "x_i = -10 + i*dx for i = 0..399 with dx = 20/400, a Hamiltonian matrix with "
            "H[i][i] = 1/dx^2 + 0.5*x_i^2 and H[i][i+1] = H[i+1][i] = -0.5/dx^2, and "
            "Dirichlet boundaries. Report its lowest eigenvalue to 10 significant "
            "figures. I want the discrete eigenvalue, not the exact 0.5."
        ) + _SUFFIX,
        expected_answers=["0.49992186"],
        accepted_tools=["evaluate_sage", "matrix_operation", "evaluate_sage_streaming"],
        timeout_seconds=420,
    ),
    ToolForcingCase(
        id="ext-phys-anharmonic",
        domain="physics",
        prompt=(
            "For the quartic anharmonic oscillator H = p^2/2 + x^2/2 + x^4, compute the "
            "ground state energy by diagonalising H in the first 80 harmonic oscillator "
            "states, where x is the tridiagonal matrix with x[n][n+1] = x[n+1][n] = "
            "sqrt((n+1)/2) and the unperturbed energies are n + 1/2. Give 8 significant "
            "figures. Perturbation theory diverges here, so do not use it."
        ) + _SUFFIX,
        expected_answers=["0.8037706"],
        accepted_tools=["evaluate_sage", "matrix_operation", "evaluate_sage_streaming"],
        timeout_seconds=420,
    ),
    ToolForcingCase(
        id="ext-phys-mercury",
        domain="physics",
        prompt=(
            "Compute the general-relativistic perihelion advance of Mercury in arcseconds "
            "per century, from the closed form 6*pi*GM/(c^2*a*(1-e^2)) per orbit, using "
            "GM = 1.32712440018e20 m^3/s^2, a = 5.7909050e10 m, e = 0.205630, orbital "
            "period 87.9691 days and a Julian century of 36525 days. Give 4 significant "
            "figures."
        ) + _SUFFIX,
        expected_answers=["42.98"],
        accepted_tools=["evaluate_sage", "calculate_expression"],
    ),
    ToolForcingCase(
        id="ext-phys-bessel-zero",
        domain="physics",
        prompt=(
            "A circular drumhead's radial modes are the zeros of the Bessel function J0. "
            "What is the fifth positive zero of J0, to 9 significant figures?"
        ) + _SUFFIX,
        expected_answers=["14.9309177"],
        accepted_tools=["find_root", "evaluate_sage", "calculate_expression"],
    ),
    ToolForcingCase(
        id="ext-session-state",
        domain="session",
        # Nothing here is knowable without the server actually holding state
        # between two separate tool calls.
        prompt=(
            "Using the sagemath MCP server, first evaluate the code "
            "'blob = 8675309 * 31' and then, in a SECOND separate call to the "
            "same session, evaluate the code 'blob + 1'. "
            "Reply with ONLY the number from the second call."
        ),
        expected_answers=["268934580"],
        accepted_tools=["evaluate_sage"],
    ),
    ToolForcingCase(
        id="ext-session-named",
        domain="session",
        prompt=(
            "Using the sagemath MCP server: start a named session called 'clitest', "
            "evaluate 'q = 1234' in session 'clitest', then evaluate 'q * 1001' in "
            "session 'clitest'. Reply with ONLY the final number."
        ),
        expected_answers=["1235234"],
        accepted_tools=["evaluate_sage"],
    ),
]


def by_domain(domains: set[str] | None) -> list[ToolForcingCase]:
    if not domains:
        return list(EXTENDED_CASES)
    return [case for case in EXTENDED_CASES if case.domain in domains]
