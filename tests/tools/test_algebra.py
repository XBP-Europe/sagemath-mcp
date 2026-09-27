"""Unit tests for the algebra and linear-algebra tools (src/sagemath_mcp/tools/algebra.py).

Moved out of tests/test_server.py in the 2026-09 refactor, unchanged.
"""


import pytest
from fastmcp.exceptions import ToolError

from sagemath_mcp import server

from ..conftest import FakeContext
from ..stubs import StubSession, _stub_manager


@pytest.mark.asyncio
async def test_matrix_multiply(monkeypatch):
    session = StubSession("[[19.0, 22.0], [43.0, 50.0]]")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.matrix_multiply([[1, 2], [3, 4]], [[5, 6], [7, 8]], ctx=ctx)
    assert result == {"product": [[19.0, 22.0], [43.0, 50.0]]}


@pytest.mark.asyncio
async def test_matrix_multiply_literal_eval_failure(monkeypatch):
    session = StubSession("matrix([[1, 0], [0, 1]])")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.matrix_multiply([[1, 0], [0, 1]], [[1, 0], [0, 1]], ctx=ctx)
    assert result == {"product": "matrix([[1, 0], [0, 1]])"}


@pytest.mark.asyncio
async def test_solve_equation(monkeypatch):
    session = StubSession("['x == 1']")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.solve_equation("x^2 - 1 = 0", ctx=ctx)
    assert result == {"solutions": ["x == 1"]}


@pytest.mark.asyncio
async def test_solve_equation_system(monkeypatch):
    session = StubSession("[['x == 1', 'y == 2']]")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.solve_equation(
        ["x + y = 3", "x - y = -1"],
        variable=["x", "y"],
        ctx=ctx,
    )
    assert result == {"solutions": [["x == 1", "y == 2"]]}


@pytest.mark.asyncio
async def test_matrix_operation_determinant(monkeypatch):
    session = StubSession("-2.0")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.matrix_operation(
        [[1, 2], [3, 4]], "determinant", ctx=ctx
    )
    assert result == {"operation": "determinant", "result": -2.0}


@pytest.mark.asyncio
async def test_matrix_operation_rank(monkeypatch):
    session = StubSession("2")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.matrix_operation(
        [[1, 0], [0, 1]], "rank", ctx=ctx
    )
    assert result == {"operation": "rank", "result": 2}


@pytest.mark.asyncio
async def test_matrix_operation_eigenvalues(monkeypatch):
    session = StubSession("[3.0, 1.0]")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.matrix_operation(
        [[2, 1], [1, 2]], "eigenvalues", ctx=ctx
    )
    assert result == {"operation": "eigenvalues", "result": [3.0, 1.0]}


@pytest.mark.asyncio
async def test_matrix_operation_invalid():
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.matrix_operation([[1]], "nonsense", ctx=ctx)


@pytest.mark.asyncio
async def test_matrix_operation_no_context():
    with pytest.raises(ToolError):
        await server.matrix_operation([[1]], "rank", ctx=None)


@pytest.mark.asyncio
async def test_solve_equation_no_context():
    with pytest.raises(ToolError):
        await server.solve_equation("x=0", ctx=None)


@pytest.mark.asyncio
async def test_matrix_multiply_no_context():
    with pytest.raises(ToolError):
        await server.matrix_multiply([[1]], [[1]], ctx=None)


@pytest.mark.asyncio
async def test_boolean_algebra_evaluate(monkeypatch):
    session = StubSession("'x0*x1 + x0*x2 + x1*x2'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.boolean_algebra_operation(
        expression="x0*x1 + x0*x2 + x1*x2",
        operation="evaluate", ctx=ctx,
    )
    assert result["operation"] == "evaluate"


@pytest.mark.asyncio
async def test_boolean_algebra_variables(monkeypatch):
    session = StubSession("['x0', 'x1']")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.boolean_algebra_operation(
        expression="x0*x1", operation="variables",
        num_variables=2, ctx=ctx,
    )
    assert result["operation"] == "variables"


@pytest.mark.asyncio
async def test_boolean_algebra_degree(monkeypatch):
    session = StubSession("2")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.boolean_algebra_operation(
        expression="x0*x1 + x2", operation="degree", ctx=ctx,
    )
    assert result["result"] == 2


@pytest.mark.asyncio
async def test_boolean_algebra_invalid(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.boolean_algebra_operation(
            expression="x0", operation="invalid", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_boolean_algebra_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.boolean_algebra_operation(
            expression="x0", operation="evaluate", ctx=None,
        )


@pytest.mark.asyncio
async def test_polynomial_ring_groebner(monkeypatch):
    session = StubSession("['a^2 + b', 'b^2 - 1']")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.polynomial_ring_operation(
        ring_vars=["a", "b"],
        polynomials=["a^2+b", "b^2-1"],
        operation="groebner_basis", ctx=ctx,
    )
    assert result["operation"] == "groebner_basis"


@pytest.mark.asyncio
async def test_polynomial_ring_dimension(monkeypatch):
    session = StubSession("0")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.polynomial_ring_operation(
        ring_vars=["a", "b"],
        polynomials=["a^2+b", "b^2-1"],
        operation="ideal_dimension", ctx=ctx,
    )
    assert result["operation"] == "ideal_dimension"


@pytest.mark.asyncio
async def test_polynomial_ring_variety(monkeypatch):
    session = StubSession("[{'a': '1', 'b': '-1'}]")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.polynomial_ring_operation(
        ring_vars=["a", "b"],
        polynomials=["a-1", "b+1"],
        operation="ideal_variety", ctx=ctx,
    )
    assert result["operation"] == "ideal_variety"


@pytest.mark.asyncio
async def test_polynomial_ring_invalid(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.polynomial_ring_operation(
            ring_vars=["a"], polynomials=["a^2"],
            operation="invalid", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_polynomial_ring_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.polynomial_ring_operation(
            ring_vars=["a"], polynomials=["a^2"],
            operation="groebner_basis", ctx=None,
        )


# ---------------------------------------------------------------------------
# Argument-shape errors that must be reported, not computed around
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matrix_multiply_rejects_incompatible_shapes(sage_manager):
    """2x3 by 2x2 has no product; the message names both shapes."""
    with pytest.raises(ToolError, match="2x3 matrix by a 2x2"):
        await server.matrix_multiply(
            matrix_a=[[1, 2, 3], [4, 5, 6]],
            matrix_b=[[1, 2], [3, 4]],
            ctx=FakeContext("shape-client"),
        )
