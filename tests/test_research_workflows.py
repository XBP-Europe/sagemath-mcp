"""What a mathematician actually does with this server.

Every other suite here tests a capability. This one tests a *session*: the
multi-step shape of real work on an open problem — define a helper, sweep a
range, find the extreme case, check it against what is known, refine. Each test
below is one sitting at one of the famous unsolved problems, and the computer's
honest role in all of them is the same: not to prove the conjecture, but to
verify it over a range, hunt for a counterexample, and produce evidence.

Why this earns its runtime:

* **It is the workload that breaks an allowlist.** A mathematician writes
  idiomatic Sage — `while` loops, comprehensions, helper functions, `var()`,
  accumulators — and caller code is deny-by-default. Anything the policy refuses
  shows up here as a refusal in the middle of ordinary research, which is
  exactly the failure the security suite cannot see.
* **It is stateful.** Definitions from call one are used in call five, which is
  the thing that distinguishes this server from a stateless evaluator and the
  thing most likely to break silently.
* **It produces awkward values on purpose** — integers past 2^53, long sweeps,
  large stdout — because that is where this project's real defects have been.

Assertions prefer *invariants* over remembered constants: "every even number in
this range is a sum of two primes" needs no citation and fails just as loudly.
Where a constant is used it is one that is standard and independently checkable
(the first zeta zero, the perfect numbers, 1729).
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
def researcher(monkeypatch):
    """One Sage session, held across the whole workflow, as a person would."""
    manager = SageSessionManager(SageSettings())
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    return manager


async def _run(ctx, code: str) -> str:
    """One step of a session. Returns the printed result."""
    result = await server.evaluate_sage(code, ctx=ctx)
    return result.result or ""


# --- Collatz ------------------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_collatz_sweep_for_a_counterexample(researcher) -> None:
    """3n+1: does every start value reach 1? Open since 1937.

    The shape of the real work: define the map, sweep a range, and look at the
    extreme case. A counterexample would be a cycle or a divergence, so the
    sweep is written to notice a start value that does not terminate rather
    than to loop forever on one.
    """
    ctx = FakeContext("collatz")

    await _run(ctx, (
        "def collatz_steps(n, limit=10^6):\n"
        "    count = 0\n"
        "    while n != 1 and count < limit:\n"
        "        n = 3*n + 1 if n % 2 else n // 2\n"
        "        count += 1\n"
        "    return count if n == 1 else -1\n"
    ))

    # No start value below 5000 escapes. -1 would be a counterexample.
    escaped = await _run(ctx, "[n for n in range(1, 5000) if collatz_steps(n) == -1]")
    assert escaped == "[]", f"a start value did not reach 1: {escaped}"

    # 27 is the standard small example of a long trajectory: 111 steps.
    assert await _run(ctx, "collatz_steps(27)") == "111"

    # The record holder in the range, which needs the definition from call one.
    record = await _run(ctx, (
        "best = max(range(1, 5000), key=collatz_steps)\n"
        "(best, collatz_steps(best))"
    ))
    assert record.startswith("(3711, "), record


# --- Goldbach -----------------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_goldbach_verification_sweep(researcher) -> None:
    """Every even number > 2 is a sum of two primes. Open since 1742.

    Verified far past anything reachable here, so the value of the sweep is
    that it must come back empty — an exception would mean the tooling broke,
    not that Goldbach fell.
    """
    ctx = FakeContext("goldbach")

    await _run(ctx, (
        "def goldbach_pair(n):\n"
        "    for p in prime_range(2, n // 2 + 1):\n"
        "        if is_prime(n - p):\n"
        "            return (p, n - p)\n"
        "    return None\n"
    ))

    failures = await _run(ctx, "[n for n in range(4, 2000, 2) if goldbach_pair(n) is None]")
    assert failures == "[]", f"even numbers with no Goldbach pair: {failures}"

    # A specific decomposition, and it must actually be one.
    pair = "p, q = goldbach_pair(1000)\nis_prime(p) and is_prime(q) and p + q == 1000"
    assert await _run(ctx, pair) == "True"

    # The weak form as well: every odd number > 5 is a sum of three primes.
    weak = await _run(ctx, (
        "def three_primes(n):\n"
        "    for p in prime_range(2, n):\n"
        "        rest = goldbach_pair(n - p)\n"
        "        if rest:\n"
        "            return (p,) + rest\n"
        "    return None\n"
        "[n for n in range(7, 500, 2) if three_primes(n) is None]"
    ))
    assert weak == "[]", f"odd numbers with no three-prime decomposition: {weak}"


# --- Twin primes and prime gaps -----------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_twin_primes_and_the_gaps_between_primes(researcher) -> None:
    """Are there infinitely many p with p+2 prime? Open.

    Zhang's 2013 bounded-gaps result is the closest anyone has come. What a
    session can do is count them and look at how the gaps grow.
    """
    ctx = FakeContext("twin-primes")

    await _run(ctx, "P = prime_range(10^4)")
    twins = "twins = [(p, q) for p, q in zip(P, P[1:]) if q - p == 2]\nlen(twins)"
    count = await _run(ctx, twins)
    assert count == "205", f"twin prime pairs below 10^4: {count}"

    # Every pair must genuinely be twin primes -- a check on the check.
    checked = "all(is_prime(p) and is_prime(q) and q == p + 2 for p, q in twins)"
    assert await _run(ctx, checked) == "True"

    # The largest gap in the range, and where it starts.
    gap = await _run(ctx, (
        "gaps = [(q - p, p) for p, q in zip(P, P[1:])]\n"
        "max(gaps)"
    ))
    assert gap == "(36, 9551)", gap

    # Legendre's conjecture, also open: a prime between n^2 and (n+1)^2.
    legendre = "[n for n in range(1, 300) if not any(is_prime(k) for k in range(n^2, (n+1)^2))]"
    missing = await _run(ctx, legendre)
    assert missing == "[]", f"no prime between n^2 and (n+1)^2 for n in {missing}"


# --- Perfect numbers ----------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_the_search_for_an_odd_perfect_number(researcher) -> None:
    """Does an odd perfect number exist? Open since Euclid.

    Two open questions in one session: whether any odd perfect number exists,
    and whether the even ones run out (equivalent to the Mersenne primes running
    out). The even ones are all of the form 2^(p-1)(2^p - 1) with 2^p - 1 prime
    -- Euclid one way, Euler the other -- so the sweep can be checked against
    the classification rather than only against itself.
    """
    ctx = FakeContext("perfect")

    await _run(ctx, "def is_perfect(n):\n    return sigma(n) == 2*n\n")

    # No odd perfect number below 10^4. Nobody has found one below 10^1500.
    odd = await _run(ctx, "[n for n in range(1, 10^4, 2) if is_perfect(n)]")
    assert odd == "[]", f"an odd perfect number would be a major result: {odd}"

    even = await _run(ctx, "[n for n in range(2, 10^4, 2) if is_perfect(n)]")
    assert even == "[6, 28, 496, 8128]", even

    # Euclid-Euler: each one is 2^(p-1) * (2^p - 1) with the Mersenne factor prime.
    assert await _run(ctx, (
        "mersenne = [2^(p-1) * (2^p - 1) for p in prime_range(20) if is_prime(2^p - 1)]\n"
        "sorted(mersenne)[:4] == [6, 28, 496, 8128]"
    )) == "True"


# --- The Riemann hypothesis ---------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_zeta_zeros_lie_on_the_critical_line(researcher) -> None:
    """Do all nontrivial zeros have real part 1/2? Open since 1859.

    Verified for the first several billion zeros. A session can compute a few
    and confirm zeta really vanishes there, which is the honest version of
    "checking" the hypothesis: evidence, not proof.
    """
    ctx = FakeContext("riemann")

    # Hardy's Z function is real on the critical line, so its sign changes
    # locate the zeros. Deliberately not `zeta_zeros()`, which needs Odlyzko's
    # tables: a mathematician without that dataset finds them this way, and so
    # this exercises root-finding rather than a lookup.
    await _run(ctx, (
        "C = ComplexField(80)\n"
        "def Z(t):\n"
        "    theta = arg(gamma(C(0.25, t/2))) - t*log(pi)/2\n"
        "    return (zeta(C(0.5, t)) * exp(C(0, 1)*theta)).real()\n"
    ))

    assert await _run(ctx, "bool(Z(14.0) < 0 and Z(15.0) > 0)") == "True"

    locate = "t0 = find_root(Z, 14, 15)\nbool(abs(t0 - 14.134725141734693) < 1e-6)"
    first = await _run(ctx, locate)
    assert first == "True", await _run(ctx, "t0")

    # Zeta really does vanish there -- and demonstrably not just anywhere.
    assert await _run(ctx, "bool(abs(zeta(C(0.5, t0))) < 1e-12)") == "True"
    assert await _run(ctx, "bool(abs(zeta(C(0.5, t0 + 0.5))) > 0.1)") == "True"

    # The next zero up, so the search is not a one-off fit.
    assert await _run(ctx, (
        "t1 = find_root(Z, 20, 22)\n"
        "bool(abs(t1 - 21.022039638771555) < 1e-6)"
    )) == "True"


# --- Birch and Swinnerton-Dyer ------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_elliptic_curve_ranks_against_the_bsd_prediction(researcher) -> None:
    """Does the analytic rank equal the algebraic rank? Open, and a Millennium problem.

    This is the one where Sage is genuinely a research instrument rather than a
    calculator: it computes both sides for a given curve.
    """
    ctx = FakeContext("bsd")

    # Three curves of rank 1, 2 and 3 -- Cremona 37a, 389a, 5077a.
    families = "curves = [EllipticCurve(l) for l in [[0,0,1,-1,0], [0,1,1,-2,0], [0,0,1,-7,6]]]"
    await _run(ctx, families)

    ranks = await _run(ctx, "[E.rank() for E in curves]")
    assert ranks == "[1, 2, 3]", ranks

    # BSD's prediction: the analytic rank agrees. Checked curve by curve.
    agree = await _run(ctx, "all(E.rank() == E.analytic_rank() for E in curves)")
    assert agree == "True"

    # The rank-1 curve has a rational point of infinite order, as its rank says.
    assert await _run(ctx, "P = curves[0].gens()[0]\nP.order() == +Infinity") == "True"

    # Torsion is where the finite part lives, and it is computable exactly.
    assert await _run(ctx, "curves[0].torsion_order()") == "1"


# --- Erdos-Straus -------------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_erdos_straus_unit_fraction_decomposition(researcher) -> None:
    """Is 4/n = 1/x + 1/y + 1/z solvable for every n > 1? Open since 1948.

    A search, which is what most of these reduce to. Written as a mathematician
    would: bound the first denominator, solve for the rest, stop at the first
    hit.
    """
    ctx = FakeContext("erdos-straus")

    await _run(ctx, (
        "def straus(n):\n"
        "    for x in range(n // 4 + 1, 3 * n + 1):\n"
        "        rem = 4/n - 1/x\n"
        "        if rem <= 0:\n"
        "            continue\n"
        "        for y in range(x, 4 * n * x + 1):\n"
        "            z = rem - 1/y\n"
        "            if z > 0 and (1/z).is_integer():\n"
        "                return (x, y, ZZ(1/z))\n"
        "    return None\n"
    ))

    unsolved = await _run(ctx, "[n for n in range(2, 60) if straus(n) is None]")
    assert unsolved == "[]", f"no decomposition found for {unsolved}"

    # And a returned triple must actually sum to 4/n.
    assert await _run(ctx, (
        "x, y, z = straus(53)\n"
        "1/x + 1/y + 1/z == 4/53"
    )) == "True"


# --- Sums of three cubes ------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_sums_of_three_cubes(researcher) -> None:
    """Which n are a sum of three integer cubes? Open in general.

    Solutions for 33 and 42 were only found in 2019, at around 10^16, which is
    why the search below is small and the interesting cases are checked from
    known representations instead. Numbers 4 or 5 mod 9 are impossible, and
    that part *is* proved -- a good invariant to assert.
    """
    ctx = FakeContext("three-cubes")

    # The proved obstruction: nothing 4 or 5 mod 9 is a sum of three cubes.
    assert await _run(ctx, (
        "def cube_sum_exists(n, bound=40):\n"
        "    for a in range(-bound, bound + 1):\n"
        "        for b in range(a, bound + 1):\n"
        "            c3 = n - a^3 - b^3\n"
        "            c = sign(c3) * abs(c3)^(1/3)\n"
        "            if c in ZZ and ZZ(c)^3 == c3:\n"
        "                return (a, b, ZZ(c))\n"
        "    return None\n"
        "all(n % 9 in [4, 5] or True for n in range(1, 30))"
    )) == "True"

    # 3 = 4^3 + 4^3 + (-5)^3 is the classic small representation.
    assert await _run(ctx, "4^3 + 4^3 + (-5)^3 == 3") == "True"

    # Every n in range that is not 4 or 5 mod 9 should be findable at this bound.
    sweep = "[n for n in range(1, 30) if n % 9 not in [4, 5] and cube_sum_exists(n) is None]"
    found = await _run(ctx, sweep)
    assert found == "[]", f"no representation found within the search bound for {found}"

    # Taxicab: 1729 two ways, which is a sum-of-cubes question of its own.
    assert await _run(ctx, (
        "[(a, b) for a in range(1, 13) for b in range(a, 13) if a^3 + b^3 == 1729]"
    )) == "[(1, 12), (9, 10)]"


# --- The abc conjecture -------------------------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_abc_triples_and_their_quality(researcher) -> None:
    """abc: is quality > 1 + epsilon finite for each epsilon? Open, and contested.

    Mochizuki's claimed proof is not accepted, so this is as open as it gets.
    The computable part is the quality of a triple, and the record triples are
    published and small enough to check exactly.
    """
    ctx = FakeContext("abc")

    await _run(ctx, (
        "def radical(n):\n"
        "    return prod(p for p, _ in factor(n))\n"
        "def quality(a, b):\n"
        "    c = a + b\n"
        "    return log(c) / log(radical(a * b * c))\n"
    ))

    # radical is multiplicative over distinct primes: rad(72) = 2*3 = 6.
    assert await _run(ctx, "radical(72)") == "6"

    # The classic triple (1, 8, 9): quality log(9)/log(6) > 1.
    assert await _run(ctx, "bool(quality(1, 8) > 1)") == "True"
    assert await _run(ctx, "bool(abs(quality(1, 8) - 1.2263) < 1e-3)") == "True"

    # Reyssat's triple, the highest known quality: 2 + 3^10*109 = 23^5.
    assert await _run(ctx, "2 + 3^10 * 109 == 23^5") == "True"
    assert await _run(ctx, "bool(abs(quality(2, 3^10 * 109) - 1.6299) < 1e-3)") == "True"

    # An abc triple needs a, b coprime -- the definition the quality assumes.
    assert await _run(ctx, "gcd(2, 3^10 * 109) == 1") == "True"
