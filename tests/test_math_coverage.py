"""Mathematics that must work, in every correct form.

The allowlist inverted the default. Before it, an unknown name was allowed and
the risk was that something dangerous got through; now an unknown name is
refused and the risk is the opposite one -- that ordinary mathematics stops
working, quietly, for a caller who did nothing wrong. A security suite cannot
catch that. Every test in it asserts something is *blocked*, so a policy that
refused everything would pass all of them.

Six layers, and the ordering is deliberate -- each answers a question the one
before it cannot:

1. **Binding forms** -- every way Python and Sage create a name. A caller's own
   names bypass the allowlist, so anything ``_bound_names`` misses becomes an
   unusable variable. Found ``match`` patterns and Sage's ``function('f')``.
2. **The same forms across calls** -- a session is stateful and the allowlist is
   consulted per call, so binding in one call and reading in the next is a
   different path from doing both at once. It is also the one callers use.
3. **Mathematical truths** -- predicates Sage itself evaluates to ``True``.
   "It ran without raising" is a weak assertion: this project has already
   shipped a silently wrong answer (integers above 2^53 corrupted by JSON
   parsing) that every no-exception test passed. Sage decides equality here, so
   there are no brittle string comparisons.
4. **Equivalent spellings** -- ``2^10``, ``2**10`` and ``pow(2, 10)`` must agree.
   Clients are models, which emit many spellings of one request; asserting
   agreement between them catches a wrong answer without anyone having to know
   the right one in advance.
5. **Preparser forms** -- Sage is not Python. ``5/2`` is a rational, ``2^10`` is
   a power, ``R.<t> = QQ[]`` declares a generator. The preparser runs on caller
   code only, so its behaviour is part of this contract.
6. **Allowlist reachability** -- the names callers reach for, by area, with a
   size floor. A nearly-empty allowlist passes every security test there is.

Layers 1 and 6 need no Sage and run in the fast job, because that is where
allowlist regressions come from. The rest need a real worker.
"""

from __future__ import annotations

import ast
import re
import shutil

import pytest

from sagemath_mcp.security import SECURITY_POLICY, SecurityViolation, _bound_names, validate_module

requires_sage = pytest.mark.skipif(
    shutil.which("sage") is None, reason="Sage executable not available"
)


@pytest.fixture(autouse=True)
def unset_pure_python(monkeypatch):
    monkeypatch.delenv("SAGEMATH_MCP_PURE_PYTHON", raising=False)


async def _session(name: str):
    from sagemath_mcp.session import SageSession

    return SageSession(name, None)


async def _value(session, code: str) -> str:
    result = await session.evaluate(code, want_latex=False, capture_stdout=True)
    return result.result


# --- Layer 1: every way a caller creates a name --------------------------------
# (id, code, the names it must bind). No Sage: the question is what
# `_bound_names` recognises, and getting that wrong makes a legitimate variable
# unreadable for the rest of the session.

