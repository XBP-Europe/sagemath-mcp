import sys

import pytest

from sagemath_mcp.config import SageSettings
from sagemath_mcp.session import (
    SageEvaluationError,
    SageProcessError,
    SageSession,
    SageSessionManager,
)


@pytest.fixture(scope="module")
def python_settings():
    return SageSettings(
        sage_binary="sage",
        startup_code="from math import *",
        eval_timeout=5.0,
        idle_ttl=10.0,
        shutdown_grace=1.0,
        max_stdout_chars=1000,
        force_python_worker=True,
    )


@pytest.fixture(autouse=True)
def pure_python_env(monkeypatch):
    monkeypatch.setenv("SAGEMATH_MCP_PURE_PYTHON", "1")


@pytest.mark.asyncio
async def test_session_stateful_evaluation(python_settings):
    session = SageSession("test-session", python_settings)
    try:
        result1 = await session.evaluate("total = 5", want_latex=False, capture_stdout=False)
        assert result1.result_type == "statement"
        result2 = await session.evaluate("total + 7", want_latex=False, capture_stdout=True)
        assert result2.result == "12"
        assert result2.result_type == "expression"
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_session_reset_clears_state(python_settings):
    session = SageSession("reset-session", python_settings)
    try:
        await session.evaluate("x = 10", want_latex=False, capture_stdout=False)
        await session.reset()
        with pytest.raises(SageEvaluationError):
            await session.evaluate("x + 1", want_latex=False, capture_stdout=False)
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_session_manager_snapshot(python_settings):
    manager = SageSessionManager(python_settings)
    session = await manager.get("snapshot-session")
    try:
        await session.evaluate("value = 2", want_latex=False, capture_stdout=False)
        snapshot = manager.snapshot()
        assert any(entry["session_id"] == "snapshot-session" for entry in snapshot)
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_session_manager_cull_idle(python_settings):
    eager_cull_settings = SageSettings(
        sage_binary="sage",
        startup_code="from math import *",
        eval_timeout=5.0,
        idle_ttl=0.0,
        shutdown_grace=1.0,
        max_stdout_chars=1000,
        force_python_worker=True,
    )
    manager = SageSessionManager(eager_cull_settings)
    session = await manager.get("cull-session")
    try:
        await session.evaluate("hit = 1", want_latex=False, capture_stdout=False)
        session.last_used_at -= 5  # force the session to appear idle
        await manager.cull_idle()
        assert manager.snapshot() == []
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_session_cancel_restarts_worker(python_settings):
    session = SageSession("cancel-session", python_settings)
    try:
        await session.evaluate("y = 42", want_latex=False, capture_stdout=False)
        await session.cancel()
        with pytest.raises(SageEvaluationError):
            await session.evaluate("y + 1", want_latex=False, capture_stdout=False)
    finally:
        await session.shutdown()


def test_truncate_stdout():
    server = pytest.importorskip("sagemath_mcp.server")
    original_limit = server.SESSION_MANAGER.settings.max_stdout_chars
    server.SESSION_MANAGER.settings.max_stdout_chars = 8
    try:
        truncated = server._truncate_stdout("0123456789")
        assert truncated.startswith("01234567")
        assert "output truncated" in truncated
    finally:
        server.SESSION_MANAGER.settings.max_stdout_chars = original_limit


def test_truncate_stdout_with_non_int_limit(monkeypatch):
    server = pytest.importorskip("sagemath_mcp.server")
    import types

    monkeypatch.setattr(server, "DEFAULT_SETTINGS", types.SimpleNamespace(max_stdout_chars=5))
    monkeypatch.setattr(server.SESSION_MANAGER.settings, "max_stdout_chars", 5.5)
    result = server._truncate_stdout("0123456789")
    assert result.endswith("[output truncated]")


class _FakeWriter:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, payload: bytes) -> None:
        self.data.extend(payload)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _FakeReader:
    def __init__(self, data: bytes = b""):
        self._data = data

    async def readline(self) -> bytes:
        return self._data


class _FakeProcess:
    def __init__(self):
        self.stdin = _FakeWriter()
        self.stdout = _FakeReader()
        self.stderr = None
        self.returncode: int | None = None
        self.pid = 1234
        self.killed = False

    async def wait(self) -> int:
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


