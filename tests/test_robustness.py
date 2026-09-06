"""Session/worker robustness fixes from the 2026-09-06 external review.

Four findings, each reproduced against the shape it happened in:

1. Worker startup raced outside any lock, so two simultaneous first requests to
   one session launched two workers and leaked one.
2. Nothing bounded the number of live sessions, so a client opening a fresh
   named workspace per call could exhaust the host a worker at a time.
3. The ~30 helper tools evaluated through `_evaluate_structured`, which never
   touched the monitoring counters, so the metrics accounted for `evaluate_sage`
   alone.
4. `/health` and the Helm readiness probe reported process liveness without
   testing that Sage can compute, so a pod could route traffic to a dead
   backend.
"""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest

from sagemath_mcp import monitoring, runtime, server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.session import SageProcessError, SageSession, SageSessionManager

from .conftest import FakeContext

requires_sage = pytest.mark.skipif(
    shutil.which("sage") is None, reason="Sage executable not available"
)


class _FakeProcess:
    """A live-looking process: ensure_started treats returncode None as alive."""

    returncode = None


# --- 1. Worker startup no longer races ---------------------------------------


async def test_concurrent_first_requests_launch_one_worker(monkeypatch):
    """Two simultaneous first calls to one session must not double-launch.

    A scheduling probe produced two live workers for two concurrent first
    requests; the second leaked. The double-checked startup lock closes it.
    The patched launch yields (await) before marking itself done, which is the
    exact window the unguarded code interleaved in -- without the lock this
    counter reaches the number of racers.
    """
    session = SageSession("race", SageSettings(force_python_worker=True))
    launches = 0

    async def counting_launch() -> None:
        nonlocal launches
        await asyncio.sleep(0)  # the interleave window
        launches += 1
        session._process = _FakeProcess()

    monkeypatch.setattr(session, "_launch_worker", counting_launch)
    await asyncio.gather(*(session.ensure_started() for _ in range(8)))
    assert launches == 1


async def test_ensure_started_relaunches_a_dead_worker(monkeypatch):
    """The guard is 'alive', not 'ever started': a dead worker must relaunch."""
    session = SageSession("dead", SageSettings(force_python_worker=True))
    launches = 0

    async def counting_launch() -> None:
        nonlocal launches
        launches += 1
        session._process = _FakeProcess()

    monkeypatch.setattr(session, "_launch_worker", counting_launch)
    await session.ensure_started()
    session._process.returncode = 1  # it died
    await session.ensure_started()
    assert launches == 2


# --- 2. The session ceiling --------------------------------------------------


async def test_the_session_ceiling_refuses_a_new_worker_but_not_an_existing_one(
    monkeypatch,
):
    manager = SageSessionManager(SageSettings(force_python_worker=True, max_sessions=2))

    # Do not actually spawn: routing and the ceiling are the claim here.
    async def no_launch(self) -> None:
        self._process = _FakeProcess()

    monkeypatch.setattr(SageSession, "ensure_started", no_launch)

    await manager.get("a")
    await manager.get("b")
    with pytest.raises(SageProcessError, match="Session limit reached"):
        await manager.get("c")
    # An existing session is always reachable -- the ceiling is a creation gate,
    # never a lock-out from state a client already holds.
    assert await manager.get("a") is not None


async def test_a_zero_ceiling_is_unbounded(monkeypatch):
    manager = SageSessionManager(SageSettings(force_python_worker=True, max_sessions=0))

    async def no_launch(self) -> None:
        self._process = _FakeProcess()

    monkeypatch.setattr(SageSession, "ensure_started", no_launch)
    for i in range(20):
        await manager.get(f"s{i}")
    assert len(manager.snapshot()) == 20


def test_the_ceiling_is_configurable_from_the_environment(monkeypatch):
    monkeypatch.setenv("SAGEMATH_MCP_MAX_SESSIONS", "7")
    assert SageSettings.from_env().max_sessions == 7


# --- 3. Helper-tool evaluations reach the metrics ----------------------------