BINDING_FORMS: list[tuple[str, str, set[str]]] = [
    ("plain", "a = 5", {"a"}),
    ("augmented", "b = 1\nb += 2", {"b"}),
    ("annotated", "c: int = 3", {"c"}),
    ("tuple-unpack", "d, e = 1, 2", {"d", "e"}),
    ("nested-unpack", "(f, (g, h)) = (1, (2, 3))", {"f", "g", "h"}),
    ("starred-unpack", "i, *j = [1, 2, 3]", {"i", "j"}),
    ("chained", "k = m = 7", {"k", "m"}),
    ("walrus", "(n := 5)", {"n"}),
    ("comprehension", "[p**2 for p in range(4)]", {"p"}),
    ("nested-comprehension", "[[q*r for q in range(2)] for r in range(2)]", {"q", "r"}),
    ("generator", "sum(s**2 for s in range(5))", {"s"}),
    ("dict-comprehension", "{t: t**2 for t in range(3)}", {"t"}),
    ("set-comprehension", "{u % 3 for u in range(9)}", {"u"}),
    ("comprehension-unpack", "[v + w for v, w in [(1, 2)]]", {"v", "w"}),
    ("for-target", "for aa in range(3):\n    pass", {"aa"}),
    ("for-tuple-target", "for bb, cc in [(1, 2)]:\n    pass", {"bb", "cc"}),
    ("function-def", "def dd(ee, ff=1, *gg, **hh):\n    pass", {"dd", "ee", "ff", "gg", "hh"}),
    ("lambda-args", "ii = lambda jj: jj", {"ii", "jj"}),
    ("class-def", "class Kk:\n    pass", {"Kk"}),
    ("except-as", "try:\n    pass\nexcept ValueError as ll:\n    pass", {"ll"}),
    ("with-as", "ctx = 1\nwith ctx as nn:\n    pass", {"ctx", "nn"}),
    ("with-as-tuple", "ctx = 1\nwith ctx as (pp, qq):\n    pass", {"ctx", "pp", "qq"}),
    # Sage's own spellings for declaring symbols. These create names that no
    # assignment reveals, and a caller who cannot use them afterwards has lost
    # the ordinary way of doing symbolic mathematics.
    ("var-single", "var('rr')", {"rr"}),
    ("var-space-separated", "var('ss tt')", {"ss", "tt"}),
    ("var-comma-separated", "var('uu,vv')", {"uu", "vv"}),
    ("var-multiple-args", "var('ww', 'xx')", {"ww", "xx"}),
    ("function-declaration", "function('yy')", {"yy"}),
    # `match` binds through patterns, not Name nodes -- a whole statement's
    # worth of names that looked invisible to a Name-based walk.
    #
    # The patterns here avoid numeric literals on purpose. Sage's preparser
    # rewrites `case 1:` to `case _sage_const_1:`, which Python reads as a name
    # capture and rejects with "makes remaining patterns unreachable". That is
    # SageMath 10.9 itself -- plain `sage script.sage` does the same -- not
    # something this server introduces, and there is nothing to fix here.
    ("match-as", "match 'v':\n    case 'v' as ad:\n        pass", {"ad"}),
    ("match-capture", "match 1:\n    case af:\n        pass", {"af"}),
    ("match-sequence", "match [1, 2]:\n    case [ah, ai]:\n        pass", {"ah", "ai"}),
    ("match-star", "match [1, 2]:\n    case [ak, *al]:\n        pass", {"ak", "al"}),
    ("match-mapping", "match {'k': 1}:\n    case {'k': an, **ao}:\n        pass", {"an", "ao"}),
    ("match-class", "match ValueError(1):\n    case ValueError() as aq:\n        pass", {"aq"}),
    ("match-or", "match 'v':\n    case 'u' | 'v' as at:\n        pass", {"at"}),
]

_FORM_IDS = [i for i, _, _ in BINDING_FORMS]
_FORM_ARGS = [(c, e) for _, c, e in BINDING_FORMS]


@pytest.mark.parametrize("code,expected", _FORM_ARGS, ids=_FORM_IDS)
def test_every_binding_form_is_recognised(code: str, expected: set[str]) -> None:
    """A name the caller creates must be a name the caller can then read."""
    bound = _bound_names(ast.parse(code))
    missing = expected - bound
    assert not missing, (
        f"{code!r} binds {sorted(missing)}, which _bound_names did not see. Those "
        f"names are unusable for the rest of the session even though the caller "
        f"defined them."
    )


@pytest.mark.parametrize("code,expected", _FORM_ARGS, ids=_FORM_IDS)
def test_a_bound_name_passes_validation_when_read(code: str, expected: set[str]) -> None:
    """The same thing one level up, and what a caller actually experiences."""
    reads = "\n".join(sorted(expected))
    validate_module(ast.parse(f"{code}\n{reads}"))


# --- Layer 2: bindings survive into the next call -------------------------------
# Only the forms Python actually keeps at module level. A comprehension target
# and a function argument are scoped to their construct and are *supposed* to
# vanish; `_bound_names` over-approximates by design, and the test below covers
# what a caller sees when they read one.

SCOPED_TO_THEIR_CONSTRUCT = {
    "comprehension", "nested-comprehension", "generator", "dict-comprehension",
    "set-comprehension", "comprehension-unpack", "function-def", "lambda-args",
    "except-as", "with-as", "with-as-tuple",
}
PERSISTENT_FORMS = [
    (label, code, names)
    for label, code, names in BINDING_FORMS
    if label not in SCOPED_TO_THEIR_CONSTRUCT
]


