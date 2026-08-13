import asyncio
import contextlib
import json
import sys

import pytest

from sagemath_mcp.config import SageSettings
from sagemath_mcp.session import (
    SageEvaluationError,
    SageProcessError,
    SageSession,
    SageSessionManager,
)
from sagemath_mcp.tools import core as core_tools


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
    pytest.importorskip("sagemath_mcp.server")
    runtime = pytest.importorskip("sagemath_mcp.runtime")
    original_limit = runtime.SESSION_MANAGER.settings.max_stdout_chars
    runtime.SESSION_MANAGER.settings.max_stdout_chars = 8
    try:
        truncated = core_tools._truncate_stdout("0123456789")
        assert truncated.startswith("01234567")
        assert "output truncated" in truncated
    finally:
        runtime.SESSION_MANAGER.settings.max_stdout_chars = original_limit


def test_truncate_stdout_with_non_int_limit(monkeypatch):
    pytest.importorskip("sagemath_mcp.server")
    runtime = pytest.importorskip("sagemath_mcp.runtime")
    import types

    # Patch where _truncate_stdout reads it, which is its own module now.
    monkeypatch.setattr(
        core_tools, "DEFAULT_SETTINGS", types.SimpleNamespace(max_stdout_chars=5)
    )
    monkeypatch.setattr(runtime.SESSION_MANAGER.settings, "max_stdout_chars", 5.5)
    result = core_tools._truncate_stdout("0123456789")
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

    def last_request_id(self) -> str | None:
        """The id of the most recent request written, if any."""
        lines = [line for line in bytes(self.data).splitlines() if line.strip()]
        for line in reversed(lines):
            try:
                return json.loads(line.decode("utf-8")).get("id")
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
        return None

    async def wait_closed(self) -> None:
        return None


class _FakeReader:
    """A stand-in worker stdout.

    *echo_id_from* lets the canned response carry the id of the request that was
    just written, which is what the real worker does. Without it the reader
    answers with a line that belongs to no request, and the session correctly
    refuses to accept it.
    """

    def __init__(self, data: bytes = b"", echo_id_from: "_FakeWriter | None" = None):
        self._data = data
        self._echo_id_from = echo_id_from

    async def readline(self) -> bytes:
        if self._echo_id_from is None:
            return self._data
        request_id = self._echo_id_from.last_request_id()
        if request_id is None:
            return self._data
        message = json.loads(self._data.decode("utf-8"))
        message["id"] = request_id
        return json.dumps(message).encode("utf-8") + b"\n"


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
    fake_process.stdout = _FakeReader(
        json.dumps({"ok": False}).encode() + b"\n", echo_id_from=fake_process.stdin
    )

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


