"""verify_claim: the claim-checking primitive.

Two halves, mirroring how the tool is built. The unit half checks the tool's
own contract against a stub session -- the gate in front of the claim, the
payload handling, the verdict vocabulary -- and needs no Sage. The integration
half (``requires_sage``) checks the ladder itself: that real SageMath proves,
refutes, supports and declines the claims each rung exists for, including the
two honesty rules -- a prover saying False is never reported as refuted, and a
refutation always exhibits its evidence.
"""

from __future__ import annotations

import shutil

import pytest

from sagemath_mcp import runtime, server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.session import SageSessionManager

from .conftest import FakeContext
from .test_server import StubSession, _stub_manager

requires_sage = pytest.mark.skipif(
    shutil.which("sage") is None, reason="Sage executable not available"
)

PROVED_PAYLOAD = (
    "{'verdict': 'proved', 'method': 'symbolic_prover', "
    "'evidence': 'SageMath proves the relation symbolically', "
    "'samples': None, 'precision_bits': None}"
)


async def test_verify_claim_requires_context(monkeypatch):
    with pytest.raises(server.ToolError, match="MCP context"):
        await server.verify_claim("1 == 1", ctx=None)
    ctx = FakeContext()
    ctx.session_id = None
    with pytest.raises(server.ToolError, match="MCP context"):
        await server.verify_claim("1 == 1", ctx=ctx)


@pytest.mark.parametrize("claim", ["", "   "])
async def test_verify_claim_refuses_an_empty_claim(claim, monkeypatch):
    await _stub_manager(monkeypatch, StubSession(PROVED_PAYLOAD))
    with pytest.raises(server.ToolError, match="must state a comparison"):
        await server.verify_claim(claim, ctx=FakeContext())


async def test_verify_claim_reports_the_verdict(monkeypatch):
    session = StubSession(PROVED_PAYLOAD)
    await _stub_manager(monkeypatch, session)
    result = await server.verify_claim("sin(x)**2 + cos(x)**2 == 1", ctx=FakeContext())
    assert result.verdict == "proved"
    assert result.method == "symbolic_prover"
    assert result.evidence == "SageMath proves the relation symbolically"
    assert result.samples is None
    assert result.precision_bits is None
    assert result.claim == "sin(x)**2 + cos(x)**2 == 1"
    code = session.calls[0]["code"]
    assert '"sin(x)**2 + cos(x)**2 == 1"' in code
    assert "_nsamples = 12" in code
    assert "_prec = 128" in code


async def test_verify_claim_passes_the_knobs_through(monkeypatch):
    session = StubSession(
        "{'verdict': 'supported', 'method': 'numeric_sampling', "
        "'evidence': 'holds at 7 of 7 sampled points', "
        "'samples': 7, 'precision_bits': 256}"
    )
    await _stub_manager(monkeypatch, session)
    result = await server.verify_claim(
        "exp(x) >= x + 1",
        samples=7,
        precision_bits=256,
        timeout_seconds=45.0,
        ctx=FakeContext(),
    )
    assert result.verdict == "supported"
    assert result.samples == 7
    assert result.precision_bits == 256
    code = session.calls[0]["code"]
    assert "_nsamples = 7" in code
    assert "_prec = 256" in code
    assert session.calls[0]["timeout_seconds"] == 45.0


async def test_verify_claim_folds_whitespace_like_every_other_fragment(monkeypatch):
    session = StubSession(PROVED_PAYLOAD)
    await _stub_manager(monkeypatch, session)
    result = await server.verify_claim("1 + 1\n    == 2", ctx=FakeContext())
    assert result.claim == "1 + 1 == 2"


DECIMAL_REWRITES = [
    ("classic", "0.1 + 0.2 == 0.3", "(1/10) + (1/5) == (3/10)"),
    ("rounded-away", "1.0 + 1e-20 == 1.0", "(1) + (1/100000000000000000000) == (1)"),
    ("whole", "2.0 == 2", "(2) == 2"),
    ("scientific", "1.5e3 == 1500", "(1500) == 1500"),
    ("complex-untouched", "1.5j == 1.5j", "1.5j == 1.5j"),
    ("hex-untouched", "0x1e == 30", "0x1e == 30"),
    ("integers-untouched", "2 + 2 == 4", "2 + 2 == 4"),
]