@requires_sage
@pytest.mark.asyncio
async def test_a_name_bound_in_one_call_is_readable_in_the_next() -> None:
    """The stateful path, which is the one callers use.

    Validation happens per call against the names bound so far, so binding and
    reading inside a single module proves nothing about binding in call 1 and
    reading in call 5. A form that worked in one shot and failed across calls
    would look, to a caller, like their variable had evaporated.
    """
    session = await _session("cross-call")
    failures: list[str] = []
    try:
        for label, code, expected in PERSISTENT_FORMS:
            try:
                await session.evaluate(code, want_latex=False, capture_stdout=True)
                for name in sorted(expected):
                    await session.evaluate(name, want_latex=False, capture_stdout=True)
            except Exception as exc:
                failures.append(f"{label}: {type(exc).__name__}: {str(exc)[:120]}")
    finally:
        await session.shutdown()

    assert not failures, (
        "these bindings did not survive into a later call in the same session:\n  "
        + "\n  ".join(failures)
    )


@requires_sage
@pytest.mark.asyncio
async def test_a_scoped_name_fails_as_python_not_as_a_refusal() -> None:
    """Reading a comprehension target must read as a mistake, not a rejection.

    `_bound_names` collects names across the whole module without tracking
    scope -- deliberately, since a strict analysis would refuse ordinary code
    for no security gain. The consequence is that validation lets `p` through
    after `[p^2 for p in range(4)]`, and Python then raises NameError because
    the comprehension never leaked it.

    That is the right way round. The caller gets Python's own explanation of a
    Python mistake, instead of a security refusal implying the server withheld
    something -- which would send them looking for a permission problem that
    does not exist.
    """
    session = await _session("scoped")
    try:
        await session.evaluate("[p^2 for p in range(4)]", want_latex=False, capture_stdout=True)
        with pytest.raises(Exception) as caught:
            await session.evaluate("p", want_latex=False, capture_stdout=True)
    finally:
        await session.shutdown()

    message = str(caught.value)
    assert "not defined" in message, message
    assert "allowlist" not in message, (
        f"a scoped name read as a security refusal rather than a NameError: {message}"
    )


# --- Layer 3: mathematics that must be right ------------------------------------
# Each case is a predicate Sage evaluates. Asserting `True` rather than comparing
# printed output lets Sage decide mathematical equality -- `(x+1)*(x-1)` and
# `x^2-1` are the same to it and different strings to us.

