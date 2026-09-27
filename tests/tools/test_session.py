"""Unit tests for the session, workspace and resource tools (src/sagemath_mcp/tools/session.py).

Moved out of tests/test_server.py in the 2026-09 refactor, unchanged.
"""

import asyncio
import contextlib
import json

import pytest
from fastmcp.exceptions import ToolError

from sagemath_mcp import runtime, server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.errors import SageEvaluationError
from sagemath_mcp.manager import SageSessionManager
from sagemath_mcp.monitoring import reset_metrics

from ..conftest import FakeContext
from ..stubs import StubSession, _stub_manager


@pytest.mark.asyncio
async def test_documentation_resource_contains_reference_link():
    links = await server.documentation_resource("all", None)
    urls = {link.url for link in links}
    assert "https://doc.sagemath.org/html/en/reference" in urls


@pytest.mark.asyncio
async def test_monitoring_resource_tracks_metrics(monkeypatch):
    reset_metrics()
    success_session = StubSession("42")
    await _stub_manager(monkeypatch, success_session)
    ctx_success = FakeContext("metrics-success")
    result = await server.evaluate_sage("6*7", ctx=ctx_success)
    assert result.result == "42"

    class FailingSession:
        def __init__(self):
            self.calls: list[str] = []

        async def evaluate(self, code: str, **kwargs):
            self.calls.append(code)
            raise SageEvaluationError(
                "Blocked by policy",
                error_type="SecurityViolation",
                stdout="",
                traceback="",
            )

    await _stub_manager(monkeypatch, FailingSession())
    ctx_fail = FakeContext("metrics-fail")
    with pytest.raises(server.ToolError):
        await server.evaluate_sage("import os", ctx=ctx_fail)

    raw = await server.monitoring_resource("metrics", None)
    assert raw
    snapshot = json.loads(raw)
    assert snapshot["attempts"] == 2
    assert snapshot["successes"] == 1
    assert snapshot["failures"] == 1
    assert snapshot["security_failures"] == 1
    # The counters are safe aggregates; the free-text fields are not, and the
    # resource must not expose them (item 58). They stay on the internal record.
    assert "last_error" not in snapshot
    assert "last_security_violation" not in snapshot
    assert "last_error_details" not in snapshot
    from sagemath_mcp import monitoring as _monitoring

    assert _monitoring.snapshot()["last_security_violation"]
    assert _monitoring.snapshot()["last_error_details"]


@pytest.mark.asyncio
async def test_documentation_resource_unknown_scope():
    result = await server.documentation_resource("missing", None)
    assert result == []


@pytest.mark.asyncio
async def test_monitoring_resource_unknown_scope():
    result = await server.monitoring_resource("other", None)
    assert result == "[]"


# --- context guard tests (no ctx / no session_id) ---


@pytest.mark.asyncio
async def test_reset_sage_session_no_context():
    with pytest.raises(ToolError):
        await server.reset_sage_session(ctx=None)


@pytest.mark.asyncio
async def test_cancel_sage_session_no_context():
    with pytest.raises(ToolError):
        await server.cancel_sage_session(ctx=None)


# --- reset/cancel tool happy paths ---


@pytest.mark.asyncio
async def test_reset_sage_session(monkeypatch):
    reset_called = False

    async def fake_reset(session_id: str):
        nonlocal reset_called
        reset_called = True

    manager = SageSessionManager(server.DEFAULT_SETTINGS)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "reset", fake_reset)

    ctx = FakeContext("reset-test")
    result = await server.reset_sage_session(ctx=ctx)
    assert reset_called
    assert result.message == "Session cleared"


@pytest.mark.asyncio
async def test_cancel_sage_session(monkeypatch):
    cancel_called = False

    async def fake_cancel(session_id: str):
        nonlocal cancel_called
        cancel_called = True

    manager = SageSessionManager(server.DEFAULT_SETTINGS)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "cancel", fake_cancel)

    ctx = FakeContext("cancel-test")
    result = await server.cancel_sage_session(ctx=ctx)
    assert cancel_called
    assert result.message == "Session cancelled and restarted"