@pytest.mark.asyncio
async def test_session_evaluate_handles_timeout(monkeypatch, python_settings):
    from sagemath_mcp import session as session_module

    session = SageSession("timeout", python_settings)
    fake_process = _FakeProcess()

    async def fake_ensure_started() -> None:
        session._process = fake_process

    monkeypatch.setattr(session, "ensure_started", fake_ensure_started)

    restart_called = False

    async def fake_restart_worker() -> None:
        nonlocal restart_called
        restart_called = True

    monkeypatch.setattr(session, "_restart_worker", fake_restart_worker)

    async def fake_wait_for(*args, **kwargs):
        coro = args[0]
        coro.close()
        raise TimeoutError

    monkeypatch.setattr(session_module.asyncio, "wait_for", fake_wait_for)

    with pytest.raises(TimeoutError):
        await session.evaluate("1 + 1", want_latex=False, capture_stdout=False)

    assert restart_called is True


@pytest.mark.asyncio
async def test_session_shutdown_kills_on_timeout(monkeypatch, python_settings):
    from sagemath_mcp import session as session_module

    session = SageSession("shutdown", python_settings)
    fake_process = _FakeProcess()
    session._process = fake_process

    async def fake_wait_for(*args, **kwargs):
        coro = args[0]
        coro.close()
        raise TimeoutError

    monkeypatch.setattr(session_module.asyncio, "wait_for", fake_wait_for)

    await session.shutdown()

    assert fake_process.killed is True
    assert fake_process.stdin.closed is True


@pytest.mark.asyncio
async def test_session_launch_fails_without_sage(monkeypatch, python_settings):
    settings = SageSettings(
        sage_binary="nonexistent-sage-binary",
        startup_code="from math import *",
        eval_timeout=5.0,
        idle_ttl=10.0,
        shutdown_grace=1.0,
        max_stdout_chars=1000,
        force_python_worker=False,
    )
    session = SageSession("no-sage", settings)
    from sagemath_mcp.session import SageProcessError

    with pytest.raises(SageProcessError, match="Unable to locate Sage"):
        await session.ensure_started()


@pytest.mark.asyncio
async def test_session_evaluate_worker_terminated(monkeypatch, python_settings):
    """Worker returns empty bytes (terminated unexpectedly)."""
    from sagemath_mcp.session import SageProcessError

    session = SageSession("terminated", python_settings)
    fake_process = _FakeProcess()

    async def fake_ensure_started():
        session._process = fake_process

    monkeypatch.setattr(session, "ensure_started", fake_ensure_started)

    with pytest.raises(SageProcessError, match="terminated unexpectedly"):
        await session.evaluate("1 + 1", want_latex=False, capture_stdout=False)


@pytest.mark.asyncio
async def test_session_terminate_worker_branches(python_settings):
    """Cover _terminate_worker when there is a process with a running stderr task."""
    session = SageSession("terminate-branches", python_settings)
    await session.ensure_started()
    assert session._process is not None
    assert session._stderr_task is not None

    await session._terminate_worker()

    assert session._process is None
    assert session._stderr_task is None


@pytest.mark.asyncio
async def test_session_terminate_worker_no_process(python_settings):
    """Cover _terminate_worker when there is no process."""
    session = SageSession("terminate-none", python_settings)
    # No process started — should be a no-op
    await session._terminate_worker()
    assert session._process is None


@pytest.mark.asyncio
async def test_manager_reset_and_cancel(python_settings):
    """Cover SageSessionManager.reset() and .cancel() code paths."""
    manager = SageSessionManager(python_settings)
    try:
        session = await manager.get("mgr-ops")
        await session.evaluate("x = 42", want_latex=False, capture_stdout=False)

        await manager.reset("mgr-ops")
        # After reset, x should be undefined
        with pytest.raises(SageEvaluationError):
            await session.evaluate("x + 1", want_latex=False, capture_stdout=False)

        # Re-create state and test cancel
        session = await manager.get("mgr-ops")
        await session.evaluate("y = 10", want_latex=False, capture_stdout=False)
        await manager.cancel("mgr-ops")
        # After cancel (restart), y should be gone
        with pytest.raises(SageEvaluationError):
            session2 = await manager.get("mgr-ops")
            await session2.evaluate("y + 1", want_latex=False, capture_stdout=False)
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_cull_idle_with_shutdown_failure(python_settings):
    """Cover the exception logging branch in cull_idle."""
    eager_settings = SageSettings(
        sage_binary="sage",
        startup_code="from math import *",
        eval_timeout=5.0,
        idle_ttl=0.0,
        shutdown_grace=0.01,
        max_stdout_chars=1000,
        force_python_worker=True,
    )
    manager = SageSessionManager(eager_settings)
    session = await manager.get("cull-fail")
    await session.evaluate("z = 1", want_latex=False, capture_stdout=False)
    session.last_used_at -= 5

    # Patch shutdown to raise
    async def failing_shutdown():
        raise RuntimeError("simulated shutdown failure")

    session.shutdown = failing_shutdown
    # cull_idle uses return_exceptions=True, so the error is caught and logged
    await manager.cull_idle()

    # The session should still have been removed from the manager
    assert manager.snapshot() == []