# ---------------------------------------------------------------------------
# Code journal and session persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_code_journal_records_evaluations(python_settings):
    """Verify that successful evaluations are recorded in the journal."""
    session = SageSession("journal-test", python_settings)
    try:
        await session.evaluate("x = 42", want_latex=False, capture_stdout=False)
        await session.evaluate("y = x + 1", want_latex=False, capture_stdout=False)
        assert len(session._code_journal) == 2
        assert "x = 42" in session._code_journal[0]
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_code_journal_cleared_on_reset(python_settings):
    """Verify that reset clears the journal."""
    session = SageSession("journal-reset", python_settings)
    try:
        await session.evaluate("a = 1", want_latex=False, capture_stdout=False)
        assert len(session._code_journal) == 1
        await session.reset()
        assert len(session._code_journal) == 0
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_journal_save_and_load(python_settings, tmp_path):
    """Test saving and loading a code journal to/from disk."""
    settings = SageSettings(
        sage_binary="sage",
        startup_code="from math import *",
        eval_timeout=5.0,
        idle_ttl=10.0,
        shutdown_grace=1.0,
        max_stdout_chars=1000,
        force_python_worker=True,
        persist_sessions=True,
        persist_dir=str(tmp_path),
    )
    session = SageSession("persist-test", settings)
    try:
        await session.evaluate("total = 100", want_latex=False, capture_stdout=False)
        await session.evaluate("half = total / 2", want_latex=False, capture_stdout=False)
        session.save_journal()

        journal_path = session._persist_path()
        assert journal_path.exists()

        loaded = SageSession.load_journal(journal_path)
        assert len(loaded) == 2
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_journal_save_noop_when_disabled(python_settings):
    """save_journal is a no-op when persistence is disabled."""
    session = SageSession("no-persist", python_settings)
    try:
        await session.evaluate("x = 1", want_latex=False, capture_stdout=False)
        session.save_journal()  # should not raise
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_restore_from_journal(python_settings):
    """Test replaying a journal to restore session state."""
    session = SageSession("replay-test", python_settings)
    try:
        replayed = await session.restore_from_journal(
            ["val = 99", "val + 1"]
        )
        assert replayed == 2
        result = await session.evaluate("val", want_latex=False, capture_stdout=False)
        assert result.result == "99"
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_restore_from_journal_stops_on_error(python_settings):
    """Journal replay stops at first error and returns partial count."""
    session = SageSession("replay-error", python_settings)
    try:
        replayed = await session.restore_from_journal(
            ["a = 1", "raise ValueError('boom')", "b = 2"]
        )
        assert replayed == 1  # only first entry succeeded
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_manager_shutdown_saves_journals(tmp_path):
    """Manager.shutdown() persists journals for all sessions."""
    settings = SageSettings(
        sage_binary="sage",
        startup_code="from math import *",
        eval_timeout=5.0,
        idle_ttl=10.0,
        shutdown_grace=1.0,
        max_stdout_chars=1000,
        force_python_worker=True,
        persist_sessions=True,
        persist_dir=str(tmp_path),
    )
    manager = SageSessionManager(settings)
    session = await manager.get("shutdown-persist")
    await session.evaluate("x = 42", want_latex=False, capture_stdout=False)
    await manager.shutdown()

    journal_path = session._persist_path()
    assert journal_path.exists()


@pytest.mark.asyncio
async def test_manager_restores_journal_on_get(tmp_path):
    """Manager.get() replays persisted journal for a new session."""
    settings = SageSettings(
        sage_binary="sage",
        startup_code="from math import *",
        eval_timeout=5.0,
        idle_ttl=10.0,
        shutdown_grace=1.0,
        max_stdout_chars=1000,
        force_python_worker=True,
        persist_sessions=True,
        persist_dir=str(tmp_path),
    )
    # First: create and save a session
    manager1 = SageSessionManager(settings)
    s1 = await manager1.get("restore-test")
    await s1.evaluate("saved_var = 123", want_latex=False, capture_stdout=False)
    await manager1.shutdown()

    # Second: get the same session_id — should restore
    manager2 = SageSessionManager(settings)
    s2 = await manager2.get("restore-test")
    result = await s2.evaluate("saved_var", want_latex=False, capture_stdout=False)
    assert result.result == "123"
    await manager2.shutdown()


@pytest.mark.asyncio
async def test_terminate_worker_without_stdin(python_settings):
    """Cover branch 265->269: process exists but stdin is None."""
    session = SageSession("no-stdin", python_settings)
    await session.ensure_started()
    # Simulate stdin already closed
    session._process.stdin = None
    await session._terminate_worker()
    assert session._process is None


@pytest.mark.asyncio
async def test_terminate_worker_already_exited(python_settings):
    """Cover branch 269->272: process already exited (returncode set)."""
    session = SageSession("already-exited", python_settings)
    await session.ensure_started()
    # Kill the process first so returncode is set
    session._process.kill()
    await session._process.wait()
    assert session._process.returncode is not None
    # Now terminate should skip kill() since it already exited
    await session._terminate_worker()
    assert session._process is None