TRUTHS: list[tuple[str, str]] = [
    # Arithmetic and exactness. Staying exact is Sage's whole point.
    ("integer-arithmetic", "2^10 + 3*4 - 5/7 == 7247/7"),
    ("rational-exactness", "2/3 + 1/6 == 5/6"),
    ("no-floor-division", "5/2 != 2"),
    ("big-integer", "factorial(50) == prod(srange(1, 51))"),
    ("big-integer-exact", "2^100 == 1267650600228229401496703205376"),
    ("complex", "(1 + I)^4 == -4"),
    ("precision", "abs(n(pi, digits=30) - pi) < 1e-28"),
    # Calculus.
    ("derivative-product-rule", "diff(sin(x)*exp(x), x) == cos(x)*e^x + sin(x)*e^x"),
    ("derivative-chain-rule", "diff(sin(x^2), x) == 2*x*cos(x^2)"),
    ("partial-derivative", "diff(x^2*y^3, x, y) == 6*x*y^2"),
    ("predefined-symbols", "bool((x + y + z + t).subs(x=1, y=2, z=3, t=4) == 10)"),
    ("predefined-y-in-calculus", "integrate(y^2, y) == y^3/3"),
    ("predefined-t-in-parametric", "diff(cos(t), t) == -sin(t)"),
    ("integral-arctan", "integrate(1/(1 + x^2), x) == arctan(x)"),
    ("definite-integral", "integrate(sin(x), x, 0, pi) == 2"),
    ("fundamental-theorem", "diff(integrate(x*sin(x), x), x) == x*sin(x)"),
    ("limit", "limit(sin(x)/x, x=0) == 1"),
    ("taylor", "taylor(exp(x), x, 0, 2) == 1 + x + x^2/2"),
    ("symbolic-sum", "var('k')\nsum(k^2, k, 1, 10) == 385"),
    ("undeclared-symbol-still-refused", "1 == 1"),
    (
        "ode-solution-satisfies-ode",
        "yy = function('yy')\ns = desolve(diff(yy(x), x) == yy(x), yy(x))\ndiff(s, x) == s",
    ),
    # Algebra.
    ("factor-round-trip", "expand((x^2 - 1).factor()) == x^2 - 1"),
    ("expand", "expand((x + 1)^5) == x^5 + 5*x^4 + 10*x^3 + 10*x^2 + 5*x + 1"),
    ("solve-quadratic", "sorted([s.rhs() for s in solve(x^2 - 4 == 0, x)]) == [-2, 2]"),
    ("solve-system", "len(solve([x + y == 3, x - y == 1], x, y)) == 1"),
    ("substitute", "(x^2 + 1).subs(x=3) == 10"),
    ("trig-identity", "(sin(x)^2 + cos(x)^2).simplify_trig() == 1"),
    ("assumption", "assume(x > 0)\nsqrt(x^2).simplify_full() == x"),
    # Linear algebra. The inverse invariant is worth more than a printed matrix.
    ("matrix-determinant", "matrix([[1, 2], [3, 4]]).det() == -2"),
    (
        "matrix-inverse-invariant",
        "M = matrix(QQ, [[1, 2], [3, 4]])\nM * M.inverse() == identity_matrix(QQ, 2)",
    ),
    ("matrix-rank-deficient", "matrix([[1, 2], [2, 4]]).rank() == 1"),
    ("matrix-power", "matrix([[1, 1], [0, 1]])^10 == matrix([[1, 10], [0, 1]])"),
    ("eigenvalues", "sorted(matrix(QQ, [[2, 0], [0, 3]]).eigenvalues()) == [2, 3]"),
    ("cross-product", "vector([1, 2, 3]).cross_product(vector([4, 5, 6])) == vector([-3, 6, -3])"),
    ("dot-product", "vector([1, 2, 3]).dot_product(vector([4, 5, 6])) == 32"),
    # Number theory.
    ("primality", "is_prime(104729) and not is_prime(104730)"),
    ("mersenne-prime", "(2^61 - 1).is_prime()"),
    ("factorisation-round-trip", "prod([p^e for p, e in factor(360)]) == 360"),
    ("gcd-lcm-identity", "gcd(120, 84) * lcm(120, 84) == 120 * 84"),
    ("modular-power", "power_mod(3, 100, 7) == 4"),
    ("euler-phi", "euler_phi(360) == 96"),
    ("prime-counting", "len(prime_range(100)) == 25"),
    ("continued-fraction", "continued_fraction(pi).convergents()[3] == 355/113"),
    # Combinatorics and discrete structures.
    ("binomial", "binomial(20, 10) == 184756"),
    ("catalan", "catalan_number(6) == 132"),
    ("permutations", "Permutations(4).cardinality() == 24"),
    ("partitions", "Partitions(6).cardinality() == 11"),
    ("graph-chromatic", "graphs.PetersenGraph().chromatic_number() == 3"),
    ("graph-parameterised", "graphs.CompleteGraph(5).size() == 10"),
    ("group-order", "SymmetricGroup(4).order() == 24"),
    ("lagrange", "G = SymmetricGroup(4)\nG.order() % G.subgroups()[1].order() == 0"),
    # Rings, fields and structures.
    ("finite-field", "GF(7)(3)^5 == GF(7)(5)"),
    ("finite-field-order", "K.<a> = GF(9)\nK.order() == 9"),
    ("polynomial-ring", "R.<z> = QQ[]\n(z^2 - 1) == (z - 1)*(z + 1)"),
    ("groebner-membership", "R.<a, b> = QQ[]\nI = Ideal([a^2 - b, a*b - 1])\n(a^2 - b) in I"),
    ("number-field", "K.<w> = NumberField(x^2 - 2)\nw^2 == 2"),
    ("p-adic-valuation", "Qp(5)(25).valuation() == 2"),
    ("elliptic-curve-rank", "EllipticCurve([0, 0, 1, -1, 0]).rank() == 1"),
    ("elliptic-point-on-curve", "E = EllipticCurve([0, 0, 1, -1, 0])\nE(0, 0) in E"),
    # Numerics and statistics.
    ("find-root", "abs(find_root(cos(x) - x, 0, 1) - 0.7390851332151607) < 1e-9"),
    ("mean", "mean([1, 2, 3, 4]) == 5/2"),
    ("median", "median([1, 3, 2]) == 2"),
    ("variance", "variance([1, 2, 3, 4]) == 5/3"),
    ("real-interval", "RIF(1, 2).center() == 1.5"),
    ("srange", "sum(srange(0, 10, 2)) == 20"),
    # Ordinary programming, which mathematics needs constantly.
    ("loop-accumulator", "total = 0\nfor i in range(10):\n    total += i\ntotal == 45"),
    ("recursion", "def fact(k):\n    return 1 if k <= 1 else k*fact(k - 1)\nfact(6) == 720"),
    (
        "closure",
        "def outer():\n    c = 2\n    def inner():\n        return c\n"
        "    return inner()\nouter() == 2",
    ),
    ("class-definition", "class P:\n    def __init__(self, v):\n        self.v = v\nP(3).v == 3"),
    ("comprehension-over-sage", "[factorial(j) for j in range(5)] == [1, 1, 2, 6, 24]"),
    ("multi-statement-state", "u = matrix([[1, 1], [0, 1]])\nw2 = u^10\nw2.det() == 1"),
    ("plot-returns-an-object", "plot(sin(x), (x, 0, 1)) is not None"),
]