async def test_a_helper_tool_failure_is_recorded(sage_manager, monkeypatch):
    """A specialized tool whose evaluation errors must count, and count as a
    security failure when that is what it was.

    Driven by injecting the error rather than by the prelude failing: the
    generated prelude imports `sage.all`, which succeeds wherever Sage is
    installed (the integration container included), so relying on it made the
    outcome depend on the runtime. Injection tests exactly the branch that
    matters -- `_evaluate_structured` recording the failure -- everywhere.
    Before the fix the helper tools recorded nothing at all, pass or fail.
    """
    from sagemath_mcp.session import SageEvaluationError

    async def raises_security(self, *args, **kwargs):
        raise SageEvaluationError(
            "refused", error_type="SecurityViolation", stdout="", traceback="tb"
        )

    monkeypatch.setattr(SageSession, "evaluate", raises_security)
    monitoring.reset_metrics()
    before = monitoring.snapshot()["attempts"]
    with pytest.raises(SageEvaluationError):
        await server.calculate_expression("6 * 7", ctx=FakeContext("metrics-client"))
    after = monitoring.snapshot()
    assert after["attempts"] == before + 1
    assert after["failures"] >= 1
    assert after["security_failures"] >= 1


async def test_a_helper_tool_process_error_is_recorded(sage_manager, monkeypatch):
    """A dead worker under a helper tool counts too, not only under evaluate_sage."""
    monitoring.reset_metrics()

    async def dies(self, *args, **kwargs):
        raise SageProcessError("Sage worker terminated unexpectedly.")

    monkeypatch.setattr(SageSession, "evaluate", dies)
    before = monitoring.snapshot()["attempts"]
    with pytest.raises(SageProcessError):
        await server.calculate_expression("6 * 7", ctx=FakeContext("proc-err"))
    after = monitoring.snapshot()
    assert after["attempts"] == before + 1
    assert after["failures"] >= 1


@requires_sage
async def test_a_helper_tool_success_is_recorded(monkeypatch):
    manager = SageSessionManager(SageSettings())
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    monitoring.reset_metrics()
    try:
        result = await server.calculate_expression("factorial(5)", ctx=FakeContext("m"))
        assert result["numeric"] == 120.0
        snap = monitoring.snapshot()
        assert snap["successes"] >= 1
        assert snap["attempts"] >= 1
    finally:
        await manager.shutdown()


# --- 4. Readiness runs the real Sage path ------------------------------------


class _StubEval:
    def __init__(self, result: str | None, exc: Exception | None = None):
        self._result = result
        self._exc = exc

    async def evaluate(self, code, **kwargs):
        if self._exc is not None:
            raise self._exc

        class _R:
            result = self._result

        return _R()


def _readiness_manager(monkeypatch, stub):
    async def fake_get(key: str):
        assert key == server._READINESS_SESSION_KEY
        return stub

    manager = SageSessionManager(SageSettings())
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fake_get)


async def test_readiness_is_ready_when_sage_computes(monkeypatch):
    _readiness_manager(monkeypatch, _StubEval("2"))
    response = await server.readiness_check(object())
    assert response.status_code == 200
    body = json.loads(bytes(response.body).decode("utf-8"))
    assert body["status"] == "ready"
    assert "elapsed_ms" in body


async def test_readiness_is_unready_on_a_wrong_answer(monkeypatch):
    """A backend that computes but computes wrong is not ready either."""
    _readiness_manager(monkeypatch, _StubEval("3"))
    response = await server.readiness_check(object())
    assert response.status_code == 503
    assert json.loads(bytes(response.body).decode("utf-8"))["status"] == "unready"


async def test_readiness_is_unready_when_the_worker_fails(monkeypatch):
    _readiness_manager(monkeypatch, _StubEval(None, exc=SageProcessError("no worker")))
    response = await server.readiness_check(object())
    assert response.status_code == 503
    body = json.loads(bytes(response.body).decode("utf-8"))
    assert body["status"] == "unready"
    assert "no worker" in body["reason"]


async def test_liveness_stays_shallow(monkeypatch):
    """Liveness must not depend on a worker; a busy backend is still alive."""
    called = False

    async def fail_if_touched(key: str):
        nonlocal called
        called = True
        raise AssertionError("liveness must not evaluate")

    manager = SageSessionManager(SageSettings())
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fail_if_touched)
    response = await server.health_check(object())
    assert response.status_code == 200
    assert called is False