# --- session_resource coverage ---


# Two clients, each owning a default and a named workspace. The manager keys on
# the MCP session id, so client A's keys are "A" and "A::curves" and client B's
# are "B" and "B::scratch". The resource must show a caller only their own, and
# only by workspace name -- never the raw key (which is the other client's MCP
# session id). See REVIEW_ACTIONS.md item 57.
def _two_client_snapshot():
    return [
        {"session_id": "A", "live": True, "started_at": 1000.0,
         "last_used_at": 1001.0, "idle_seconds": 5.0},
        {"session_id": "A::curves", "live": True, "started_at": 1000.0,
         "last_used_at": 1001.0, "idle_seconds": 5.0},
        {"session_id": "B", "live": True, "started_at": 1000.0,
         "last_used_at": 1001.0, "idle_seconds": 5.0},
        {"session_id": "B::scratch", "live": False, "started_at": 1000.0,
         "last_used_at": 1001.0, "idle_seconds": 10.0},
    ]


@pytest.mark.asyncio
async def test_session_resource_all_is_scoped_to_the_caller(monkeypatch):
    manager = SageSessionManager(server.DEFAULT_SETTINGS)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "snapshot", _two_client_snapshot)

    raw = await server.session_resource("all", FakeContext("A"))
    result = json.loads(raw)
    # Client A sees exactly its two workspaces, named -- never B's, never a
    # raw MCP session id.
    names = sorted(entry["session_id"] for entry in result)
    assert names == ["curves", "default"]
    assert all(entry["session_id"] not in {"A", "B", "A::curves", "B::scratch"} for entry in result)


@pytest.mark.asyncio
async def test_session_resource_filters_by_workspace_name(monkeypatch):
    manager = SageSessionManager(server.DEFAULT_SETTINGS)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "snapshot", _two_client_snapshot)

    raw = await server.session_resource("curves", FakeContext("A"))
    result = json.loads(raw)
    assert len(result) == 1
    assert result[0]["session_id"] == "curves"


@pytest.mark.asyncio
async def test_session_resource_cannot_read_another_clients_scope(monkeypatch):
    manager = SageSessionManager(server.DEFAULT_SETTINGS)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "snapshot", _two_client_snapshot)

    # The pre-fix exploit: pass another client's MCP session id as the scope.
    # It must match nothing, because scope now selects a workspace name within
    # the caller's own sessions.
    raw = await server.session_resource("B", FakeContext("A"))
    assert json.loads(raw) == []


@pytest.mark.asyncio
async def test_session_resource_without_context_returns_nothing(monkeypatch):
    manager = SageSessionManager(server.DEFAULT_SETTINGS)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "snapshot", _two_client_snapshot)

    # Fails closed: no caller to scope to, so nothing is disclosed.
    assert json.loads(await server.session_resource("all", None)) == []


@pytest.mark.asyncio
async def test_session_tools_require_context():
    """Every session tool needs a session_id to scope the workspace."""
    for call in (
        lambda: server.interrupt_sage_session(ctx=None),
        lambda: server.start_sage_session("x", ctx=None),
        lambda: server.list_sage_sessions(ctx=None),
        lambda: server.stop_sage_session("x", ctx=None),
    ):
        with pytest.raises(ToolError):
            await call()


