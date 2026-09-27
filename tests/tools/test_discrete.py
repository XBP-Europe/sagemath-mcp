"""Unit tests for the discrete-mathematics tools (src/sagemath_mcp/tools/discrete.py).

Moved out of tests/test_server.py in the 2026-09 refactor, unchanged.
"""


import pytest
from fastmcp.exceptions import ToolError

from sagemath_mcp import server
from sagemath_mcp.tools import discrete as combinatorics_module

from ..conftest import FakeContext
from ..stubs import StubSession, _stub_manager


@pytest.mark.asyncio
async def test_number_theory_is_prime(monkeypatch):
    session = StubSession("True")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.number_theory_operation(
        "is_prime", 7, ctx=ctx
    )
    assert result == {"operation": "is_prime", "result": True}


@pytest.mark.asyncio
async def test_number_theory_factor_integer(monkeypatch):
    session = StubSession("'2^2 * 3 * 5'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.number_theory_operation(
        "factor_integer", 60, ctx=ctx
    )
    assert result == {"operation": "factor_integer", "result": "2^2 * 3 * 5"}


@pytest.mark.asyncio
async def test_number_theory_gcd(monkeypatch):
    session = StubSession("6")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.number_theory_operation(
        "gcd", 12, b=18, ctx=ctx
    )
    assert result == {"operation": "gcd", "result": 6}


@pytest.mark.asyncio
async def test_number_theory_gcd_missing_b():
    ctx = FakeContext()
    with pytest.raises(ToolError, match="requires both"):
        await server.number_theory_operation("gcd", 12, ctx=ctx)


@pytest.mark.asyncio
async def test_number_theory_invalid_op():
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.number_theory_operation("bogus", 5, ctx=ctx)


@pytest.mark.asyncio
async def test_number_theory_operation_no_context():
    with pytest.raises(ToolError):
        await server.number_theory_operation("is_prime", 7, ctx=None)


@pytest.mark.asyncio
async def test_combinatorics_binomial(monkeypatch):
    session = StubSession("252")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="binomial", n=10, k=5, ctx=ctx,
    )
    assert result["operation"] == "binomial"
    assert result["result"] == 252


@pytest.mark.asyncio
async def test_combinatorics_factorial(monkeypatch):
    session = StubSession("120")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="factorial", n=5, ctx=ctx,
    )
    assert result["result"] == 120


@pytest.mark.asyncio
async def test_combinatorics_catalan(monkeypatch):
    session = StubSession("42")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="catalan", n=5, ctx=ctx,
    )
    assert result["operation"] == "catalan"


@pytest.mark.asyncio
async def test_combinatorics_fibonacci(monkeypatch):
    session = StubSession("55")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="fibonacci", n=10, ctx=ctx,
    )
    assert result["result"] == 55


@pytest.mark.asyncio
async def test_combinatorics_bell(monkeypatch):
    session = StubSession("52")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="bell", n=5, ctx=ctx,
    )
    assert result["operation"] == "bell"


@pytest.mark.asyncio
async def test_combinatorics_partitions(monkeypatch):
    session = StubSession("7")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="partitions", n=5, ctx=ctx,
    )
    assert result["result"] == 7


@pytest.mark.asyncio
async def test_combinatorics_permutations(monkeypatch):
    session = StubSession("24")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="permutations", n=4, ctx=ctx,
    )
    assert result["result"] == 24


@pytest.mark.asyncio
async def test_combinatorics_permutations_with_k(monkeypatch):
    session = StubSession("60")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="permutations", n=5, k=3, ctx=ctx,
    )
    assert result["result"] == 60


@pytest.mark.asyncio
async def test_combinatorics_invalid_operation(monkeypatch):
    session = StubSession("0")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.combinatorics_operation(
            operation="invalid", n=5, ctx=ctx,
        )


@pytest.mark.asyncio
async def test_combinatorics_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.combinatorics_operation(
            operation="factorial", n=5, ctx=None,
        )


# ---------------------------------------------------------------------------
# Phase 4 — Niche domain tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_operation_chromatic(monkeypatch):
    session = StubSession("3")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.graph_operation(
        graph="PetersenGraph", operation="chromatic_number", ctx=ctx,
    )
    assert result["operation"] == "chromatic_number"
    assert result["result"] == 3


@pytest.mark.asyncio
async def test_graph_operation_is_connected(monkeypatch):
    session = StubSession("True")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.graph_operation(
        graph="{0:[1,2], 1:[0,2], 2:[0,1]}",
        operation="is_connected", ctx=ctx,
    )
    assert result["result"] is True


@pytest.mark.asyncio
async def test_graph_operation_shortest_path(monkeypatch):
    session = StubSession("[0, 1, 2]")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.graph_operation(
        graph="PetersenGraph", operation="shortest_path",
        source=0, target=2, ctx=ctx,
    )
    assert result["operation"] == "shortest_path"


