"""What a refusal says: the messages and the spellings they point to.

A refusal names the rule it broke and, where there is one, the spelling that
works -- the public name for an internal one, the in-process mathematics for
an external interface. None of this decides anything; the validator does.
"""

from __future__ import annotations

from ._artifacts import ALLOWED_CALLER_NAMES


def format_violation(message: str, code: str | None) -> str:
    if not code:
        return message
    snippet = code.strip().splitlines()
    if snippet:
        snippet = snippet[:3]
        joined = " / ".join(line.strip() for line in snippet if line.strip())
        return f"{message} [snippet: {joined}]"
    return message


# What to reach for instead, when an import asks for something this server does
# not offer. A refusal that names the alternative costs the caller nothing; one
# that says only "disabled" costs an exchange, and models do not always recover
# from it -- three physics cases were lost to exactly that.
_IMPORT_ALTERNATIVES: tuple[tuple[str, str], ...] = (
    ("numpy", "SageMath's own arrays: matrix(RDF, ...), vector(RDF, ...), srange"),
    ("scipy", "numerical_integral, find_root, desolve_odeint, minimize"),
    ("sympy", "SageMath is a superset: var(), integrate(), solve(), simplify()"),
    ("matplotlib", "plot(), plot3d(), list_plot(), parametric_plot()"),
    ("math", "sqrt, exp, log, pi and the rest are already available"),
    ("cmath", "ComplexField, I, and the usual functions are already available"),
    ("random", "random(), randint(), shuffle(), sample(), set_random_seed()"),
    ("fractions", "QQ and Rational are already available"),
    ("decimal", "RealField(precision) is already available"),
    ("statistics", "mean, median, variance, std are already available"),
    ("itertools", "product, permutations and combinations of Sage's own"),
    # Both found by the 2026-09-15 tool-surface measurement: Gemini reached for
    # mpmath in the high-precision physics cases and lost four of them to a
    # refusal that named no alternative.
    ("mpmath", "RealField(prec) and RealBallField(prec) for high precision, "
               "numerical_integral, find_root, and N(expr, digits=...) on an "
               "exact expression"),
    ("functools", "reduce is already available"),
)


# The mathematics behind a name this server does not offer. Every entry is a
# spelling that works, and `test_the_blocked_interfaces_do_not_block_the_
# mathematics` computes each one -- this is writing down what that test knows.
#
# It matters because of who is reading. A refusal that says only "not offered"
# leaves a model to guess, and the guess is usually another spelling of the same
# refused thing; naming the equivalent ends the exchange. ~2,300 of the refusals
# SageMath's own doctests provoke are these names.
_NATIVE_EQUIVALENTS: dict[str, str] = {
    # The external CAS interfaces. Each spawns the real program and hands it a
    # string; Sage computes all of it in-process as well.
    "gap": "SymmetricGroup(5), PermutationGroup([...]) and the group methods",
    "gap3": "the native group methods",
    "libgap": "the group methods usually answer directly: SymmetricGroup(5), "
              "PermutationGroup([...]), and .order(), .gens(), .subgroups()",
    "singular": "ideal(...).groebner_basis(), .primary_decomposition() and the "
                "polynomial ring methods",
    "maxima": "integrate(), limit(), desolve(), factor() and solve() -- all of "
              "which use Maxima in process",
    "gp": "the number theory functions directly: factor(), is_prime(), "
          "qfbclassno via QuadraticField(...).class_number()",
    "pari": "the number theory functions directly, or the .pari() method on a "
            "Sage object",
    "magma": "Sage's own algebra: PolynomialRing, NumberField, EllipticCurve",
    "mathematica": "Sage's own symbolics: var(), integrate(), solve(), simplify()",
    "maple": "Sage's own symbolics: var(), integrate(), solve(), simplify()",
    "matlab": "matrix(RDF, ...) and the numerical linear algebra methods",
    "octave": "matrix(RDF, ...) and the numerical linear algebra methods",
    "macaulay2": "ideal(...).groebner_basis() and the polynomial ring methods",
    "r": "RealDistribution, mean(), variance(), find_fit() and statistics_summary",
    "fricas": "Sage's own symbolics: var(), integrate(), solve()",
    "giac": "Sage's own symbolics: var(), integrate(), solve()",
    "sage0": "the mathematics directly; there is no second Sage to talk to",
    # String-path attribute access, which is refused as a class.
    # Only the dynamic form still reaches this advice: a screened literal --
    # attrcall('bruhat_le') -- is accepted outright.
    "attrcall": "a literal attribute name, or a lambda: lambda a, b: a.bruhat_le(b)",
    "attrgetter": "a lambda, or the attribute directly",
    "methodcaller": "a lambda: methodcaller('trace') is lambda m: m.trace()",
    "itemgetter": "a lambda: itemgetter(0) is lambda s: s[0]",
    # Session and display plumbing.
    "show": "the value itself -- results come back as text, and the plot tools "
            "return an image",
    "view": "the value itself, or plot() for a picture",
    "pretty_print": "the value itself",
    "html": "the value itself",
    "reset": "the reset_sage_session tool, which restarts the worker cleanly",
    "set_verbose": "nothing -- progress is reported by the streaming tool",
    "load": "the value directly; this server keeps state between calls instead",
    "save": "the value directly; this server keeps state between calls instead",
}