@pytest.mark.parametrize(
    "claim,expected",
    [(c, e) for _, c, e in DECIMAL_REWRITES],
    ids=[i for i, _, _ in DECIMAL_REWRITES],
)
async def test_verify_claim_reads_decimal_literals_exactly(claim, expected, monkeypatch):
    """0.1 means 1/10, never the 53-bit double it would round to.

    The external review caught the bool path answering about doubles while
    calling the evidence exact: `0.1 + 0.2 == 0.3` came back refuted and
    `1.0 + 1e-20 == 1.0` came back proved. Exactness has to be preserved
    before evaluation collapses the comparison -- no later precision can
    recover digits already rounded away.
    """
    session = StubSession(PROVED_PAYLOAD)
    await _stub_manager(monkeypatch, session)
    result = await server.verify_claim(claim, ctx=FakeContext())
    assert result.claim == expected
    assert expected in session.calls[0]["code"]


def test_comparison_sides_splits_a_single_comparison():
    from sagemath_mcp.tools.verify import _comparison_sides, _exactness_probe_sources

    assert _comparison_sides("RR(1) == RR(2)") == ("RR(1)", "RR(2)", "==")
    # The equation spelling is normalized before splitting, and the sides keep
    # their ORIGINAL text -- `^` must not round-trip through the Python AST
    # (bit-xor precedence would turn `x^2 - 1` into `x^(2 - 1)`).
    lhs, rhs, op = _comparison_sides("x^2 - 1 = 0")
    assert lhs.replace(" ", "") == "x^2-1" and rhs == "0" and op == "=="
    assert _comparison_sides("e^pi != pi^e") == ("e^pi", "pi^e", "!=")
    # Greek letters: get_source_segment must return whole symbols, not a slice
    # cut mid-character by a byte offset (each letter is two UTF-8 bytes).
    alpha = chr(0x3B1)  # built from its code point so no ambiguous literal is in the source
    assert _comparison_sides(f"{alpha} == {alpha}") == (alpha, alpha, "==")
    # A bare predicate has no comparison sides; whole-claim evaluation.
    assert _comparison_sides("is_prime(7)") == (None, None, None)
    # The exactness probe surfaces the inexact input wherever it hides -- inside
    # a predicate receiver, a `== True` wrapper, or a zero-arg lambda body.
    for claim in (
        "(RR(1)+RR(1)/10^20-RR(1)).is_zero() == True",
        "(lambda: (RR(1)+RR(1)/10^20-RR(1)).is_zero())()",
    ):
        assert any("RR(1)" in s for s in _exactness_probe_sources(claim))
    assert _exactness_probe_sources(alpha) == [alpha]  # UTF-8 handled here too
    # A comparison whose operator is not one of the six ordering/equality ops
    # (membership, identity) has no proof-grade sides: whole-claim evaluation.
    assert _comparison_sides("x in (1, 2, 3)") == (None, None, None)
    # Sage-only syntax that does not parse: no sides, falls back to whole-claim.
    assert _comparison_sides("R.<a> = QQ[]") == (None, None, None)


async def test_verify_claim_accepts_the_equation_spelling(monkeypatch):
    """A single '=' is Sage's equation, not Python; the gate must let it pass."""
    session = StubSession(PROVED_PAYLOAD)
    await _stub_manager(monkeypatch, session)
    result = await server.verify_claim("x^2 - 2*x + 1 = (x - 1)^2", ctx=FakeContext())
    assert result.claim == "x^2 - 2*x + 1 = (x - 1)^2"


INJECTION_CLAIMS = [
    ("sage-eval", "sage_eval('1') == 1"),
    ("dunder-import", "__import__('os').getuid() == 0"),
    ("scrubbed-name", "unpickle_global('os','system')('id') == 0"),
    ("comment", "1 == 1 # eval('x') = __import__('os').system('id')"),
    ("semicolon", "2 == 2; _z = 1"),
    ("sage-module-walk", "sage.misc.sage_eval.sage_eval('1') == 1"),
]


@pytest.mark.parametrize(
    "claim", [c for _, c in INJECTION_CLAIMS], ids=[i for i, _ in INJECTION_CLAIMS]
)
async def test_verify_claim_rejects_injection_payloads(claim, monkeypatch):
    """The claim passes the same fragment gate as every other tool parameter."""
    await _stub_manager(monkeypatch, StubSession(PROVED_PAYLOAD))
    with pytest.raises(server.ToolError, match=r"security policy|not permitted"):
        await server.verify_claim(claim, ctx=FakeContext())


TRUTH_ASSEMBLY_CLAIMS = [
    ("not", "not (x == y)"),
    ("and", "x > 0 and x < 1"),
    ("or", "x == 0 or x == 1"),
    ("chained", "0 < x < 1"),
    ("ternary", "1 == 1 if x == y else 1 == 2"),
    ("explicit-bool", "bool(x == y)"),
    ("all", "all([x == x])"),
    ("any", "any([x == y])"),
]