@pytest.mark.asyncio
async def test_manager_get_empty_journal_file(tmp_path):
    """Cover branch 295->301: journal file exists but is empty list."""
    import json

    settings = SageSettings(
        sage_binary="sage",
        startup_code="from math import *",
        eval_timeout=5.0,
        idle_ttl=10.0,
        shutdown_grace=1.0,
        max_stdout_chars=1000,
        force_python_worker=True,
        persist_sessions=True,
        persist_dir=str(tmp_path),
    )
    # Write an empty journal
    (tmp_path / "empty-journal.journal.json").write_text(json.dumps([]))

    manager = SageSessionManager(settings)
    try:
        session = await manager.get("empty-journal")
        # Should not crash, just skip restore
        assert session._code_journal == []
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_shutdown_journal_save_failure(tmp_path, python_settings):
    """Cover lines 339-340: save_journal raises during shutdown."""
    manager = SageSessionManager(python_settings)
    session = await manager.get("save-fail")
    await session.evaluate("x = 1", want_latex=False, capture_stdout=False)

    # Make save_journal raise
    def broken_save():
        raise OSError("disk full")

    session.save_journal = broken_save

    # shutdown should not propagate the exception
    await manager.shutdown()
    assert manager.snapshot() == []


@pytest.mark.asyncio
async def test_interrupt_preserves_namespace(python_settings):
    """Interrupting must abandon the computation, not the variables.

    This is the difference from cancel(), which restarts the worker and drops
    everything the caller has built up.
    """
    session = SageSession("interrupt-keeps-state", python_settings)
    try:
        await session.evaluate("treasure = 12345", want_latex=False, capture_stdout=False)

        async def long_running():
            with pytest.raises(SageEvaluationError) as excinfo:
                await session.evaluate(
                    "x = 0\nfor i in range(10**9):\n    x += i\nx",
                    want_latex=False,
                    capture_stdout=False,
                )
            return excinfo.value

        task = asyncio.create_task(long_running())
        await asyncio.sleep(0.5)
        assert await session.interrupt() is True
        error = await task
        assert error.error_type == "Interrupted"

        # The whole point: state survived.
        result = await session.evaluate("treasure", want_latex=False, capture_stdout=False)
        assert result.result == "12345"
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_interrupt_reports_when_no_worker(python_settings):
    """Interrupting a session that never started is a no-op, not an error."""
    session = SageSession("interrupt-no-worker", python_settings)
    assert await session.interrupt() is False


@pytest.mark.asyncio
async def test_interrupt_while_idle_leaves_worker_usable(python_settings):
    """A stray interrupt with nothing running must not kill the worker.

    This asserted True until the idle worker was found to wedge under real
    Sage: the SIGINT arrived while it was blocked in readline(), where there is
    no computation to abort, and it could not answer the next request. The
    pure-Python worker swallowed it, which is why only the Sage suite showed it.
    Now nothing is signalled at all and False means "nothing was running".
    """
    session = SageSession("interrupt-idle", python_settings)
    try:
        await session.evaluate("kept = 7", want_latex=False, capture_stdout=False)
        assert await session.interrupt() is False
        await asyncio.sleep(0.3)
        result = await session.evaluate("kept", want_latex=False, capture_stdout=False)
        assert result.result == "7"
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_named_sessions_are_isolated(python_settings):
    """Workspaces under one client must not share variables."""
    manager = SageSessionManager(python_settings)
    try:
        curves = await manager.get(manager.key_for("client", "curves"))
        scratch = await manager.get(manager.key_for("client", "scratch"))
        assert curves is not scratch

        await curves.evaluate("only_here = 1", want_latex=False, capture_stdout=False)
        with pytest.raises(SageEvaluationError):
            await scratch.evaluate("only_here", want_latex=False, capture_stdout=False)
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_default_session_key_is_unchanged(python_settings):
    """The default workspace keys on the bare scope.

    Journal filenames derive from the key, so changing this would orphan every
    previously persisted session.
    """
    manager = SageSessionManager(python_settings)
    assert manager.key_for("client") == "client"
    assert manager.key_for("client", "default") == "client"
    assert manager.key_for("client", "curves") == "client::curves"
    assert manager.split_key("client") == ("client", "default")
    assert manager.split_key("client::curves") == ("client", "curves")