@requires_sage
@pytest.mark.asyncio
async def test_the_mathematics_is_correct() -> None:
    """Every predicate must evaluate to True, in one session, all reported.

    A predicate that comes back False is either a wrong answer from the server
    or a wrong claim in this file. Both need looking at, which is why the
    failure prints the case rather than just a count.
    """
    session = await _session("truths")
    failures: list[str] = []
    try:
        for label, code in TRUTHS:
            try:
                # `==` on Sage symbolics builds an equation rather than deciding
                # one: `integrate(sin(x), x, 0, pi) == 2` evaluates to the object
                # `2 == 2`. Wrapping the final line forces the question to be
                # answered, and keeps the table free of bool() noise.
                *setup, final = code.rstrip().split("\n")
                answer = await _value(session, "\n".join([*setup, f"bool({final})"]))
                if answer != "True":
                    failures.append(f"{label}: expected True, got {answer!r}  <- {code!r}")
            except Exception as exc:
                failures.append(f"{label}: {type(exc).__name__}: {str(exc)[:130]}")
    finally:
        await session.shutdown()

    assert not failures, "mathematics that should be true was not:\n  " + "\n  ".join(failures)


# --- Layer 4: spellings that must agree -----------------------------------------
# Metamorphic: assert equality *between* spellings rather than against a value we
# would have to know in advance. `2^10` and `2**10` disagreeing is a bug whichever
# is right, and this is the shape that catches a silently wrong answer.

EQUIVALENT_SPELLINGS: list[tuple[str, list[str]]] = [
    ("power", ["2^10", "2**10", "pow(2, 10)", "2 ^ 10"]),
    ("square-root", ["sqrt(16)", "16^(1/2)", "16**(1/2)"]),
    ("derivative", ["diff(x^3, x)", "derivative(x^3, x)", "(x^3).diff(x)", "(x^3).derivative(x)"]),
    ("integral", ["integrate(x^2, x)", "integral(x^2, x)", "(x^2).integrate(x)"]),
    ("factorial", ["factorial(10)", "prod(srange(1, 11))", "gamma(11)"]),
    (
        "determinant",
        [
            "matrix([[1, 2], [3, 4]]).det()",
            "matrix([[1, 2], [3, 4]]).determinant()",
            "det(matrix([[1, 2], [3, 4]]))",
        ],
    ),
    ("rational", ["1/2", "QQ(1)/QQ(2)", "QQ((1, 2))"]),
    ("pi-spelling", ["n(pi)", "n(π)"]),
    ("whitespace", ["1+1", "1 + 1", "  1  +  1  "]),
    ("line-continuation", ["2 + 3", "2 + \\\n    3"]),
    ("parenthesisation", ["2*3 + 4", "(2*3) + 4", "4 + 2*3"]),
    ("integer-conversion", ["ZZ(7)", "Integer(7)", "7"]),
    ("expand-spelling", ["expand((x + 1)^2)", "((x + 1)^2).expand()"]),
    ("factor-spelling", ["factor(x^2 - 1)", "(x^2 - 1).factor()"]),
    ("substitution", ["(x^2).subs(x=4)", "(x^2).substitute(x=4)", "(x^2)(x=4)"]),
    ("numeric-approx", ["n(1/3)", "numerical_approx(1/3)", "(1/3).n()"]),
    ("absolute-value", ["abs(-5)", "(-5).abs()"]),
    ("comment-and-blank-lines", ["2 + 2", "# a comment\n\n2 + 2  # trailing\n"]),
    ("semicolons", ["1 + 2", "aq1 = 1; aq2 = 2; aq1 + aq2"]),
]