@pytest.mark.parametrize(
    "claim",
    [c for _, c in TRUTH_ASSEMBLY_CLAIMS],
    ids=[i for i, _ in TRUTH_ASSEMBLY_CLAIMS],
)
async def test_verify_claim_refuses_python_truth_assembly(claim, monkeypatch):
    """Shapes where Python itself would call bool() on a symbolic relation.

    `not (x == y)` is the sharpest case: evaluation would fold the prover's
    "not proved" into False and hand back True -- a 'proved' verdict for a
    claim nothing proved. One claim, one comparison.
    """
    await _stub_manager(monkeypatch, StubSession(PROVED_PAYLOAD))
    with pytest.raises(server.ToolError, match="one comparison per claim"):
        await server.verify_claim(claim, ctx=FakeContext())


async def test_verify_claim_leaves_sage_only_spellings_to_the_preparser(monkeypatch):
    """A claim the equation rewrite still cannot parse is sage_eval's to judge."""
    session = StubSession(PROVED_PAYLOAD)
    await _stub_manager(monkeypatch, session)
    result = await server.verify_claim("x <==> y", ctx=FakeContext())
    assert result.verdict == "proved"


async def test_verify_claim_surfaces_a_ladder_error(monkeypatch):
    """A claim that is not a comparison is a loud tool error, not a verdict."""
    await _stub_manager(
        monkeypatch,
        StubSession("{'error': 'the claim must be a comparison'}"),
    )
    with pytest.raises(server.ToolError, match="must be a comparison"):
        await server.verify_claim("2 + 2", ctx=FakeContext())


async def test_verify_claim_rejects_a_non_dict_payload(monkeypatch):
    await _stub_manager(monkeypatch, StubSession("proved"))
    with pytest.raises(server.ToolError, match="unexpected verification payload"):
        await server.verify_claim("1 == 1", ctx=FakeContext())


async def test_verify_claim_rejects_an_unknown_verdict(monkeypatch):
    """The verdict vocabulary is the tool's honesty contract; nothing else passes."""
    await _stub_manager(monkeypatch, StubSession("{'verdict': 'confident'}"))
    with pytest.raises(server.ToolError, match="unexpected verdict"):
        await server.verify_claim("1 == 1", ctx=FakeContext())


# --- The ladder against real SageMath ---------------------------------------