@pytest.mark.asyncio
async def test_manager_shutdown_with_failure(python_settings):
    """Cover the exception logging branch in manager.shutdown()."""
    manager = SageSessionManager(python_settings)
    session = await manager.get("shutdown-fail")
    await session.evaluate("a = 1", want_latex=False, capture_stdout=False)

    async def failing_shutdown():
        raise RuntimeError("simulated")

    session.shutdown = failing_shutdown

    # shutdown should not propagate the exception (return_exceptions=True)
    await manager.shutdown()
    assert manager.snapshot() == []


@pytest.mark.asyncio
async def test_session_shutdown_noop_when_not_started(python_settings):
    """Cover shutdown early return when no process exists."""
    session = SageSession("noop-shutdown", python_settings)
    await session.shutdown()  # should be a no-op


@pytest.mark.asyncio
async def test_session_is_alive(python_settings):
    session = SageSession("alive-check", python_settings)
    assert session.is_alive() is False
    try:
        await session.ensure_started()
        assert session.is_alive() is True
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_session_should_cull(python_settings):
    session = SageSession("cull-check", python_settings)
    assert session.should_cull() is False
    session.last_used_at -= python_settings.idle_ttl + 1
    assert session.should_cull() is True


@pytest.mark.asyncio
async def test_launch_worker_no_python_interpreter(monkeypatch, python_settings):
    """Cover line 68: no python interpreter found."""
    monkeypatch.setattr(sys, "executable", "")
    import shutil as _shutil

    orig_which = _shutil.which

    def fake_which(name):
        if name in ("python3", "python"):
            return None
        return orig_which(name)

    monkeypatch.setattr(_shutil, "which", fake_which)

    session = SageSession("no-python", python_settings)
    with pytest.raises(SageProcessError, match="Unable to locate a Python interpreter"):
        await session.ensure_started()


@pytest.mark.asyncio
async def test_launch_worker_sage_venv_and_pythonpath(monkeypatch, python_settings):
    """Cover lines 80-82 (SAGE_VENV) and 85 (existing PYTHONPATH)."""
    monkeypatch.setenv("SAGE_VENV", "/fake/sage/venv")
    monkeypatch.setenv("PYTHONPATH", "/existing/path")

    session = SageSession("env-paths", python_settings)
    try:
        await session.ensure_started()
        result = await session.evaluate("2 + 2", want_latex=False, capture_stdout=False)
        assert result.result == "4"
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_reset_worker_terminated(monkeypatch, python_settings):
    """Cover line 172: worker terminated during reset."""
    session = SageSession("reset-terminated", python_settings)
    fake_process = _FakeProcess()
    # readline returns empty bytes = worker died
    fake_process.stdout = _FakeReader()  # default returns b""

    async def fake_ensure_started():
        session._process = fake_process

    monkeypatch.setattr(session, "ensure_started", fake_ensure_started)

    with pytest.raises(SageProcessError, match="terminated during reset"):
        await session.reset()


@pytest.mark.asyncio
async def test_reset_worker_returns_failure(monkeypatch, python_settings):
    """Cover line 175: worker returns ok=False during reset."""
    import json

    session = SageSession("reset-fail", python_settings)
    fake_process = _FakeProcess()
    fake_process.stdout = _FakeReader(json.dumps({"ok": False}).encode() + b"\n")

    async def fake_ensure_started():
        session._process = fake_process

    monkeypatch.setattr(session, "ensure_started", fake_ensure_started)

    with pytest.raises(SageProcessError, match="Failed to reset"):
        await session.reset()


@pytest.mark.asyncio
async def test_terminate_worker_process_still_running(python_settings):
    """Cover lines 225-227: process.returncode is None (still running) during terminate."""
    session = SageSession("terminate-running", python_settings)
    await session.ensure_started()
    assert session._process is not None
    # Ensure returncode is None (process still alive)
    assert session._process.returncode is None

    await session._terminate_worker()
    assert session._process is None


@pytest.mark.asyncio
async def test_cull_idle_no_stale_sessions(python_settings):
    """Cover lines 263->261, 266: cull_idle with no stale sessions (early return)."""
    manager = SageSessionManager(python_settings)
    try:
        session = await manager.get("not-stale")
        await session.evaluate("1+1", want_latex=False, capture_stdout=False)
        # Session is fresh, so nothing should be culled
        await manager.cull_idle()
        assert len(manager.snapshot()) == 1
    finally:
        await manager.shutdown()