@pytest.mark.asyncio
async def test_start_sage_session_rejects_blank_name(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    with pytest.raises(ToolError, match="must not be empty"):
        await server.start_sage_session("   ", ctx=FakeContext())


@pytest.mark.asyncio
async def test_stop_unknown_session_reports_clearly(monkeypatch):
    """Stopping a workspace that does not exist must say so, not fail silently."""
    manager = SageSessionManager(SageSettings(force_python_worker=True))
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    with pytest.raises(ToolError, match="No Sage session named"):
        await server.stop_sage_session("absent", ctx=FakeContext("scope"))


@pytest.mark.asyncio
async def test_interrupt_without_worker_is_not_an_error(monkeypatch):
    """Nothing running is a normal outcome, reported rather than raised."""
    manager = SageSessionManager(SageSettings(force_python_worker=True))
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    result = await server.interrupt_sage_session(ctx=FakeContext("scope"))
    assert "No running computation" in result.message


@pytest.mark.asyncio
async def test_named_sessions_listed_per_client(monkeypatch):
    manager = SageSessionManager(SageSettings(force_python_worker=True))
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    ctx = FakeContext("client-a")
    try:
        await server.start_sage_session("alpha", ctx=ctx)
        await server.start_sage_session("beta", ctx=ctx)
        # A different client must not see them.
        other = await server.list_sage_sessions(ctx=FakeContext("client-b"))
        assert other["count"] == 0

        listed = await server.list_sage_sessions(ctx=ctx)
        assert [entry["name"] for entry in listed["sessions"]] == ["alpha", "beta"]

        await server.stop_sage_session("alpha", ctx=ctx)
        listed = await server.list_sage_sessions(ctx=ctx)
        assert [entry["name"] for entry in listed["sessions"]] == ["beta"]
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_cancelled_streaming_then_reset_then_evaluate_on_a_named_workspace(
    monkeypatch,
):
    """The whole sequence through the public tools, on one named workspace.

    Streaming and the specialised tools did not clean up after a cancellation
    the way evaluate_sage did, so an abandoned computation stayed running and
    its response sat in the pipe for whoever read next.
    """
    settings = SageSettings(force_python_worker=True, eval_timeout=30.0)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    ctx = FakeContext("cancel-stream-client")
    try:
        await server.evaluate_sage("anchor = 5", session="bench", ctx=ctx)

        task = asyncio.create_task(
            server.evaluate_sage_streaming(
                "total = sum(range(60000000))\ntotal / 0", session="bench", ctx=ctx
            )
        )
        await asyncio.sleep(0.2)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        await server.reset_sage_session(session="bench", ctx=ctx)
        result = await server.evaluate_sage("3 * 14", session="bench", ctx=ctx)
        assert result.result == "42", "the workspace was unusable after cancel + reset"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_interrupting_a_session_with_no_worker_is_not_an_error(sage_manager):
    """Nothing is running, so there is nothing to abandon."""
    ctx = FakeContext("idle-client")
    response = await server.interrupt_sage_session(session="never-used", ctx=ctx)
    assert "No running computation" in response.message


@pytest.mark.asyncio
async def test_interrupting_an_idle_workspace_says_nothing_was_running(sage_manager):
    """It used to signal the idle worker and claim "state preserved" regardless."""
    ctx = FakeContext("busy-client")
    await server.evaluate_sage("kept = 5", session="busy", ctx=ctx)
    response = await server.interrupt_sage_session(session="busy", ctx=ctx)
    assert "No running computation" in response.message


@pytest.mark.asyncio
async def test_interrupting_a_running_computation_reports_state_preserved(sage_manager):
    """The other half: something IS running, so the signal is real."""
    ctx = FakeContext("interrupt-client")
    await server.evaluate_sage("kept = 9", session="work", ctx=ctx)

    task = asyncio.create_task(
        server.evaluate_sage("sum(range(80000000))", session="work", ctx=ctx)
    )
    await asyncio.sleep(0.2)
    response = await server.interrupt_sage_session(session="work", ctx=ctx)
    with contextlib.suppress(Exception):
        await task

    assert "state preserved" in response.message
    survived = await server.evaluate_sage("kept", session="work", ctx=ctx)
    assert survived.result == "9", "the namespace did not survive the interrupt"
