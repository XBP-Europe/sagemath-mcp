"""Unit tests for the plotting and geometry tools (src/sagemath_mcp/tools/plotting.py).

Moved out of tests/test_server.py in the 2026-09 refactor, unchanged.
"""


import pytest
from fastmcp.exceptions import ToolError

from sagemath_mcp import server

from ..conftest import FakeContext
from ..stubs import StubSession, _stub_manager


@pytest.mark.asyncio
async def test_plot_expression(monkeypatch):
    session = StubSession("'aWdub3JlZA=='")  # base64 of b"ignored"
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.plot_expression("sin(x)", ctx=ctx)
    # Returns MCP image content, not a JSON dict of base64: a client renders it.
    content = result.to_image_content()
    assert content.mime_type == "image/png"
    assert content.data == "aWdub3JlZA=="


@pytest.mark.asyncio
async def test_plot_expression_svg(monkeypatch):
    session = StubSession("'aWdub3JlZA=='")
    await _stub_manager(monkeypatch, session)
    result = await server.plot_expression("sin(x)", image_format="svg", ctx=FakeContext())
    assert result.to_image_content().mime_type == "image/svg+xml"


@pytest.mark.asyncio
async def test_plot_expression_rejects_malformed_image_data(monkeypatch):
    session = StubSession("'not!!valid!!base64'")
    await _stub_manager(monkeypatch, session)
    with pytest.raises(server.ToolError, match="malformed image data"):
        await server.plot_expression("sin(x)", ctx=FakeContext())


@pytest.mark.asyncio
async def test_plot_expression_rejects_non_string_result(monkeypatch):
    session = StubSession("42")  # literal_eval -> int, not an image payload
    await _stub_manager(monkeypatch, session)
    with pytest.raises(server.ToolError, match="did not return image data"):
        await server.plot_expression("sin(x)", ctx=FakeContext())


@pytest.mark.asyncio
async def test_plot_expression_no_context():
    with pytest.raises(ToolError):
        await server.plot_expression("x", ctx=None)


@pytest.mark.asyncio
async def test_plot3d_expression(monkeypatch):
    session = StubSession("'aWdub3JlZA=='")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.plot3d_expression(
        expression="x^2 + y^2", ctx=ctx,
    )
    assert result.to_image_content().mime_type == "image/png"


@pytest.mark.asyncio
async def test_plot3d_expression_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.plot3d_expression("x + y", ctx=None)


@pytest.mark.asyncio
async def test_plot_multi_expression(monkeypatch):
    session = StubSession("'aWdub3JlZA=='")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.plot_multi_expression(
        expressions=["sin(x)", "cos(x)"], ctx=ctx,
    )
    assert result.to_image_content().mime_type == "image/png"


@pytest.mark.asyncio
async def test_plot_multi_expression_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.plot_multi_expression(
            expressions=["x", "x^2"], ctx=None,
        )


@pytest.mark.asyncio
async def test_geometry_distance(monkeypatch):
    session = StubSession("5.0")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.geometry_operation(
        operation="distance",
        points=[[0.0, 0.0], [3.0, 4.0]], ctx=ctx,
    )
    assert result["result"] == 5.0


@pytest.mark.asyncio
async def test_geometry_volume(monkeypatch):
    session = StubSession("1.0")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.geometry_operation(
        operation="polytope_volume",
        points=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
        ctx=ctx,
    )
    assert result["operation"] == "polytope_volume"


@pytest.mark.asyncio
async def test_geometry_convex_hull(monkeypatch):
    session = StubSession("[[0, 0], [1, 0], [0, 1]]")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.geometry_operation(
        operation="convex_hull_vertices",
        points=[[0, 0], [1, 0], [0, 1], [0.5, 0.25]],
        ctx=ctx,
    )
    assert result["operation"] == "convex_hull_vertices"


@pytest.mark.asyncio
async def test_geometry_invalid(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.geometry_operation(
            operation="invalid",
            points=[[0, 0], [1, 1]], ctx=ctx,
        )


@pytest.mark.asyncio
async def test_geometry_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.geometry_operation(
            operation="distance",
            points=[[0, 0], [1, 1]], ctx=None,
        )


@pytest.mark.asyncio
async def test_geometry_rejects_an_empty_point_set(sage_manager):
    with pytest.raises(ToolError, match="at least one point"):
        await server.geometry_operation(
            operation="area", points=[], ctx=FakeContext("geo-client")
        )


@pytest.mark.asyncio
async def test_geometry_distance_needs_two_points(sage_manager):
    """It used to generate the literal "None" and return it as an answer."""
    with pytest.raises(ToolError, match="requires two points"):
        await server.geometry_operation(
            operation="distance", points=[[0, 0]], ctx=FakeContext("geo-client")
        )


@pytest.mark.asyncio
async def test_is_convex_needs_a_polygon(sage_manager):
    """Two points are a segment. Rejected before any Sage call, so no runtime."""
    with pytest.raises(ToolError, match="at least three"):
        await server.geometry_operation(
            operation="is_convex", points=[[0, 0], [1, 1]], ctx=FakeContext("geo-client")
        )