@pytest.mark.asyncio
async def test_list_and_stop_named_sessions(python_settings):
    manager = SageSessionManager(python_settings)
    try:
        await manager.get(manager.key_for("alice", "a"))
        await manager.get(manager.key_for("alice", "b"))
        await manager.get(manager.key_for("bob", "c"))

        listed = await manager.list_for_scope("alice")
        assert [entry["name"] for entry in listed] == ["a", "b"]
        assert all(entry["alive"] for entry in listed)

        assert await manager.stop("alice", "a") is True
        assert [e["name"] for e in await manager.list_for_scope("alice")] == ["b"]
        # Other clients are unaffected.
        assert [e["name"] for e in await manager.list_for_scope("bob")] == ["c"]
        # Stopping something that is not there reports it rather than raising.
        assert await manager.stop("alice", "a") is False
    finally:
        await manager.shutdown()


def test_named_session_journal_filename_is_safe(tmp_path):
    """"::" must not reach the filesystem."""
    settings = SageSettings(
        force_python_worker=True, persist_sessions=True, persist_dir=str(tmp_path)
    )
    session = SageSession("client::curves", settings)
    path = session._persist_path()
    assert path is not None
    assert "::" not in path.name
    assert path.name.startswith("client__curves-")
    assert path.name.endswith(".journal.json")


@pytest.mark.parametrize(
    "name",
    ["a/b", "a?b", "a:b", "a b", "a__b", "a\\b", "ünïcode", "a" * 80, "a.b"],
)
def test_journal_paths_are_unique_per_workspace(tmp_path, name):
    """Distinct workspaces must never share a journal file.

    Replacing unsafe characters with "_" was not injective: "a/b" and "a?b" both
    became "a_b", so one workspace could overwrite another's journal and later
    restore the wrong code into its namespace.
    """
    settings = SageSettings(
        force_python_worker=True, persist_sessions=True, persist_dir=str(tmp_path)
    )
    manager = SageSessionManager(settings)
    key = manager.key_for("client", name)
    path = SageSession(key, settings)._persist_path()
    assert path is not None
    # No separator or traversal may survive into the filename.
    assert "/" not in path.name and "\\" not in path.name
    assert ".." not in path.name


def test_journal_paths_do_not_collide(tmp_path):
    """The specific collision from the review: a/b vs a?b."""
    settings = SageSettings(
        force_python_worker=True, persist_sessions=True, persist_dir=str(tmp_path)
    )
    manager = SageSessionManager(settings)
    names = ["a/b", "a?b", "a:b", "a_b", "a__b", "a b"]
    paths = {
        SageSession(manager.key_for("client", name), settings)._persist_path()
        for name in names
    }
    assert len(paths) == len(names), "distinct workspaces mapped to the same journal file"


@pytest.mark.asyncio
async def test_idle_culling_persists_the_journal(tmp_path):
    """Culling must not silently discard state that persistence promised to keep.

    shutdown() and stop() saved journals; cull_idle did not, so the ordinary
    idle lifecycle threw the state away.
    """
    settings = SageSettings(
        force_python_worker=True,
        persist_sessions=True,
        persist_dir=str(tmp_path),
        idle_ttl=0.0,
    )
    manager = SageSessionManager(settings)
    try:
        session = await manager.get("cull-persist")
        await session.evaluate("survivor = 4321", want_latex=False, capture_stdout=False)
        assert session._code_journal, "journal should hold the assignment"

        await asyncio.sleep(0.05)
        await manager.cull_idle()

        restored = await manager.get("cull-persist")
        result = await restored.evaluate("survivor", want_latex=False, capture_stdout=False)
        assert result.result == "4321", "culling discarded the journal"
    finally:
        await manager.shutdown()


def test_legacy_journal_is_still_found_after_the_rename(tmp_path):
    """Upgrading must not orphan journals written by earlier versions.

    The digest was added so distinct workspaces cannot collide, but it changed
    every filename -- including plain default sessions, whose journal used to be
    named after the session id alone.
    """
    settings = SageSettings(
        force_python_worker=True, persist_sessions=True, persist_dir=str(tmp_path)
    )
    session = SageSession("legacy-client", settings)

    # A journal written by the previous scheme.
    legacy = tmp_path / "legacy-client.journal.json"
    legacy.write_text(json.dumps(["heirloom = 11"]), encoding="utf-8")

    found = session.existing_journal_path()
    assert found == legacy, "the pre-digest journal was not found"
    assert SageSession.load_journal(found) == ["heirloom = 11"]


