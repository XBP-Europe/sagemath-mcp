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

        # Not a comparison at all: loud error, not a verdict.
        with pytest.raises(server.ToolError, match="must be a comparison"):
            await server.verify_claim("2 + 2", ctx=ctx)
    finally:
        await manager.shutdown()
