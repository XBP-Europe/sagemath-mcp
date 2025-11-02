import asyncio
import contextlib
import json
import shutil

import pytest

from sagemath_mcp import server
from sagemath_mcp.models import EvaluateResult
from sagemath_mcp.monitoring import reset_metrics
from sagemath_mcp.session import SageEvaluationError, SageSessionManager, WorkerResult


class FakeContext:
    def __init__(self, session_id: str = "session"):
        self.session_id = session_id
        self.info_messages: list[str] = []
        self.error_messages: list[str] = []
        self.warning_messages: list[str] = []
        self.progress_events: list[tuple[float, float | None, str | None]] = []

    async def info(self, message: str) -> None:
        self.info_messages.append(message)

    async def error(self, message: str) -> None:
        self.error_messages.append(message)

    async def warning(self, message: str) -> None:
        self.warning_messages.append(message)

    async def report_progress(
        self,
        progress: float,
        total: float | None,
        message: str | None,
    ) -> None:
        self.progress_events.append((progress, total, message))


@pytest.mark.asyncio
async def test_cull_loop_runs_until_cancelled(monkeypatch):
    calls: list[int] = []

    async def fake_cull_idle():
        calls.append(1)

    monkeypatch.setattr(server.SESSION_MANAGER, "cull_idle", fake_cull_idle)

    task = asyncio.create_task(server._cull_loop(interval=0.01))
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

    monkeypatch.setattr(server, "_cull_loop", fake_cull_loop)

    async with server._lifespan(server.mcp):
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

    monkeypatch.setattr(server, "_cull_loop", fake_cull_loop)

    async with server._lifespan(server.mcp):
        await asyncio.sleep(0)

    assert events == ["cancelled"]


@pytest.mark.asyncio
async def test_progress_heartbeat_emits(monkeypatch):
    ctx = FakeContext("heartbeat")
    task = asyncio.create_task(server._progress_heartbeat(ctx, interval=0.01))
    await asyncio.sleep(0.03)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert ctx.progress_events


@pytest.mark.asyncio
async def test_evaluate_sage_reports_progress(monkeypatch):
    fake_result = WorkerResult(
        result_type="expression",
        result="42",
        latex=None,
        stdout="",
        elapsed_ms=12.3,
    )

    class FakeSession:
        async def evaluate(self, *args, **kwargs) -> WorkerResult:
            await asyncio.sleep(0)
            return fake_result

    monkeypatch.setattr(server, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))

    async def fake_get(session_id: str) -> FakeSession:
        return FakeSession()

    async def fake_cancel(session_id: str) -> None:
        raise AssertionError("cancel should not be called")

    monkeypatch.setattr(server.SESSION_MANAGER, "get", fake_get)
    monkeypatch.setattr(server.SESSION_MANAGER, "cancel", fake_cancel)

    ctx = FakeContext()
    payload: EvaluateResult = await server.evaluate_sage.fn("x = 6", ctx=ctx)

    assert payload.result == "42"
    assert ctx.info_messages
    assert ctx.progress_events
    assert ctx.progress_events[-1] == (1.0, 1.0, "Sage evaluation complete")


