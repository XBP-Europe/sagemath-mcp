import pytest

from sagemath_mcp.config import SageSettings
from sagemath_mcp.session import SageEvaluationError, SageSession, SageSessionManager


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
    async def readline(self) -> bytes:
        return b""


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

    async def fake_wait_for(coro, timeout):
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

    async def fake_wait_for(coro, timeout):
        coro.close()
        raise TimeoutError

    monkeypatch.setattr(session_module.asyncio, "wait_for", fake_wait_for)

    await session.shutdown()

    assert fake_process.killed is True
    assert fake_process.stdin.closed is True