@requires_sage
async def test_verify_claim_ladder_against_real_sage(monkeypatch):
    manager = SageSessionManager(SageSettings())
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    ctx = FakeContext("verify-claims")

    try:
        # Exact operands decide at evaluation time -- and via the preparser,
        # so ^ is exponentiation here.
        proved = await server.verify_claim("2^10 == 1024", ctx=ctx)
        assert proved.verdict == "proved"
        assert proved.method == "exact_comparison"

        refuted = await server.verify_claim("2 + 2 == 5", ctx=ctx)
        assert refuted.verdict == "refuted"
        assert refuted.method == "exact_comparison"

        # The symbolic prover.
        pythagoras = await server.verify_claim("sin(x)**2 + cos(x)**2 == 1", ctx=ctx)
        assert pythagoras.verdict == "proved"
        assert pythagoras.method in {"symbolic_prover", "exact_difference"}

        # A definite integral the prover decides.
        dirichlet = await server.verify_claim(
            "integral(sin(x)/x, x, 0, oo) == pi/2", ctx=ctx
        )
        assert dirichlet.verdict == "proved"

        # The roadmap's showcase claim. On SageMath 10.9 the integral comes
        # back with an unevaluated limit term that maxima then refuses to
        # re-read ("direction must be either 'plus' or 'minus'"), so every
        # rung is inconclusive -- and the honest answer is 'undecided', not a
        # guess. A Sage upgrade may promote it; it must never become 'refuted'.
        zeta3 = await server.verify_claim(
            "integral(x^2/(e^x-1), x, 0, oo) == 2*zeta(3)", ctx=ctx
        )
        assert zeta3.verdict in {"proved", "supported", "undecided"}

        # The documented equation spelling.
        square = await server.verify_claim("x^2 - 2*x + 1 = (x - 1)^2", ctx=ctx)
        assert square.verdict == "proved"

        # Exact arithmetic over the algebraic numbers.
        algebraic = await server.verify_claim("sqrt(2) != 3/2", ctx=ctx)
        assert algebraic.verdict == "proved"
        assert algebraic.method == "exact_algebraic"

        # A constant inequality between transcendentals: certified intervals.
        transcendental = await server.verify_claim("e^pi != pi^e", ctx=ctx)
        assert transcendental.verdict == "proved"

        # A refutation from sampling exhibits its counterexample.
        counterexample = await server.verify_claim("x + y > x", ctx=ctx)
        assert counterexample.verdict == "refuted"
        assert counterexample.method == "numeric_sampling"
        assert "counterexample" in counterexample.evidence

        # Supported, never silently promoted to proved: a true inequality the
        # prover does not decide is reported with its sample count and precision.
        bernoulli = await server.verify_claim("exp(x) >= x + 1", ctx=ctx)
        assert bernoulli.verdict in {"proved", "supported"}
        if bernoulli.verdict == "supported":
            assert bernoulli.samples and bernoulli.precision_bits

        # A true constant equality neither the prover nor the algebraic field
        # decides (Catalan's constant is not known to be algebraic): supported,
        # with the certified enclosure as the evidence.
        catalan_claim = await server.verify_claim(
            "integral(log(x)/(1+x^2), x, 0, 1) == -catalan", ctx=ctx
        )
        assert catalan_claim.verdict == "supported"
        assert catalan_claim.method == "certified_interval"
        assert catalan_claim.precision_bits == 128

        # A strict inequality whose sides are exactly equal: the enclosure of
        # lhs - rhs contains zero at every precision, so the honest answer is
        # undecided -- not refuted, which would need a certified sign.
        knife_edge = await server.verify_claim("arctan(1) < pi/4", ctx=ctx)
        assert knife_edge.verdict == "undecided"
        assert knife_edge.method == "certified_interval"

        # The honesty rule made concrete: a famous near-miss, wrong only past
        # the 30th digit, must be refuted by the certified enclosure -- while a
        # prover saying False alone would have left it undecided.
        near_miss = await server.verify_claim(
            "log(640320^3 + 744)/sqrt(163) == pi", precision_bits=256, ctx=ctx
        )
        assert near_miss.verdict == "refuted"
        assert near_miss.method == "certified_interval"
        assert "certified" in near_miss.evidence

        # External-review defect 1: a comparison over machine floats is not an
        # exact proof, however the Boolean came out. Rewriting decimal literals
        # does not make RR(...) exact -- the operands are inspected, seen to be
        # inexact, and the verdict is qualified rather than 'proved/exact'.
        float_eq = await server.verify_claim("RR(1) + RR(1)/10^20 == RR(1)", ctx=ctx)
        assert float_eq.verdict == "supported"
        assert float_eq.method == "float_comparison"
        assert "inexact" in float_eq.evidence
        # A decimal literal, by contrast, is the exact rational it denotes.
        assert (await server.verify_claim("0.1 + 0.2 == 0.3", ctx=ctx)).verdict == "proved"
        # An explicit float inequality is likewise supported, never proved.
        assert (await server.verify_claim("RR(2) > RR(1)", ctx=ctx)).method == "float_comparison"

        # External-review defect 2: a sampled counterexample must lie inside the
        # stated domain. Under an integer-domain assumption, x = 1/2 is not a
        # counterexample to x != 1/2 -- it is not an integer. The old code
        # ignored the (non-substitutable) declaration and refuted falsely.
        await server.evaluate_sage("assume(x, 'integer')", ctx=ctx, session="intdom")
        integer_dom = await server.verify_claim("x != 1/2", ctx=ctx, session="intdom")
        assert integer_dom.verdict != "refuted"
        assert "1/2" not in (integer_dom.evidence or "")

        # Not a comparison at all: loud error, not a verdict.
        with pytest.raises(server.ToolError, match="must be a comparison"):
            await server.verify_claim("2 + 2", ctx=ctx)

        # The review's decimal counterexamples, now decided about the decimals
        # the caller wrote rather than the doubles they would round to.
        decimals = await server.verify_claim("0.1 + 0.2 == 0.3", ctx=ctx)
        assert decimals.verdict == "proved"
        assert decimals.method == "exact_comparison"
        rounded = await server.verify_claim("1.0 + 1e-20 == 1.0", ctx=ctx)
        assert rounded.verdict == "refuted"
        assert rounded.method == "exact_comparison"

        # A verdict that leaned on a session assumption must say so.
        await server.evaluate_sage("assume(x > 0)", ctx=ctx, session="assumed")
        assumed = await server.verify_claim("x > 0", ctx=ctx, session="assumed")
        assert assumed.verdict == "proved"
        assert "assumptions" in assumed.evidence
        assert "x > 0" in assumed.evidence
        # ... and sampling must not exhibit a counterexample outside the
        # assumed domain: abs(x) == x is false for negative x, which the
        # assumption excludes, so every admissible sample supports it.
        restricted = await server.verify_claim("abs(x) == x", ctx=ctx, session="assumed")
        assert restricted.verdict in {"proved", "supported"}
        if restricted.verdict == "supported":
            assert "assumptions" in restricted.evidence
        # The same claim without the assumption is refuted at a negative sample.
        unrestricted = await server.verify_claim("abs(x) == x", ctx=ctx)
        assert unrestricted.verdict == "refuted"

        # External-review round 2, defect 1: exactness is a prerequisite for a
        # proof and it recurses. Wrapping an approximate value in a list or in
        # the symbolic ring does not make it exact, so neither may be 'proved'.
        boxed = await server.verify_claim("[RR(1) + RR(1)/10^20] == [RR(1)]", ctx=ctx)
        assert boxed.verdict == "supported"
        assert boxed.method == "float_comparison"
        wrapped = await server.verify_claim("SR(RR(1) + RR(1)/10^20) == 1", ctx=ctx)
        assert wrapped.verdict == "supported"
        assert wrapped.method == "float_comparison"
        # A symbolic expression built only from exact constants stays exact.
        assert (await server.verify_claim("SR(1/2) == 1/2", ctx=ctx)).verdict == "proved"
        assert (await server.verify_claim("cos(pi) == -1", ctx=ctx)).verdict == "proved"

        # External-review round 2, defect 2: the algebraic branch must not
        # conceal the assumption it leaned on. sin(pi*x) != 1 is decided exactly
        # over the algebraic numbers, but only because x is an integer -- the
        # verdict now carries that, in a structured field and in the evidence.
        await server.evaluate_sage("assume(x, 'integer')", ctx=ctx, session="algdom")
        alg = await server.verify_claim("sin(pi*x) != 1", ctx=ctx, session="algdom")
        assert alg.verdict == "proved"
        assert alg.method == "exact_algebraic"
        assert "x is integer" in alg.assumptions
        assert "integer" in (alg.evidence or "")

        # External-review round 3: two more paths that mistook a rounded result
        # for exact evidence. A dict with an inexact KEY (not just values), and a
        # bare predicate whose collapsed Boolean hid its inexact input.
        dict_key = await server.verify_claim("{RR(1)+RR(1)/10^20: 0} == {RR(1): 0}", ctx=ctx)
        assert dict_key.verdict == "supported"
        assert dict_key.method == "float_comparison"
        predicate = await server.verify_claim("(RR(1)+RR(1)/10^20-RR(1)).is_zero()", ctx=ctx)
        assert predicate.verdict == "supported"
        assert predicate.method == "float_comparison"
        # Exact bare predicates are still decided, and the `^`-precedence trap of
        # rebuilding a comparison from its parsed sides does not corrupt a true
        # identity into a refutation.
        assert (await server.verify_claim("is_prime(7)", ctx=ctx)).verdict == "proved"
        power = await server.verify_claim("x^2 - 2*x + 1 = (x - 1)^2", ctx=ctx)
        assert power.verdict == "proved"

        # External-review round 4: a Boolean's type must not establish exactness.
        # Wrapping the inexact predicate in `== True` or a zero-argument lambda
        # kept the rounding but was reported proved; exactness is now read from
        # the sub-expressions, so both qualify while their exact counterparts do
        # not.
        boolean_wrap = await server.verify_claim(
            "(RR(1)+RR(1)/10^20-RR(1)).is_zero() == True", ctx=ctx
        )
        assert boolean_wrap.verdict == "supported"
        assert boolean_wrap.method == "float_comparison"
        lambda_wrap = await server.verify_claim(
            "(lambda: (RR(1)+RR(1)/10^20-RR(1)).is_zero())()", ctx=ctx
        )
        assert lambda_wrap.verdict == "supported"
        # `== True` on an EXACT predicate cannot lower certainty either -- it is
        # still proved, and the probe does not false-positive on function names.
        assert (await server.verify_claim("is_prime(7) == True", ctx=ctx)).verdict == "proved"

        # External-review round 4: Greek-symbol claims. AST column offsets count
        # UTF-8 bytes, so the old raw slicing cut a two-byte letter in half and
        # produced invalid syntax; get_source_segment keeps the whole symbol.
        alpha = chr(0x3B1)
        assert (await server.verify_claim(f"{alpha} == {alpha}", ctx=ctx)).verdict == "proved"
        greek = await server.verify_claim(
            f"{alpha}^2 - 2*{alpha} + 1 == ({alpha} - 1)^2", ctx=ctx
        )
        assert greek.verdict == "proved"
    finally:
        await manager.shutdown()