def native_equivalent(name: str) -> str | None:
    return _NATIVE_EQUIVALENTS.get(name)


# Names a model writes that SageMath does not have, and how Sage spells them.
# Distinct from _NATIVE_EQUIVALENTS: nothing here is withheld -- these names do
# not exist in Sage at all (a NameError at the REPL), so the refusal that stops
# them is the deny-by-default "not a name this server offers", and the fix is a
# spelling, not a policy. They come from watching models work: the 2026-09-15
# tool-surface measurement lost `partitions` three times and `bessel_J_zeros`
# twice, each to a refusal that suggested checking for a typo; the rest are the
# SymPy, NumPy and SciPy spellings a model reaches for first.
#
# Every entry is verified against real Sage by
# `test_every_sage_spelling_hint_computes`: the key must be absent from the
# worker namespace (if a Sage release adds it, the entry must go) and the
# spelling must compute. Names recommended here must be on the allowlist --
# advising a refused spelling would be worse than none.
_SAGE_SPELLINGS: dict[str, str] = {
    "partitions": "Partitions(n).cardinality() or number_of_partitions(n)",
    "npartitions": "number_of_partitions(n)",
    "bessel_J_zeros": "find_root(bessel_J(0, x), a, b) with a bracket [a, b] around the "
                      "zero (the first zero of J_0 lies in [2, 3])",
    "besseljzero": "find_root(bessel_J(0, x), a, b) with a bracket [a, b] around the zero",
    "jn_zeros": "find_root(bessel_J(0, x), a, b) with a bracket [a, b] around the zero",
    "isprime": "is_prime(n)",
    "is_prime_number": "is_prime(n)",
    "nextprime": "next_prime(n)",
    "primerange": "prime_range(a, b)",
    "primefactors": "prime_divisors(n), or factor(n) for the factorisation",
    "factorint": "factor(n)",
    "totient": "euler_phi(n)",
    "divisor_count": "number_of_divisors(n)",
    "gcdex": "xgcd(a, b)",
    "nCr": "binomial(n, k)",
    "bell": "bell_number(n)",
    "stirling": "stirling_number1(n, k) or stirling_number2(n, k)",
    "symbols": "var('a b c')",
    "Symbol": "var('a')",
    "Poly": "PolynomialRing(QQ, 't'), or R.<t> = QQ[]",
    "summation": "sum(f, k, a, b) for a symbolic sum, sum(list) for a finite one",
    "Sum": "sum(f, k, a, b) for a symbolic sum, sum(list) for a finite one",
    "nsolve": "find_root(f, a, b), or solve(f == 0, x) for an exact answer",
    "linspace": "srange(a, b, step), or [a + (b - a)*i/n for i in range(n + 1)]",
}


def sage_spelling(name: str) -> str | None:
    return _SAGE_SPELLINGS.get(name)


def import_alternative(module: str) -> str | None:
    root = (module or "").split(".", 1)[0]
    for name, advice in _IMPORT_ALTERNATIVES:
        if root == name:
            return advice
    return None


def reach_refusal(segments: list[str]) -> str:
    """Why this chain is refused, and what the caller can actually do instead.

    The original message said "name the function directly" for every chain.
    `scripts/analyse_module_reach.py` measured what that advice was worth: of
    the 1,090 corpus examples the rule refuses, 835 reach a leaf offered under
    no spelling at all, so the one instruction given was the one instruction
    that could not be followed. `sage.rings.ideal.Katsura` is mathematics, and
    there was no `Katsura` to name.

    So the message now depends on what the leaf is. A name the server offers
    gets the original advice, which is correct for it. A name it does not gets
    told so plainly -- a caller who cannot act on a refusal should at least not
    be sent looking for something that was never there.
    """
    root = segments[0]
    leaf = segments[-1] if len(segments) > 1 else root
    if leaf in ALLOWED_CALLER_NAMES:
        return (
            f"Reaching into the '{root}' module is not permitted; "
            f"name the function directly: '{leaf}'"
        )
    return (
        f"Reaching into the '{root}' module is not permitted, and '{leaf}' is "
        "not offered under any other spelling either. If it is mathematics this "
        "server should offer, it needs to be added to the allowlist or its "
        "module screened into the permitted star exports"
    )