@pytest.mark.asyncio
async def test_evaluate_sage_handles_cancel(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.cancelled = False

        async def evaluate(self, *args, **kwargs):
            raise asyncio.CancelledError

    fake_session = FakeSession()

    async def fake_get(session_id: str) -> FakeSession:
        return fake_session

    async def fake_cancel(session_id: str) -> None:
        fake_session.cancelled = True

    monkeypatch.setattr(server, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(server.SESSION_MANAGER, "get", fake_get)
    monkeypatch.setattr(server.SESSION_MANAGER, "cancel", fake_cancel)

    ctx = FakeContext()
    with pytest.raises(asyncio.CancelledError):
        await server.evaluate_sage.fn("long_calculation()", ctx=ctx)

    assert fake_session.cancelled is True
    assert any("cancelled" in msg.lower() for msg in ctx.warning_messages)


@pytest.mark.asyncio
async def test_evaluate_sage_process_error(monkeypatch):
    class FakeSession:
        async def evaluate(self, *args, **kwargs):
            raise server.SageProcessError("boom")

    async def fake_get(session_id: str) -> FakeSession:
        return FakeSession()

    async def fake_cancel(session_id: str) -> None:
        pass

    monkeypatch.setattr(server, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(server.SESSION_MANAGER, "get", fake_get)
    monkeypatch.setattr(server.SESSION_MANAGER, "cancel", fake_cancel)

    ctx = FakeContext()
    with pytest.raises(server.ToolError):
        await server.evaluate_sage.fn("f()", ctx=ctx)

    assert ctx.error_messages


@pytest.mark.asyncio
async def test_documentation_resource_contains_reference_link():
    links = await server.documentation_resource.fn("all", None)
    urls = {link.url for link in links}
    assert "https://doc.sagemath.org/html/en/reference" in urls


class StubSession:
    def __init__(self, result: str | None):
        self.result = result
        self.calls = []

    async def evaluate(
        self,
        code: str,
        want_latex: bool,
        capture_stdout: bool,
        timeout_seconds: float | None = None,
    ):
        self.calls.append(
            {
                "code": code,
                "want_latex": want_latex,
                "capture_stdout": capture_stdout,
                "timeout_seconds": timeout_seconds,
            }
        )
        return WorkerResult(
            result_type="expression",
            result=self.result,
            latex=None,
            stdout="",
            elapsed_ms=0.0,
        )


async def _stub_manager(monkeypatch, session: StubSession):
    manager = SageSessionManager(server.DEFAULT_SETTINGS)

    async def fake_get(session_id: str):
        return session

    async def fake_cancel(session_id: str):
        return None

    monkeypatch.setattr(server, "SESSION_MANAGER", manager)
    monkeypatch.setattr(server.SESSION_MANAGER, "get", fake_get)
    monkeypatch.setattr(server.SESSION_MANAGER, "cancel", fake_cancel)
    return manager


@pytest.mark.asyncio
async def test_calculate_expression(monkeypatch):
    session = StubSession("{'string': '42', 'numeric': 42.0}")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.calculate_expression.fn("6*7", ctx=ctx)
    assert result["string"] == "42"
    assert result["numeric"] == 42.0


@pytest.mark.asyncio
async def test_matrix_multiply(monkeypatch):
    session = StubSession("[[19.0, 22.0], [43.0, 50.0]]")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.matrix_multiply.fn([[1, 2], [3, 4]], [[5, 6], [7, 8]], ctx=ctx)
    assert result == {"product": [[19.0, 22.0], [43.0, 50.0]]}


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
    result = await server.statistics_summary.fn([1, 2, 3, 4, 5], ctx=ctx)
    assert result["mean"] == 3.0
    assert "population_std_dev" in result


@pytest.mark.asyncio
async def test_evaluate_structured_parses_literal():
    session = StubSession("[1, {'value': 2}]")
    value = await server._evaluate_structured(session, "ignored")
    assert value == [1, {"value": 2}]
    call = session.calls[-1]
    assert call["want_latex"] is False
    assert call["capture_stdout"] is False


@pytest.mark.asyncio
async def test_evaluate_structured_returns_none():
    session = StubSession(None)
    value = await server._evaluate_structured(session, "ignored")
    assert value is None


@pytest.mark.asyncio
async def test_evaluate_structured_falls_back_to_string():
    session = StubSession("Decimal('1.234')")
    value = await server._evaluate_structured(session, "ignored")
    assert value == "Decimal('1.234')"


@pytest.mark.asyncio
async def test_monitoring_resource_tracks_metrics(monkeypatch):
    reset_metrics()
    success_session = StubSession("42")
    await _stub_manager(monkeypatch, success_session)
    ctx_success = FakeContext("metrics-success")
    result = await server.evaluate_sage.fn("6*7", ctx=ctx_success)
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
        await server.evaluate_sage.fn("import os", ctx=ctx_fail)

    snapshots = await server.monitoring_resource.fn("metrics", None)
    assert snapshots
    snapshot = snapshots[0]
    assert snapshot.attempts == 2
    assert snapshot.successes == 1
    assert snapshot.failures == 1
    assert snapshot.security_failures == 1
    assert snapshot.last_security_violation


@pytest.mark.asyncio
async def test_solve_equation(monkeypatch):
    session = StubSession("['x == 1']")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.solve_equation.fn("x^2 - 1 = 0", ctx=ctx)
    assert result == {"solutions": ["x == 1"]}


@pytest.mark.asyncio
async def test_differentiate_expression(monkeypatch):
    session = StubSession("'2*x'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.differentiate_expression.fn("x^2", ctx=ctx)
    assert result == {"derivative": "2*x"}


@pytest.mark.asyncio
async def test_integrate_expression(monkeypatch):
    session = StubSession("'x^3/3'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.integrate_expression.fn("x^2", ctx=ctx)
    assert result == {"integral": "x^3/3"}


@pytest.mark.asyncio
async def test_llm_stateful_average_workflow(monkeypatch):
    from sagemath_mcp.config import SageSettings

    settings = SageSettings(
        startup_code="from math import *",
        eval_timeout=5.0,
        idle_ttl=10.0,
        shutdown_grace=1.0,
        max_stdout_chars=1000,
        force_python_worker=True,
    )
    manager = SageSessionManager(settings)

    monkeypatch.setattr(server, "SESSION_MANAGER", manager)

    ctx = FakeContext("llm-sequence")
    try:
        result1 = await server.evaluate_sage.fn("values = [1, 2, 3, 4, 5]", ctx=ctx)
        assert result1.result_type == "statement"

        result2 = await server.evaluate_sage.fn(
            "average = sum(values) / len(values)\naverage",
            ctx=ctx,
        )
        assert result2.result == "3.0"

        result3 = await server.evaluate_sage.fn(
            "values.append(6)\nsum(values)",
            ctx=ctx,
        )
        assert result3.result == "21"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_llm_reuses_defined_function(monkeypatch):
    from sagemath_mcp.config import SageSettings

    settings = SageSettings(
        startup_code="from math import *",
        eval_timeout=5.0,
        idle_ttl=10.0,
        shutdown_grace=1.0,
        max_stdout_chars=1000,
        force_python_worker=True,
    )
    manager = SageSessionManager(settings)

    monkeypatch.setattr(server, "SESSION_MANAGER", manager)

    ctx = FakeContext("llm-function")
    try:
        define = await server.evaluate_sage.fn(
            "def energy(mass, c=299792458):\n    return mass * c**2",
            ctx=ctx,
        )
        assert define.result_type == "statement"

        result = await server.evaluate_sage.fn("energy(0.001)", ctx=ctx)
        assert float(result.result) == pytest.approx(8.987551787368176e13)
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("sage") is None, reason="Sage executable not available")
async def test_calculate_expression_with_sage(monkeypatch):
    from sagemath_mcp.session import SageSession, SageSettings

    settings = SageSettings()
    session = SageSession("sage-integration", settings)

    async def fake_get(session_id: str):
        return session

    async def fake_cancel(session_id: str):
        await session.cancel()

    manager = SageSessionManager(settings)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)
    monkeypatch.setattr(server.SESSION_MANAGER, "get", fake_get)
    monkeypatch.setattr(server.SESSION_MANAGER, "cancel", fake_cancel)

    ctx = FakeContext("sage-integration")
    try:
        result = await server.calculate_expression.fn("factorial(5)", ctx=ctx)
        assert result["numeric"] == 120.0
    finally:
        await session.shutdown()