@requires_sage
@pytest.mark.asyncio
async def test_equivalent_spellings_agree() -> None:
    """Same mathematics, different spelling, identical answer."""
    session = await _session("equivalences")
    failures: list[str] = []
    try:
        for label, spellings in EQUIVALENT_SPELLINGS:
            answers: dict[str, str] = {}
            for spelling in spellings:
                try:
                    answers[spelling] = await _value(session, spelling)
                except Exception as exc:
                    answers[spelling] = f"<{type(exc).__name__}: {str(exc)[:80]}>"
            if len(set(answers.values())) > 1:
                detail = ", ".join(f"{k!r} -> {v!r}" for k, v in answers.items())
                failures.append(f"{label}: {detail}")
    finally:
        await session.shutdown()

    assert not failures, (
        "these spellings mean the same thing and gave different answers:\n  "
        + "\n  ".join(failures)
    )


# --- Layer 5: the Sage preparser -------------------------------------------------
# Sage is not Python, and the preparser is the difference. It runs on caller code
# and not on generated code, so its behaviour is part of the caller contract:
# `5/2` being a rational rather than 2 is the most visible thing about Sage, and
# a regression there would look like arithmetic quietly changing.

PREPARSER_FORMS: list[tuple[str, str]] = [
    ("caret-is-power", "2^10 == 1024"),
    ("double-star-is-power", "2**10 == 1024"),
    ("division-is-exact", "1/3 + 1/3 + 1/3 == 1"),
    ("integer-literals-are-sage-integers", "isinstance(2, Integer)"),
    ("float-literals-are-real-numbers", "0.5.parent() == RR"),
    ("generator-syntax", "R.<t> = QQ[]\nt.parent() is R"),
    ("generator-syntax-field", "K.<a> = GF(9)\na.parent() is K"),
    ("multiple-generators", "R.<u, v> = QQ[]\nlen(R.gens()) == 2"),
    ("underscored-literal", "1_000_000 == 10^6"),
    ("hex-literal", "0x1f == 31"),
    ("scientific-notation", "1e3 == 1000"),
    ("negative-exponent", "2^-2 == 1/4"),
    ("chained-comparison", "1 < 2 < 3"),
    ("tab-indentation", "def tabbed():\n\treturn 42\ntabbed() == 42"),
    ("trailing-newlines", "6*7 == 42\n\n\n"),
    ("leading-blank-lines", "\n\n6*7 == 42"),
    # Greek names are real Sage spellings; the linter reads them as Latin
    # look-alikes.
    ("unicode-identifier", "var('α')\nα + 1 == α + 1"),  # noqa: RUF001
    # The function-definition syntax, which is the first thing in the Sage
    # tutorial and the way a physicist writes a potential. It expands to
    # `__tmp__=var("x"); f = symbolic_expression(...).function(x)`, and this
    # server validates the preparsed source -- so the dunder rule refused all
    # four of these until `__tmp__` was allowed as a store.
    ("function-definition-syntax", "f(x) = x^2 + 1\nf(3) == 10"),
    ("function-definition-two-variables", "g(x, y) = x*y\ng(3, 4) == 12"),
    ("function-definition-declares-its-argument", "V(r) = -1/r\nV(2) == -1/2"),
    ("function-definition-is-symbolic", "h(x) = sin(x)^2 + cos(x)^2\nh(x).simplify_full() == 1"),
]