@pytest.mark.asyncio
async def test_legacy_journal_is_restored_and_migrated(tmp_path):
    settings = SageSettings(
        force_python_worker=True, persist_sessions=True, persist_dir=str(tmp_path)
    )
    (tmp_path / "migrate-me.journal.json").write_text(
        json.dumps(["heirloom = 11"]), encoding="utf-8"
    )

    manager = SageSessionManager(settings)
    try:
        session = await manager.get("migrate-me")
        result = await session.evaluate("heirloom", want_latex=False, capture_stdout=False)
        assert result.result == "11", "legacy state was not restored"

        session.save_journal()
        assert session._persist_path().exists(), "journal was not written under the new name"
        assert not (tmp_path / "migrate-me.journal.json").exists(), (
            "the legacy file should be retired so the two schemes cannot diverge"
        )
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_reset_after_a_cancelled_evaluation_does_not_read_the_stale_response(tmp_path):
    """reset() must match response IDs like evaluate() does.

    A cancelled evaluation leaves its response in the pipe. reset() read the
    next line unconditionally, so it consumed that stale line, saw a response
    for a different request and failed -- and the evaluation after it then had
    to drain the reset's own response.
    """
    settings = SageSettings(force_python_worker=True, eval_timeout=30.0)
    session = SageSession("stale-reset", settings)
    await session.ensure_started()
    try:
        await session.evaluate("marker = 1", want_latex=False, capture_stdout=False)

        # Cancel mid-flight; the worker still answers, into an empty pipe.
        task = asyncio.create_task(
            session.evaluate(
                "sum(range(60000000))\nnonexistent_name",
                want_latex=False,
                capture_stdout=False,
            )
        )
        await asyncio.sleep(0.2)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        await session.reset()          # used to raise SageProcessError
        result = await session.evaluate("2 + 2", want_latex=False, capture_stdout=False)
        assert result.result == "4", "the evaluation after reset read a stale response"
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_worker_responses_without_the_expected_id_are_not_accepted(tmp_path):
    """An ID-less line must not be taken as a request's final response."""
    settings = SageSettings(force_python_worker=True, eval_timeout=30.0)
    session = SageSession("id-required", settings)
    await session.ensure_started()
    try:
        reader = session._process.stdout
        original = reader.readline
        lines = [
            json.dumps({"ok": True, "result_type": "expression", "result": "'spoofed'"}).encode()
            + b"\n"
        ]

        async def fake_readline():
            if lines:
                return lines.pop(0)
            return await original()

        reader.readline = fake_readline
        result = await session.evaluate("6 * 7", want_latex=False, capture_stdout=False)
        assert result.result == "42", "an ID-less response was accepted as the answer"
    finally:
        await session.shutdown()


