import asyncio
import contextlib
import json

import pytest

from sagemath_mcp import app, runtime, server
from sagemath_mcp.tools import core as core_tools

from .conftest import FakeContext


@pytest.mark.asyncio
async def test_cull_loop_runs_until_cancelled(monkeypatch):
    calls: list[int] = []

    async def fake_cull_idle():
        calls.append(1)

    monkeypatch.setattr(runtime.SESSION_MANAGER, "cull_idle", fake_cull_idle)

    task = asyncio.create_task(app._cull_loop(interval=0.01))
    await asyncio.sleep(0.03)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert calls


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops(monkeypatch):
    started: list[float] = []

    async def fake_cull_loop(interval: float = 60.0) -> None:
        started.append(interval)

    monkeypatch.setattr(app, "_cull_loop", fake_cull_loop)

    async with app._lifespan(server.mcp):
        await asyncio.sleep(0)

    assert started == [60.0]


@pytest.mark.asyncio
async def test_lifespan_cancels_running_cull_loop(monkeypatch):
    events: list[str] = []
    stop = asyncio.Event()

    async def fake_cull_loop(interval: float = 60.0) -> None:
        try:
            await stop.wait()
        except asyncio.CancelledError:
            events.append("cancelled")
            raise

    monkeypatch.setattr(app, "_cull_loop", fake_cull_loop)

    async with app._lifespan(server.mcp):
        await asyncio.sleep(0)

    assert events == ["cancelled"]


@pytest.mark.asyncio
async def test_progress_heartbeat_emits(monkeypatch):
    ctx = FakeContext("heartbeat")
    task = asyncio.create_task(core_tools._progress_heartbeat(ctx, interval=0.01))
    await asyncio.sleep(0.03)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert ctx.progress_events


# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check():
    """Verify the health_check function returns status ok."""
    # We can call the handler directly with a mock request
    response = await server.health_check(None)
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["status"] == "ok"
    assert body["version"] == server.__version__
    assert "active_sessions" in body


def test_register_health_route_is_idempotent():
    """Registering twice must not fail or duplicate the route.

    This test used to build a FakeApp with a `.routes` list and assert a Route
    was inserted into it. That mock did not resemble FastMCP 3.x, where
    `http_app` is a bound method -- so the test passed against an
    implementation that registered nothing at all. The real assertion is in
    test_the_health_route_reaches_the_built_http_app: ask the app FastMCP
    actually builds.
    """
    from sagemath_mcp.app import mcp

    server._register_health_route()
    server._register_health_route()
    health = [r for r in mcp.http_app().routes if getattr(r, "path", None) == "/health"]
    assert len(health) == 1, f"expected one /health route, found {len(health)}"


@pytest.mark.asyncio
async def test_lifespan_without_cull_task(monkeypatch):
    """Cover branch 102->106: _CULL_TASK is None when lifespan exits."""
    monkeypatch.setattr(app, "_CULL_TASK", None)
    async with app._lifespan(server.mcp):
        # Force _CULL_TASK to None to test the branch
        monkeypatch.setattr(app, "_CULL_TASK", None)


def test_the_health_route_reaches_the_built_http_app() -> None:
    """The probe target has to exist on the app FastMCP actually serves.

    The previous implementation looked for a Starlette app on the FastMCP
    object and inserted a Route. Under FastMCP 3.x `http_app` is a bound method
    that builds the app, so the guard never matched and nothing was registered
    -- inside a bare `except: pass`, so it failed in total silence while the
    README advertised the endpoint and the Helm chart probed it.
    """
    from sagemath_mcp.app import mcp

    server._register_health_route()
    paths = {getattr(route, "path", None) for route in mcp.http_app().routes}
    assert "/health" in paths, f"/health missing; app serves {sorted(p for p in paths if p)}"
    assert "/ready" in paths, f"/ready missing; app serves {sorted(p for p in paths if p)}"


@pytest.mark.asyncio
async def test_the_health_endpoint_answers_with_the_server_state() -> None:
    from sagemath_mcp import __version__

    response = await server.health_check(object())
    payload = json.loads(bytes(response.body).decode("utf-8"))
    assert payload["status"] == "ok"
    assert payload["version"] == __version__
    assert "active_sessions" in payload