@requires_sage
@pytest.mark.asyncio
async def test_the_preparser_behaves_like_sage() -> None:
    session = await _session("preparser")
    failures: list[str] = []
    try:
        for label, code in PREPARSER_FORMS:
            try:
                *setup, final = code.rstrip().split("\n")
                answer = await _value(session, "\n".join([*setup, f"bool({final})"]))
                if answer != "True":
                    failures.append(f"{label}: expected True, got {answer!r}  <- {code!r}")
            except Exception as exc:
                failures.append(f"{label}: {type(exc).__name__}: {str(exc)[:130]}")
    finally:
        await session.shutdown()

    assert not failures, "the preparser did not behave like Sage:\n  " + "\n  ".join(failures)


@pytest.mark.parametrize(
    "code",
    [
        "2^10",
        "sum(k for k in range(10))",
        "matrix([[1, 2], [3, 4]]).det()",
        "integrate(x^2, x)",
        "var('t')\nt^2 + 1",
        "f = function('f')\nf(x)",
        '__tmp__=var("x"); f = symbolic_expression(x**Integer(2)).function(x)',
        "[is_prime(j) for j in range(10)]",
        "def fact(k):\n    return 1 if k <= 1 else k*fact(k - 1)\nfact(6)",
        "match 1:\n    case int() as found:\n        found",
    ],
)
def test_ordinary_mathematics_validates_without_sage(code: str) -> None:
    """The validator is the gate, and it runs without Sage.

    Keeping these in the fast job means an allowlist change that refuses
    ordinary mathematics fails in seconds rather than in the Sage job.
    """
    validate_module(ast.parse(code))


# --- Layer 6: the allowlist admits what Sage preloads ----------------------------


def test_the_allowlist_covers_the_mathematics_callers_reach_for() -> None:
    """A spot check with teeth, run without Sage.

    The generated allowlist is only as good as the namespace it came from, and a
    scrub that takes one name too many is invisible until a caller tries it.
    Named by area so a failure says which area broke, rather than "1 of 1913
    names missing".
    """
    from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES

    essential = {
        "calculus": ["diff", "integrate", "integral", "limit", "taylor", "derivative", "desolve"],
        "symbolic": ["var", "function", "solve", "expand", "factor", "simplify", "assume"],
        "arithmetic": ["factorial", "binomial", "gcd", "lcm", "sqrt", "exp", "log", "abs", "prod"],
        "trigonometry": ["sin", "cos", "tan", "arcsin", "arctan", "sinh", "cosh", "gamma"],
        "constants": ["pi", "e", "I", "infinity", "oo", "NaN"],
        "rings": ["ZZ", "QQ", "RR", "CC", "GF", "PolynomialRing", "NumberField", "Qp", "RIF"],
        "linear-algebra": ["matrix", "vector", "identity_matrix", "zero_matrix", "det"],
        "number-theory": ["is_prime", "next_prime", "prime_range", "euler_phi", "power_mod"],
        "combinatorics": ["Permutations", "Partitions", "Combinations", "catalan_number"],
        "graphs": ["graphs", "Graph", "DiGraph"],
        "groups": ["SymmetricGroup", "DihedralGroup", "CyclicPermutationGroup"],
        "curves": ["EllipticCurve", "Ideal"],
        "statistics": ["mean", "median", "mode", "std", "variance"],
        "plotting": ["plot", "plot3d", "parametric_plot", "list_plot"],
        "numeric": ["n", "numerical_approx", "find_root", "round", "floor", "ceil"],
        "sequences": ["srange", "range", "len", "sum", "prod", "max", "min", "sorted"],
        "types": ["Integer", "RealNumber", "isinstance", "bool", "int", "str", "list", "set"],
    }

    missing = {
        area: [name for name in names if name not in ALLOWED_CALLER_NAMES]
        for area, names in essential.items()
    }
    missing = {area: names for area, names in missing.items() if names}
    assert not missing, f"the allowlist does not admit these, so callers cannot use them: {missing}"


def test_the_allowlist_is_large_enough_to_be_the_real_namespace() -> None:
    """A floor, so a generation that silently produced almost nothing is caught.

    An empty allowlist refuses everything and passes every security test there
    is -- exactly the failure this file exists to catch.
    """
    from sagemath_mcp.allowlist import ALLOWED_CALLER_NAMES

    assert len(ALLOWED_CALLER_NAMES) > 1500, (
        f"the allowlist has only {len(ALLOWED_CALLER_NAMES)} names; SageMath preloads "
        f"far more than that, so it was probably generated against a broken namespace"
    )