# ---------------------------------------------------------------------------
# Worker protocol edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unparsable_worker_lines_are_skipped_not_fatal(tmp_path):
    """Anything non-JSON on the pipe is noise, not this request's answer."""
    settings = SageSettings(force_python_worker=True, eval_timeout=30.0)
    session = SageSession("noisy", settings)
    await session.ensure_started()
    try:
        reader = session._process.stdout
        original = reader.readline
        junk = [b"not json at all\n", b"<<< banner >>>\n"]

        async def fake_readline():
            if junk:
                return junk.pop(0)
            return await original()

        reader.readline = fake_readline
        result = await session.evaluate("6 * 7", want_latex=False, capture_stdout=False)
        assert result.result == "42"
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_a_worker_that_never_answers_this_request_is_abandoned(tmp_path):
    """Waiting for a matching id is unbounded if the peer repeats itself.

    A stub doing exactly that once spun here until the process ran out of
    memory, so the wait gives up after a fixed number of stale lines.
    """
    settings = SageSettings(force_python_worker=True, eval_timeout=30.0)
    session = SageSession("broken-record", settings)
    await session.ensure_started()
    try:
        stale = json.dumps({"ok": True, "id": "someone-else", "result": "'x'"}).encode() + b"\n"

        async def fake_readline():
            return stale

        session._process.stdout.readline = fake_readline
        with pytest.raises(SageProcessError, match="do not answer"):
            await session.evaluate("1 + 1", want_latex=False, capture_stdout=False)
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_interrupt_reports_false_when_the_worker_is_gone(tmp_path, monkeypatch):
    """A dead process cannot be interrupted, and that is not an error."""
    settings = SageSettings(force_python_worker=True, eval_timeout=30.0)
    session = SageSession("gone", settings)
    await session.ensure_started()
    try:
        def boom(_signal):
            raise ProcessLookupError("no such process")

        monkeypatch.setattr(session._process, "send_signal", boom)
        session._in_flight = "pretend-a-request-is-running"
        assert await session.interrupt() is False
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_manager_interrupt_is_false_for_an_unknown_session(tmp_path):
    manager = SageSessionManager(SageSettings(force_python_worker=True))
    try:
        assert await manager.interrupt("never-started") is False
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_culling_still_reclaims_a_worker_when_the_journal_cannot_be_saved(
    tmp_path, monkeypatch
):
    """A persistence failure must not strand the worker it was culling."""
    settings = SageSettings(
        force_python_worker=True, idle_ttl=0.0, persist_sessions=True,
        persist_dir=str(tmp_path),
    )
    manager = SageSessionManager(settings)
    try:
        session = await manager.get("doomed")
        await session.evaluate("kept = 1", want_latex=False, capture_stdout=False)

        def boom():
            raise OSError("disk full")

        monkeypatch.setattr(session, "save_journal", boom)
        await manager.cull_idle()
        assert not session.is_alive(), "the worker survived a failed journal save"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_stdout_events_are_dropped_when_nobody_is_listening(tmp_path):
    """A non-streaming caller still has to skip the worker's stdout events."""
    settings = SageSettings(force_python_worker=True, eval_timeout=30.0)
    session = SageSession("no-listener", settings)
    await session.ensure_started()
    try:
        reader = session._process.stdout
        original = reader.readline
        held: list[bytes] = []

        async def fake_readline():
            if held:
                return held.pop(0)
            raw = await original()
            request_id = json.loads(raw.decode("utf-8")).get("id")
            held.append(raw)          # give the real answer back next time
            # A stdout event for this very request, with nobody listening.
            return json.dumps(
                {"type": "stdout", "id": request_id, "text": "ignored"}
            ).encode() + b"\n"

        reader.readline = fake_readline
        result = await session.evaluate("11 * 11", want_latex=False, capture_stdout=False)
        assert result.result == "121"
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_interrupting_an_idle_worker_signals_nothing(tmp_path):
    """An idle worker must not be signalled at all.

    It is blocked in readline(), where a SIGINT has no computation to abort.
    Sending one anyway left a real Sage worker unable to answer the next
    request: that evaluation timed out and the worker was restarted, losing
    exactly the namespace the interrupt was supposed to protect -- while the
    tool reported "state preserved".
    """
    manager = SageSessionManager(SageSettings(force_python_worker=True))
    try:
        session = await manager.get("idle")
        await session.evaluate("marker = 1", want_latex=False, capture_stdout=False)

        assert await manager.interrupt("idle") is False, "signalled an idle worker"

        # And the session is still perfectly usable afterwards.
        result = await session.evaluate("marker", want_latex=False, capture_stdout=False)
        assert result.result == "1"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_interrupting_a_running_computation_keeps_the_namespace(tmp_path):
    """The case interrupt exists for: stop the work, keep the variables."""
    manager = SageSessionManager(SageSettings(force_python_worker=True, eval_timeout=30.0))
    try:
        session = await manager.get("busy")
        await session.evaluate("marker = 2", want_latex=False, capture_stdout=False)

        task = asyncio.create_task(
            session.evaluate("sum(range(80000000))", want_latex=False, capture_stdout=False)
        )
        await asyncio.sleep(0.2)
        assert await manager.interrupt("busy") is True, "a running computation was not signalled"

        with contextlib.suppress(Exception):
            await task
        result = await session.evaluate("marker", want_latex=False, capture_stdout=False)
        assert result.result == "2", "the namespace did not survive the interrupt"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_stdout_events_reach_the_callback_as_they_arrive(tmp_path):
    """The streaming path: each completed line is dispatched while the code runs."""
    settings = SageSettings(force_python_worker=True, eval_timeout=30.0)
    session = SageSession("streamer", settings)
    seen: list[str] = []

    async def on_stdout(text: str) -> None:
        seen.append(text)

    await session.ensure_started()
    try:
        result = await session.evaluate(
            "for _i in range(3):\n    print(_i)\n",
            want_latex=False,
            capture_stdout=True,
            on_stdout=on_stdout,
        )
        assert seen == ["0", "1", "2"]
        assert result.stdout == "0\n1\n2\n"
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_a_missing_sage_binary_is_reported_clearly(monkeypatch):
    """The message has to name the binary and the setting that changes it."""
    import shutil as shutil_module

    settings = SageSettings(force_python_worker=False, sage_binary="definitely-not-sage")
    session = SageSession("no-sage", settings)
    monkeypatch.setattr(shutil_module, "which", lambda _name: None)
    with pytest.raises(SageProcessError, match="definitely-not-sage"):
        await session.ensure_started()


