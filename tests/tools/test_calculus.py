"""Unit tests for the calculus tools (src/sagemath_mcp/tools/calculus.py).

Moved out of tests/test_server.py in the 2026-09 refactor, unchanged.
"""


import pytest
from fastmcp.exceptions import ToolError

from sagemath_mcp import server

from ..conftest import FakeContext
from ..stubs import StubSession, _stub_manager


@pytest.mark.asyncio
async def test_differentiate_expression(monkeypatch):
    session = StubSession("'2*x'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.differentiate_expression("x^2", ctx=ctx)
    assert result == {"derivative": "2*x", "order": 1}


@pytest.mark.asyncio
async def test_differentiate_expression_higher_order(monkeypatch):
    session = StubSession("'2'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.differentiate_expression("x^2", order=2, ctx=ctx)
    assert result == {"derivative": "2", "order": 2}


@pytest.mark.asyncio
async def test_integrate_expression(monkeypatch):
    session = StubSession("'x^3/3'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.integrate_expression("x^2", ctx=ctx)
    assert result == {"integral": "x^3/3", "definite": False}


@pytest.mark.asyncio
async def test_integrate_expression_definite(monkeypatch):
    session = StubSession("'1/3'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.integrate_expression(
        "x^2", lower_bound="0", upper_bound="1", ctx=ctx
    )
    assert result == {"integral": "1/3", "definite": True}


@pytest.mark.asyncio
async def test_integrate_expression_mixed_bounds():
    ctx = FakeContext()
    with pytest.raises(ToolError):
        await server.integrate_expression("x^2", lower_bound="0", ctx=ctx)


@pytest.mark.asyncio
async def test_limit_expression(monkeypatch):
    session = StubSession("'1'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.limit_expression("sin(x)/x", point="0", ctx=ctx)
    assert result == {"limit": "1"}


@pytest.mark.asyncio
async def test_limit_expression_with_direction(monkeypatch):
    session = StubSession("'+Infinity'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.limit_expression(
        "1/x", point="0", direction="plus", ctx=ctx
    )
    assert result == {"limit": "+Infinity"}


@pytest.mark.asyncio
async def test_series_expansion(monkeypatch):
    session = StubSession("'1 - x^2/2 + x^4/24 + O(x^6)'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.series_expansion("cos(x)", order=6, ctx=ctx)
    assert result["series"] == "1 - x^2/2 + x^4/24 + O(x^6)"
    assert result["order"] == 6
    assert result["point"] == "0"


@pytest.mark.asyncio
async def test_solve_ode(monkeypatch):
    session = StubSession("'_C*e^(-x)'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.solve_ode(
        "diff(y(x),x) + y(x) = 0", ctx=ctx
    )
    assert result == {"solution": "_C*e^(-x)"}


@pytest.mark.asyncio
async def test_solve_ode_binds_undefined_function(monkeypatch):
    """Regression guard for #12 that does not need a Sage runtime.

    Binding the dependent name to the applied expression turns the documented
    "y(x)" spelling into "(y(x))(x)", which Sage rejects. The generated code
    must bind the undefined function and only fall back to the applied form.
    """

    session = StubSession("'_C*e^(-x)'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    await server.solve_ode("diff(y(x), x) + y(x) = cos(x)", ctx=ctx)

    code = session.calls[0]["code"]
    assert "_ode_function = function(\"y\")" in code
    assert "_build_ode(_ode_function)" in code
    # The applied expression is still available as the fallback binding.
    assert "_y = _ode_function(_x)" in code
    assert "_build_ode(_y)" in code


@pytest.mark.asyncio
async def test_limit_expression_no_context():
    with pytest.raises(ToolError):
        await server.limit_expression("x", ctx=None)


@pytest.mark.asyncio
async def test_series_expansion_no_context():
    with pytest.raises(ToolError):
        await server.series_expansion("x", ctx=None)


@pytest.mark.asyncio
async def test_solve_ode_no_context():
    with pytest.raises(ToolError):
        await server.solve_ode("y' = 0", ctx=None)


@pytest.mark.asyncio
async def test_differentiate_expression_no_context():
    with pytest.raises(ToolError):
        await server.differentiate_expression("x", ctx=None)


@pytest.mark.asyncio
async def test_integrate_expression_no_context():
    with pytest.raises(ToolError):
        await server.integrate_expression("x", ctx=None)


# ---------------------------------------------------------------------------
# Phase 1 tools: symbolic_sum, combinatorics_operation, plot3d_expression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_symbolic_sum(monkeypatch):
    session = StubSession("'pi^2/6'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.symbolic_sum(
        expression="1/n^2", variable="n", lower="1", upper="oo", ctx=ctx,
    )
    assert result["operation"] == "sum"
    assert result["result"] is not None


@pytest.mark.asyncio
async def test_symbolic_product(monkeypatch):
    session = StubSession("'120'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.symbolic_sum(
        expression="k", variable="k", lower="1", upper="5",
        product=True, ctx=ctx,
    )
    assert result["operation"] == "product"


@pytest.mark.asyncio
async def test_symbolic_sum_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.symbolic_sum("1/n^2", ctx=None)


@pytest.mark.asyncio
async def test_vector_calculus_gradient(monkeypatch):
    session = StubSession("['2*x', '2*y', '2*z']")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.vector_calculus_operation(
        operation="gradient", expression="x^2 + y^2 + z^2", ctx=ctx,
    )
    assert result["operation"] == "gradient"
    assert isinstance(result["result"], list)


@pytest.mark.asyncio
async def test_vector_calculus_divergence(monkeypatch):
    session = StubSession("'3'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.vector_calculus_operation(
        operation="divergence", expression=["x", "y", "z"], ctx=ctx,
    )
    assert result["operation"] == "divergence"


@pytest.mark.asyncio
async def test_vector_calculus_curl(monkeypatch):
    session = StubSession("['0', '0', '0']")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.vector_calculus_operation(
        operation="curl", expression=["x", "y", "z"], ctx=ctx,
    )
    assert result["operation"] == "curl"


@pytest.mark.asyncio
async def test_vector_calculus_laplacian(monkeypatch):
    session = StubSession("'6'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.vector_calculus_operation(
        operation="laplacian", expression="x^2 + y^2 + z^2", ctx=ctx,
    )
    assert result["operation"] == "laplacian"


@pytest.mark.asyncio
async def test_vector_calculus_invalid_operation(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.vector_calculus_operation(
            operation="invalid", expression="x^2", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_vector_calculus_gradient_requires_string(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="scalar expression"):
        await server.vector_calculus_operation(
            operation="gradient", expression=["x", "y"], ctx=ctx,
        )


@pytest.mark.asyncio
async def test_vector_calculus_divergence_requires_list(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="vector field"):
        await server.vector_calculus_operation(
            operation="divergence", expression="x^2", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_vector_calculus_divergence_dimension_mismatch(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="components"):
        await server.vector_calculus_operation(
            operation="divergence",
            expression=["x", "y"],
            variables=["x", "y", "z"],
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_vector_calculus_curl_requires_3_components(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="exactly 3"):
        await server.vector_calculus_operation(
            operation="curl", expression=["x", "y"], ctx=ctx,
        )


@pytest.mark.asyncio
async def test_vector_calculus_laplacian_requires_string(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="scalar expression"):
        await server.vector_calculus_operation(
            operation="laplacian", expression=["x"], ctx=ctx,
        )


@pytest.mark.asyncio
async def test_vector_calculus_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.vector_calculus_operation(
            operation="gradient", expression="x^2", ctx=None,
        )


@pytest.mark.asyncio
async def test_vector_calculus_default_variables(monkeypatch):
    """Verify that variables defaults to ['x', 'y', 'z'] when None."""
    session = StubSession("['2*x', '2*y', '2*z']")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.vector_calculus_operation(
        operation="gradient", expression="x^2 + y^2 + z^2",
        variables=None, ctx=ctx,
    )
    assert result["operation"] == "gradient"


# ---------------------------------------------------------------------------
# Additional coverage: unreachable ctx branches, health route, curl vars
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vector_calculus_curl_wrong_variable_count(monkeypatch):
    """Cover line 1111: curl with != 3 variables."""
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="exactly 3 variables"):
        await server.vector_calculus_operation(
            operation="curl",
            expression=["x", "y", "z"],
            variables=["x", "y"],
            ctx=ctx,
        )