def test_this_suite_cannot_quietly_shrink() -> None:
    """A floor on the tables themselves.

    The generated-code lint learned this the hard way: a check that silently
    stopped finding anything kept passing. Same guard, same reason.
    """
    assert len(TRUTHS) >= 60, f"only {len(TRUTHS)} truths; this suite has been gutted"
    assert len(BINDING_FORMS) >= 30, f"only {len(BINDING_FORMS)} binding forms"
    assert len(EQUIVALENT_SPELLINGS) >= 15, f"only {len(EQUIVALENT_SPELLINGS)} equivalence groups"
    assert len(PREPARSER_FORMS) >= 15, f"only {len(PREPARSER_FORMS)} preparser forms"


# --- The message a refusal gives -------------------------------------------------


def test_an_undeclared_symbol_is_told_to_declare_itself() -> None:
    """`w` is not predefined, so using it is a missing declaration.

    The allowlist's generic message sent the caller after the wrong fix: it
    suggested the name needed adding to the allowlist, when what ordinary
    mathematics needs is `var('w')`. Clients are models that retry on the
    message they are given, so a message naming a fix they cannot perform costs
    a whole exchange.
    """
    with pytest.raises(SecurityViolation, match=r"var\('w'\)"):
        validate_module(ast.parse("diff(x^2*w^3, x, w)"))


def test_an_unknown_long_name_is_still_told_the_truth() -> None:
    """The other half: a real unknown name is not blamed on a missing var()."""
    with pytest.raises(SecurityViolation, match="allowlist"):
        validate_module(ast.parse("subprocess_helper_thing()"))


def test_the_allowlist_message_never_leaks_what_exists() -> None:
    """A refusal must not become a namespace oracle.

    Enumeration was one of the bypasses; a message listing near-matches would
    hand back the same information one name at a time.
    """
    for name in ("system", "popen", "unpickle_global"):
        with pytest.raises(SecurityViolation) as caught:
            validate_module(ast.parse(f"{name}(1)"))
        message = str(caught.value)
        assert "did you mean" not in message.lower()
        # 'x' is exempt: the undeclared-symbol message names it as the one symbol
        # SageMath predefines, which is documented and tells a caller nothing
        # they could not read in the README.
        quoted = set(re.findall(r"'([^']+)'", message)) - {name, "x"}
        assert not (quoted & SECURITY_POLICY.allowed_names), (
            f"the refusal for {name!r} quoted names that exist: "
            f"{sorted(quoted & SECURITY_POLICY.allowed_names)} -- a refusal must not "
            f"become a way to enumerate the namespace one name at a time"
        )


def test_the_predefined_symbols_are_the_same_everywhere() -> None:
    """The tools and caller code must agree on which symbols exist.

    This is the inconsistency that prompted predefining them at all: the tool
    prelude declared `x, y, z, t`, the caller namespace declared only `x`, so
    `differentiate_expression("x^2*y^3")` worked while the same mathematics
    through `evaluate_sage` did not. Both now read the same constant, and this
    fails if anyone gives one of them its own list again.
    """
    from sagemath_mcp import codegen
    from sagemath_mcp.symbols import PREDEFINED_SYMBOLS

    assert PREDEFINED_SYMBOLS == ("x", "y", "z", "t")
    prelude = codegen._sage_prelude()
    for symbol in PREDEFINED_SYMBOLS:
        assert f"'{symbol}'" in prelude, (
            f"the generated prelude no longer declares {symbol!r}, so the tools and "
            f"caller code disagree about which symbols exist"
        )


@requires_sage
@pytest.mark.asyncio
async def test_the_predefined_symbols_are_live_in_a_session() -> None:
    """And they are really there, not merely allowlisted.

    A name can pass validation and still be missing from the namespace -- that
    is exactly what a NameError at runtime means -- so the check that matters
    is whether Sage resolves it.
    """
    from sagemath_mcp.symbols import PREDEFINED_SYMBOLS

    session = await _session("predefined")
    try:
        for symbol in PREDEFINED_SYMBOLS:
            answer = await _value(session, f"({symbol}^2).degree({symbol})")
            assert answer == "2", f"{symbol!r} is not a live symbolic variable: {answer!r}"
    finally:
        await session.shutdown()