@pytest.mark.asyncio
async def test_the_sage_worker_is_launched_through_the_configured_binary(monkeypatch):
    """Not force_python_worker: the real command is `sage -python -m ...`."""
    import shutil as shutil_module

    from sagemath_mcp import session as session_module

    recorded: dict[str, tuple] = {}

    async def fake_exec(*command, **kwargs):
        recorded["command"] = command
        recorded["kwargs"] = kwargs
        raise SageProcessError("stopped before spawning")

    monkeypatch.setattr(shutil_module, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", fake_exec)

    settings = SageSettings(force_python_worker=False, sage_binary="sage")
    session = SageSession("real-sage", settings)
    with pytest.raises(SageProcessError):
        await session.ensure_started()

    assert recorded["command"][:4] == ("sage", "-python", "-m", "sagemath_mcp._sage_worker")


def test_a_workspace_with_unsafe_characters_adopts_no_ambiguous_legacy_journal(tmp_path):
    """"a/b" and "a?b" both sanitised to "a_b", so that filename proves nothing."""
    settings = SageSettings(
        force_python_worker=True, persist_sessions=True, persist_dir=str(tmp_path)
    )
    session = SageSession("a/b", settings)
    legacy_names = [path.name for path in session._legacy_persist_paths()]
    assert "a_b.journal.json" not in legacy_names, (
        "adopted a legacy file that could belong to a different workspace"
    )


@pytest.mark.asyncio
async def test_a_slow_stdout_callback_does_not_keep_the_worker_marked_busy(tmp_path):
    """The computing flag must end when the worker's answer arrives.

    A streaming caller's callback is arbitrary code and can be slow. If awaiting
    it blocks the read loop, the worker can finish, print its response and go
    back to waiting for input -- genuinely idle -- while the session still
    believes a computation is running. interrupt() then signals an idle worker,
    which is the exact unsafe path this flag was introduced to close.
    """
    settings = SageSettings(force_python_worker=True, eval_timeout=30.0)
    session = SageSession("slow-callback", settings)
    await session.ensure_started()
    release = asyncio.Event()
    first_line = asyncio.Event()

    async def blocking_on_stdout(text: str) -> None:
        first_line.set()
        await release.wait()          # hold the callback open

    try:
        task = asyncio.create_task(
            session.evaluate(
                "print('one')\nprint('two')\n42\n",
                want_latex=False,
                capture_stdout=True,
                on_stdout=blocking_on_stdout,
            )
        )
        await asyncio.wait_for(first_line.wait(), timeout=10)
        # Give the worker time to finish and answer while the callback is held.
        await asyncio.sleep(0.5)

        assert await session.interrupt() is False, (
            "signalled a worker that had already answered and gone idle"
        )

        release.set()
        result = await asyncio.wait_for(task, timeout=10)
        assert result.result == "42"
    finally:
        release.set()
        await session.shutdown()