@pytest.mark.asyncio
async def test_graph_operation_invalid(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.graph_operation(
            graph="PetersenGraph", operation="invalid", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_graph_operation_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.graph_operation(
            graph="PetersenGraph", operation="order", ctx=None,
        )


@pytest.mark.asyncio
async def test_group_operation_order(monkeypatch):
    session = StubSession("120")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.group_operation(
        group="SymmetricGroup(5)", operation="order", ctx=ctx,
    )
    assert result["result"] == 120


@pytest.mark.asyncio
async def test_group_operation_is_abelian(monkeypatch):
    session = StubSession("True")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.group_operation(
        group="CyclicPermutationGroup(6)",
        operation="is_abelian", ctx=ctx,
    )
    assert result["result"] is True


@pytest.mark.asyncio
async def test_group_operation_is_cyclic(monkeypatch):
    session = StubSession("False")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.group_operation(
        group="SymmetricGroup(4)", operation="is_cyclic", ctx=ctx,
    )
    assert result["operation"] == "is_cyclic"


@pytest.mark.asyncio
async def test_group_operation_invalid(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.group_operation(
            group="SymmetricGroup(3)", operation="invalid", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_group_operation_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.group_operation(
            group="SymmetricGroup(3)", operation="order", ctx=None,
        )


@pytest.mark.asyncio
async def test_elliptic_curve_rank(monkeypatch):
    session = StubSession("0")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.elliptic_curve_operation(
        coefficients=[0, 0, 1, -1, 0], operation="rank", ctx=ctx,
    )
    assert result["operation"] == "rank"


@pytest.mark.asyncio
async def test_elliptic_curve_discriminant(monkeypatch):
    session = StubSession("'-37'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.elliptic_curve_operation(
        coefficients=[0, -1], operation="discriminant", ctx=ctx,
    )
    assert result["operation"] == "discriminant"


@pytest.mark.asyncio
async def test_elliptic_curve_invalid(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.elliptic_curve_operation(
            coefficients=[0, 1], operation="invalid", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_elliptic_curve_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.elliptic_curve_operation(
            coefficients=[0, 1], operation="rank", ctx=None,
        )


@pytest.mark.asyncio
async def test_coding_theory_length(monkeypatch):
    session = StubSession("7")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.coding_theory_operation(
        code_type="HammingCode(GF(2), 3)",
        operation="length", ctx=ctx,
    )
    assert result["result"] == 7


@pytest.mark.asyncio
async def test_coding_theory_minimum_distance(monkeypatch):
    session = StubSession("3")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.coding_theory_operation(
        code_type="HammingCode(GF(2), 3)",
        operation="minimum_distance", ctx=ctx,
    )
    assert result["operation"] == "minimum_distance"


@pytest.mark.asyncio
async def test_coding_theory_rate(monkeypatch):
    session = StubSession("0.5714285714285714")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.coding_theory_operation(
        code_type="HammingCode(GF(2), 3)",
        operation="rate", ctx=ctx,
    )
    assert result["operation"] == "rate"


@pytest.mark.asyncio
async def test_coding_theory_invalid(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.coding_theory_operation(
            code_type="HammingCode(GF(2), 3)",
            operation="invalid", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_coding_theory_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.coding_theory_operation(
            code_type="HammingCode(GF(2), 3)",
            operation="length", ctx=None,
        )


@pytest.mark.asyncio
async def test_number_theory_accepts_big_integers_as_strings(monkeypatch):
    """The documented escape hatch for values JSON cannot carry exactly."""
    session = StubSession("1000000000000000000000000000057")
    await _stub_manager(monkeypatch, session)
    result = await server.number_theory_operation(
        "next_prime", "1000000000000000000000000000000", ctx=FakeContext()
    )
    # It comes back as a decimal STRING, not an int. Above 2^53 a JSON number
    # stops being exact, and a JavaScript-based client silently rounds it: this
    # value would reach the caller as 1.0000000000000001e+30. The exact digits
    # matter more than the type, and the input side already speaks this dialect.
    assert result["result"] == str(10**30 + 57)
    # The generated code must carry the exact value, not a float repr.
    assert "1000000000000000000000000000000" in session.calls[0]["code"]
    assert "e+30" not in session.calls[0]["code"]


@pytest.mark.parametrize(
    "tool,kwargs",
    [
        ("combinatorics_operation", {"operation": "binomial", "n": 2**53 + 1, "k": 2}),
        ("combinatorics_operation", {"operation": "factorial", "n": 2**53 + 1}),
        ("elliptic_curve_operation",
         {"operation": "rank", "coefficients": [0, 0, 1, -1, 2**53 + 1]}),
    ],
)
@pytest.mark.asyncio
async def test_exact_integer_arguments_beyond_2_53_are_refused(tool, kwargs, sage_manager):
    """A JS client rounds before it serialises, so the digits arriving are a lie.

    number_theory_operation has guarded this since 0.4.0; these did not, so
    binomial(9007199254740993, 2) computed a plausible, wrong answer in silence.
    """
    with pytest.raises(ToolError, match="2\\^53"):
        await getattr(server, tool)(ctx=FakeContext("exact-client"), **kwargs)


@pytest.mark.asyncio
async def test_exact_integer_arguments_accept_decimal_strings(sage_manager, monkeypatch):
    """The documented escape hatch has to exist wherever the guard does."""
    captured: dict[str, str] = {}

    async def fake_structured(session, code, timeout_seconds=None):
        captured["code"] = code
        return 1

    monkeypatch.setattr(combinatorics_module, "evaluate_structured", fake_structured)
    await combinatorics_module.combinatorics_operation(
        operation="factorial", n="9007199254740993", ctx=FakeContext("exact-client")
    )
    assert "9007199254740993" in captured["code"]
    assert "e+" not in captured["code"]
