"""Unit tests for the statistics tools (src/sagemath_mcp/tools/stats.py).

Moved out of tests/test_server.py in the 2026-09 refactor, unchanged.
"""

import json

import pytest
from fastmcp.exceptions import ToolError

from sagemath_mcp import server

from ..conftest import FakeContext
from ..stubs import StubSession, _stub_manager


@pytest.mark.asyncio
async def test_statistics_summary(monkeypatch):
    payload = json.dumps(
        {
            "mean": 3.0,
            "median": 3.0,
            "population_variance": 2.0,
            "sample_variance": 2.5,
            "population_std_dev": 1.4142,
            "sample_std_dev": 1.5811,
            "min": 1.0,
            "max": 5.0,
        }
    )
    session = StubSession(payload)
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.statistics_summary([1, 2, 3, 4, 5], ctx=ctx)
    assert result["mean"] == 3.0
    assert "population_std_dev" in result


@pytest.mark.asyncio
async def test_statistics_summary_no_context():
    with pytest.raises(ToolError):
        await server.statistics_summary([1, 2], ctx=None)


# ---------------------------------------------------------------------------
# Phase 2 tools: distribution, find_root, plot_multi, vector_calculus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_distribution_normal_cdf(monkeypatch):
    session = StubSession("0.9772")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.distribution_operation(
        distribution="normal", parameters=[1.0],
        operation="cdf", x=2.0, ctx=ctx,
    )
    assert result["distribution"] == "normal"
    assert result["operation"] == "cdf"


@pytest.mark.asyncio
async def test_distribution_poisson_pdf(monkeypatch):
    session = StubSession("0.1804")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.distribution_operation(
        distribution="poisson", parameters=[5.0],
        operation="pdf", x=3.0, ctx=ctx,
    )
    assert result["distribution"] == "poisson"


@pytest.mark.asyncio
async def test_distribution_poisson_mean(monkeypatch):
    session = StubSession("5.0")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.distribution_operation(
        distribution="poisson", parameters=[5.0],
        operation="mean", ctx=ctx,
    )
    assert result["operation"] == "mean"


@pytest.mark.asyncio
async def test_distribution_sample(monkeypatch):
    session = StubSession("[1.2, 0.5, -0.3]")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.distribution_operation(
        distribution="exponential", parameters=[1.0],
        operation="sample", n=3, ctx=ctx,
    )
    assert result["operation"] == "sample"


@pytest.mark.asyncio
async def test_distribution_unknown(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown distribution"):
        await server.distribution_operation(
            distribution="invalid", parameters=[1.0],
            operation="pdf", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_distribution_unknown_operation(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.distribution_operation(
            distribution="normal", parameters=[1.0],
            operation="invalid", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_distribution_poisson_unknown_op(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.distribution_operation(
            distribution="poisson", parameters=[5.0],
            operation="quantile", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_distribution_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.distribution_operation(
            distribution="normal", parameters=[1.0],
            operation="pdf", ctx=None,
        )


@pytest.mark.asyncio
async def test_statistics_summary_rejects_an_empty_dataset(sage_manager):
    with pytest.raises(ToolError, match="at least one value"):
        await server.statistics_summary(data=[], ctx=FakeContext("stats-client"))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,x", [("pdf", None), ("cdf", None)])
async def test_poisson_requires_an_evaluation_point(operation, x, monkeypatch):
    await _stub_manager(monkeypatch, StubSession("0"))
    with pytest.raises(ToolError, match="requires x"):
        await server.distribution_operation("poisson", [2.0], operation, x=x, ctx=FakeContext())


@pytest.mark.asyncio
async def test_poisson_rejects_negative_rate(monkeypatch):
    await _stub_manager(monkeypatch, StubSession("0"))
    with pytest.raises(ToolError, match="nonnegative"):
        await server.distribution_operation("poisson", [-1.0], "mean", ctx=FakeContext())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["pdf", "cdf", "quantile", "sample"])
async def test_an_undefined_moment_refuses_only_itself(operation, monkeypatch):
    """Student's t with one degree of freedom (the Cauchy) has no mean and no
    variance, but it has a density. Both moments used to be built for every
    operation, so their refusal refused the density too."""
    await _stub_manager(monkeypatch, StubSession("0.3"))
    result = await server.distribution_operation(
        "student_t", [1.0], operation, x=0.5, n=2, ctx=FakeContext()
    )
    assert result["operation"] == operation
    for moment in ("mean", "variance"):
        with pytest.raises(ToolError, match="undefined"):
            await server.distribution_operation("student_t", [1.0], moment, ctx=FakeContext())
