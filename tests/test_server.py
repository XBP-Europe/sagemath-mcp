import asyncio
import contextlib
import json
import shutil

import pytest
from fastmcp.exceptions import ToolError

from sagemath_mcp import server
from sagemath_mcp.models import EvaluateResult
from sagemath_mcp.monitoring import reset_metrics
from sagemath_mcp.session import SageEvaluationError, SageSessionManager, WorkerResult

from .conftest import FakeContext


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
    payload: EvaluateResult = await server.evaluate_sage("x = 6", ctx=ctx)

    assert payload.result == "42"
    assert ctx.info_messages
    assert ctx.progress_events
    assert ctx.progress_events[-1] == (1.0, 1.0, "Sage evaluation complete")


@pytest.mark.asyncio
async def test_evaluate_sage_with_latex(monkeypatch):
    fake_result = WorkerResult(
        result_type="expression",
        result="x^2",
        latex="x^{2}",
        stdout="",
        elapsed_ms=5.0,
    )

    class FakeSession:
        async def evaluate(self, *args, **kwargs) -> WorkerResult:
            assert kwargs.get("want_latex") is True
            return fake_result

    monkeypatch.setattr(server, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))

    async def fake_get(session_id: str) -> FakeSession:
        return FakeSession()

    monkeypatch.setattr(server.SESSION_MANAGER, "get", fake_get)

    ctx = FakeContext()
    payload = await server.evaluate_sage("x^2", want_latex=True, ctx=ctx)
    assert payload.latex == "x^{2}"
    assert payload.result == "x^2"


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
        await server.evaluate_sage("long_calculation()", ctx=ctx)

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
        await server.evaluate_sage("f()", ctx=ctx)

    assert ctx.error_messages


@pytest.mark.asyncio
async def test_documentation_resource_contains_reference_link():
    links = await server.documentation_resource("all", None)
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
    result = await server.calculate_expression("6*7", ctx=ctx)
    assert result["string"] == "42"
    assert result["numeric"] == 42.0


@pytest.mark.asyncio
async def test_calculate_expression_handles_literal_eval_failure(monkeypatch):
    session = StubSession("not-a-dict")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.calculate_expression("1+1", ctx=ctx)
    assert result == {"string": "not-a-dict"}


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
    assert snapshot["last_security_violation"]
    assert snapshot["last_error_details"]


@pytest.mark.asyncio
async def test_evaluate_sage_security_violation(monkeypatch):
    class ViolatingSession:
        async def evaluate(self, *args, **kwargs):
            raise SageEvaluationError(
                "blocked",
                error_type="SecurityViolation",
                stdout="",
                traceback="trace",
            )

    manager = SageSessionManager(server.DEFAULT_SETTINGS)

    async def fake_get(session_id: str):
        return ViolatingSession()

    monkeypatch.setattr(server, "SESSION_MANAGER", manager)
    monkeypatch.setattr(server.SESSION_MANAGER, "get", fake_get)

    ctx = FakeContext("violation")
    with pytest.raises(ToolError):
        await server.evaluate_sage("import os", ctx=ctx)

    assert ctx.error_messages

@pytest.mark.asyncio
async def test_documentation_resource_unknown_scope():
    result = await server.documentation_resource("missing", None)
    assert result == []


@pytest.mark.asyncio
async def test_monitoring_resource_unknown_scope():
    result = await server.monitoring_resource("other", None)
    assert result == "[]"



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
async def test_differentiate_expression(monkeypatch):
    session = StubSession("'2*x'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.differentiate_expression("x^2", ctx=ctx)
    assert result == {"derivative": "2*x", "order": 1}


@pytest.mark.asyncio
async def test_differentiate_expression_higher_order(monkeypatch):
    session = StubSession("'2'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.differentiate_expression("x^2", order=2, ctx=ctx)
    assert result == {"derivative": "2", "order": 2}


@pytest.mark.asyncio
async def test_integrate_expression(monkeypatch):
    session = StubSession("'x^3/3'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.integrate_expression("x^2", ctx=ctx)
    assert result == {"integral": "x^3/3", "definite": False}


@pytest.mark.asyncio
async def test_integrate_expression_definite(monkeypatch):
    session = StubSession("'1/3'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.integrate_expression(
        "x^2", lower_bound="0", upper_bound="1", ctx=ctx
    )
    assert result == {"integral": "1/3", "definite": True}


@pytest.mark.asyncio
async def test_integrate_expression_mixed_bounds():
    ctx = FakeContext()
    with pytest.raises(ToolError):
        await server.integrate_expression("x^2", lower_bound="0", ctx=ctx)


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
        result1 = await server.evaluate_sage("values = [1, 2, 3, 4, 5]", ctx=ctx)
        assert result1.result_type == "statement"

        result2 = await server.evaluate_sage(
            "average = sum(values) / len(values)\naverage",
            ctx=ctx,
        )
        assert result2.result == "3.0"

        result3 = await server.evaluate_sage(
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
        define = await server.evaluate_sage(
            "def energy(mass, c=299792458):\n    return mass * c**2",
            ctx=ctx,
        )
        assert define.result_type == "statement"

        result = await server.evaluate_sage("energy(0.001)", ctx=ctx)
        assert float(result.result) == pytest.approx(8.987551787368176e13)
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_simplify_expression(monkeypatch):
    session = StubSession("'x'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.simplify_expression("x + 0", ctx=ctx)
    assert result == {"simplified": "x"}


@pytest.mark.asyncio
async def test_expand_expression(monkeypatch):
    session = StubSession("'x^2 + 2*x + 1'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.expand_expression("(x+1)^2", ctx=ctx)
    assert result == {"expanded": "x^2 + 2*x + 1"}


@pytest.mark.asyncio
async def test_factor_expression(monkeypatch):
    session = StubSession("'(x - 1)*(x + 1)'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.factor_expression("x^2 - 1", ctx=ctx)
    assert result == {"factored": "(x - 1)*(x + 1)"}


@pytest.mark.asyncio
async def test_limit_expression(monkeypatch):
    session = StubSession("'1'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.limit_expression("sin(x)/x", point="0", ctx=ctx)
    assert result == {"limit": "1"}


@pytest.mark.asyncio
async def test_limit_expression_with_direction(monkeypatch):
    session = StubSession("'+Infinity'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.limit_expression(
        "1/x", point="0", direction="plus", ctx=ctx
    )
    assert result == {"limit": "+Infinity"}


@pytest.mark.asyncio
async def test_series_expansion(monkeypatch):
    session = StubSession("'1 - x^2/2 + x^4/24 + O(x^6)'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.series_expansion("cos(x)", order=6, ctx=ctx)
    assert result["series"] == "1 - x^2/2 + x^4/24 + O(x^6)"
    assert result["order"] == 6
    assert result["point"] == "0"


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
async def test_solve_ode(monkeypatch):
    session = StubSession("'_C*e^(-x)'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.solve_ode(
        "diff(y(x),x) + y(x) = 0", ctx=ctx
    )
    assert result == {"solution": "_C*e^(-x)"}


@pytest.mark.asyncio
async def test_number_theory_is_prime(monkeypatch):
    session = StubSession("True")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.number_theory_operation(
        "is_prime", 7, ctx=ctx
    )
    assert result == {"operation": "is_prime", "result": True}


@pytest.mark.asyncio
async def test_number_theory_factor_integer(monkeypatch):
    session = StubSession("'2^2 * 3 * 5'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.number_theory_operation(
        "factor_integer", 60, ctx=ctx
    )
    assert result == {"operation": "factor_integer", "result": "2^2 * 3 * 5"}


@pytest.mark.asyncio
async def test_number_theory_gcd(monkeypatch):
    session = StubSession("6")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.number_theory_operation(
        "gcd", 12, b=18, ctx=ctx
    )
    assert result == {"operation": "gcd", "result": 6}


@pytest.mark.asyncio
async def test_number_theory_gcd_missing_b():
    ctx = FakeContext()
    with pytest.raises(ToolError, match="requires both"):
        await server.number_theory_operation("gcd", 12, ctx=ctx)


@pytest.mark.asyncio
async def test_number_theory_invalid_op():
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.number_theory_operation("bogus", 5, ctx=ctx)


@pytest.mark.asyncio
async def test_plot_expression(monkeypatch):
    session = StubSession("'aWdub3JlZA=='")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.plot_expression("sin(x)", ctx=ctx)
    assert result["format"] == "png"
    assert result["image_base64"] == "aWdub3JlZA=="


@pytest.mark.asyncio
async def test_evaluate_structured_forwards_timeout():
    session = StubSession("42")
    await server._evaluate_structured(session, "ignored", timeout_seconds=5.0)
    call = session.calls[-1]
    assert call["timeout_seconds"] == 5.0


# --- context guard tests (no ctx / no session_id) ---


@pytest.mark.asyncio
async def test_reset_sage_session_no_context():
    with pytest.raises(ToolError):
        await server.reset_sage_session(ctx=None)


@pytest.mark.asyncio
async def test_cancel_sage_session_no_context():
    with pytest.raises(ToolError):
        await server.cancel_sage_session(ctx=None)


@pytest.mark.asyncio
async def test_simplify_expression_no_context():
    with pytest.raises(ToolError):
        await server.simplify_expression("x", ctx=None)


@pytest.mark.asyncio
async def test_expand_expression_no_context():
    with pytest.raises(ToolError):
        await server.expand_expression("x", ctx=None)


@pytest.mark.asyncio
async def test_factor_expression_no_context():
    with pytest.raises(ToolError):
        await server.factor_expression("x", ctx=None)


@pytest.mark.asyncio
async def test_limit_expression_no_context():
    with pytest.raises(ToolError):
        await server.limit_expression("x", ctx=None)


@pytest.mark.asyncio
async def test_series_expansion_no_context():
    with pytest.raises(ToolError):
        await server.series_expansion("x", ctx=None)


@pytest.mark.asyncio
async def test_matrix_operation_no_context():
    with pytest.raises(ToolError):
        await server.matrix_operation([[1]], "rank", ctx=None)


@pytest.mark.asyncio
async def test_solve_ode_no_context():
    with pytest.raises(ToolError):
        await server.solve_ode("y' = 0", ctx=None)


@pytest.mark.asyncio
async def test_number_theory_operation_no_context():
    with pytest.raises(ToolError):
        await server.number_theory_operation("is_prime", 7, ctx=None)


@pytest.mark.asyncio
async def test_plot_expression_no_context():
    with pytest.raises(ToolError):
        await server.plot_expression("x", ctx=None)


@pytest.mark.asyncio
async def test_calculate_expression_no_context():
    with pytest.raises(ToolError):
        await server.calculate_expression("1+1", ctx=None)


@pytest.mark.asyncio
async def test_solve_equation_no_context():
    with pytest.raises(ToolError):
        await server.solve_equation("x=0", ctx=None)


@pytest.mark.asyncio
async def test_differentiate_expression_no_context():
    with pytest.raises(ToolError):
        await server.differentiate_expression("x", ctx=None)


@pytest.mark.asyncio
async def test_integrate_expression_no_context():
    with pytest.raises(ToolError):
        await server.integrate_expression("x", ctx=None)


@pytest.mark.asyncio
async def test_statistics_summary_no_context():
    with pytest.raises(ToolError):
        await server.statistics_summary([1, 2], ctx=None)


@pytest.mark.asyncio
async def test_matrix_multiply_no_context():
    with pytest.raises(ToolError):
        await server.matrix_multiply([[1]], [[1]], ctx=None)


# --- reset/cancel tool happy paths ---


@pytest.mark.asyncio
async def test_reset_sage_session(monkeypatch):
    reset_called = False

    async def fake_reset(session_id: str):
        nonlocal reset_called
        reset_called = True

    manager = SageSessionManager(server.DEFAULT_SETTINGS)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)
    monkeypatch.setattr(server.SESSION_MANAGER, "reset", fake_reset)

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
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)
    monkeypatch.setattr(server.SESSION_MANAGER, "cancel", fake_cancel)

    ctx = FakeContext("cancel-test")
    result = await server.cancel_sage_session(ctx=ctx)
    assert cancel_called
    assert result.message == "Session cancelled and restarted"


# --- session_resource coverage ---


@pytest.mark.asyncio
async def test_session_resource_all(monkeypatch):
    manager = SageSessionManager(server.DEFAULT_SETTINGS)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)

    def fake_snapshot():
        return [
            {
                "session_id": "s1",
                "live": True,
                "started_at": 1000.0,
                "last_used_at": 1001.0,
                "idle_seconds": 5.0,
            }
        ]

    monkeypatch.setattr(server.SESSION_MANAGER, "snapshot", fake_snapshot)
    raw = await server.session_resource("all", None)
    result = json.loads(raw)
    assert len(result) == 1
    assert result[0]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_session_resource_filtered(monkeypatch):
    manager = SageSessionManager(server.DEFAULT_SETTINGS)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)

    def fake_snapshot():
        return [
            {
                "session_id": "s1",
                "live": True,
                "started_at": 1000.0,
                "last_used_at": 1001.0,
                "idle_seconds": 5.0,
            },
            {
                "session_id": "s2",
                "live": False,
                "started_at": 1000.0,
                "last_used_at": 1001.0,
                "idle_seconds": 10.0,
            },
        ]

    monkeypatch.setattr(server.SESSION_MANAGER, "snapshot", fake_snapshot)
    raw = await server.session_resource("s2", None)
    result = json.loads(raw)
    assert len(result) == 1
    assert result[0]["session_id"] == "s2"


@pytest.mark.asyncio
async def test_evaluate_sage_no_context():
    """Cover line 160: evaluate_sage called without a context."""
    with pytest.raises(ToolError, match="MCP context"):
        await server.evaluate_sage("1+1", ctx=None)


@pytest.mark.asyncio
async def test_evaluate_sage_no_session_id():
    """Cover line 160: evaluate_sage with ctx but no session_id."""
    ctx = FakeContext()
    ctx.session_id = None
    with pytest.raises(ToolError, match="MCP context"):
        await server.evaluate_sage("1+1", ctx=ctx)


@pytest.mark.asyncio
async def test_evaluate_sage_security_violation_branch(monkeypatch):
    """Cover lines 185-189: SageEvaluationError with SecurityViolation type."""
    from sagemath_mcp.session import SageEvaluationError

    class FakeSession:
        async def evaluate(self, *args, **kwargs):
            raise SageEvaluationError(
                "Blocked",
                error_type="SecurityViolation",
                stdout="",
                traceback="traceback info",
            )

    async def fake_get(session_id: str):
        return FakeSession()

    monkeypatch.setattr(server, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(server.SESSION_MANAGER, "get", fake_get)

    ctx = FakeContext("sec-violation")
    with pytest.raises(ToolError):
        await server.evaluate_sage("import os", ctx=ctx)

    assert any("security policy" in msg.lower() for msg in ctx.error_messages)


@pytest.mark.asyncio
async def test_evaluate_sage_non_security_error_branch(monkeypatch):
    """Cover line 189: SageEvaluationError with non-security error type."""
    from sagemath_mcp.session import SageEvaluationError

    class FakeSession:
        async def evaluate(self, *args, **kwargs):
            raise SageEvaluationError(
                "NameError: x is not defined",
                error_type="NameError",
                stdout="",
                traceback="",
            )

    async def fake_get(session_id: str):
        return FakeSession()

    monkeypatch.setattr(server, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(server.SESSION_MANAGER, "get", fake_get)

    ctx = FakeContext("name-error")
    with pytest.raises(ToolError):
        await server.evaluate_sage("x + 1", ctx=ctx)

    assert any("SageMath error" in msg for msg in ctx.error_messages)


@pytest.mark.asyncio
async def test_evaluate_sage_process_error_with_cause(monkeypatch):
    """Cover lines 192-201: SageProcessError with a __cause__."""
    class FakeSession:
        async def evaluate(self, *args, **kwargs):
            try:
                raise OSError("broken pipe")
            except OSError:
                raise server.SageProcessError("worker died") from OSError("broken pipe")

    async def fake_get(session_id: str):
        return FakeSession()

    monkeypatch.setattr(server, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(server.SESSION_MANAGER, "get", fake_get)

    ctx = FakeContext("process-error-cause")
    with pytest.raises(ToolError):
        await server.evaluate_sage("1+1", ctx=ctx)

    assert any("unavailable" in msg.lower() for msg in ctx.error_messages)


# ---------------------------------------------------------------------------
# Phase 1 tools: symbolic_sum, combinatorics_operation, plot3d_expression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_symbolic_sum(monkeypatch):
    session = StubSession("'pi^2/6'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.symbolic_sum(
        expression="1/n^2", variable="n", lower="1", upper="oo", ctx=ctx,
    )
    assert result["operation"] == "sum"
    assert result["result"] is not None


@pytest.mark.asyncio
async def test_symbolic_product(monkeypatch):
    session = StubSession("'120'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.symbolic_sum(
        expression="k", variable="k", lower="1", upper="5",
        product=True, ctx=ctx,
    )
    assert result["operation"] == "product"


@pytest.mark.asyncio
async def test_symbolic_sum_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.symbolic_sum("1/n^2", ctx=None)


@pytest.mark.asyncio
async def test_combinatorics_binomial(monkeypatch):
    session = StubSession("252")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="binomial", n=10, k=5, ctx=ctx,
    )
    assert result["operation"] == "binomial"
    assert result["result"] == 252


@pytest.mark.asyncio
async def test_combinatorics_factorial(monkeypatch):
    session = StubSession("120")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="factorial", n=5, ctx=ctx,
    )
    assert result["result"] == 120


@pytest.mark.asyncio
async def test_combinatorics_catalan(monkeypatch):
    session = StubSession("42")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="catalan", n=5, ctx=ctx,
    )
    assert result["operation"] == "catalan"


@pytest.mark.asyncio
async def test_combinatorics_fibonacci(monkeypatch):
    session = StubSession("55")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="fibonacci", n=10, ctx=ctx,
    )
    assert result["result"] == 55


@pytest.mark.asyncio
async def test_combinatorics_bell(monkeypatch):
    session = StubSession("52")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="bell", n=5, ctx=ctx,
    )
    assert result["operation"] == "bell"


@pytest.mark.asyncio
async def test_combinatorics_partitions(monkeypatch):
    session = StubSession("7")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="partitions", n=5, ctx=ctx,
    )
    assert result["result"] == 7


@pytest.mark.asyncio
async def test_combinatorics_permutations(monkeypatch):
    session = StubSession("24")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="permutations", n=4, ctx=ctx,
    )
    assert result["result"] == 24


@pytest.mark.asyncio
async def test_combinatorics_permutations_with_k(monkeypatch):
    session = StubSession("60")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.combinatorics_operation(
        operation="permutations", n=5, k=3, ctx=ctx,
    )
    assert result["result"] == 60


@pytest.mark.asyncio
async def test_combinatorics_invalid_operation(monkeypatch):
    session = StubSession("0")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.combinatorics_operation(
            operation="invalid", n=5, ctx=ctx,
        )


@pytest.mark.asyncio
async def test_combinatorics_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.combinatorics_operation(
            operation="factorial", n=5, ctx=None,
        )


@pytest.mark.asyncio
async def test_plot3d_expression(monkeypatch):
    session = StubSession("'iVBORw0KGgo...'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.plot3d_expression(
        expression="x^2 + y^2", ctx=ctx,
    )
    assert result["format"] == "png"
    assert "image_base64" in result


@pytest.mark.asyncio
async def test_plot3d_expression_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.plot3d_expression("x + y", ctx=None)


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
async def test_find_root(monkeypatch):
    session = StubSession("0.7390851332151607")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.find_root(
        expression="x - cos(x)", lower_bound=0.0, upper_bound=1.0, ctx=ctx,
    )
    assert "root" in result


@pytest.mark.asyncio
async def test_find_root_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.find_root("x^2 - 2", ctx=None)


@pytest.mark.asyncio
async def test_plot_multi_expression(monkeypatch):
    session = StubSession("'iVBORw0KGgo...'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.plot_multi_expression(
        expressions=["sin(x)", "cos(x)"], ctx=ctx,
    )
    assert result["format"] == "png"
    assert "image_base64" in result


@pytest.mark.asyncio
async def test_plot_multi_expression_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.plot_multi_expression(
            expressions=["x", "x^2"], ctx=None,
        )


@pytest.mark.asyncio
async def test_vector_calculus_gradient(monkeypatch):
    session = StubSession("['2*x', '2*y', '2*z']")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.vector_calculus_operation(
        operation="gradient", expression="x^2 + y^2 + z^2", ctx=ctx,
    )
    assert result["operation"] == "gradient"
    assert isinstance(result["result"], list)


@pytest.mark.asyncio
async def test_vector_calculus_divergence(monkeypatch):
    session = StubSession("'3'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.vector_calculus_operation(
        operation="divergence", expression=["x", "y", "z"], ctx=ctx,
    )
    assert result["operation"] == "divergence"


@pytest.mark.asyncio
async def test_vector_calculus_curl(monkeypatch):
    session = StubSession("['0', '0', '0']")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.vector_calculus_operation(
        operation="curl", expression=["x", "y", "z"], ctx=ctx,
    )
    assert result["operation"] == "curl"


@pytest.mark.asyncio
async def test_vector_calculus_laplacian(monkeypatch):
    session = StubSession("'6'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.vector_calculus_operation(
        operation="laplacian", expression="x^2 + y^2 + z^2", ctx=ctx,
    )
    assert result["operation"] == "laplacian"


@pytest.mark.asyncio
async def test_vector_calculus_invalid_operation(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.vector_calculus_operation(
            operation="invalid", expression="x^2", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_vector_calculus_gradient_requires_string(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="scalar expression"):
        await server.vector_calculus_operation(
            operation="gradient", expression=["x", "y"], ctx=ctx,
        )


@pytest.mark.asyncio
async def test_vector_calculus_divergence_requires_list(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="vector field"):
        await server.vector_calculus_operation(
            operation="divergence", expression="x^2", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_vector_calculus_divergence_dimension_mismatch(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="components"):
        await server.vector_calculus_operation(
            operation="divergence",
            expression=["x", "y"],
            variables=["x", "y", "z"],
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_vector_calculus_curl_requires_3_components(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="exactly 3"):
        await server.vector_calculus_operation(
            operation="curl", expression=["x", "y"], ctx=ctx,
        )


@pytest.mark.asyncio
async def test_vector_calculus_laplacian_requires_string(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="scalar expression"):
        await server.vector_calculus_operation(
            operation="laplacian", expression=["x"], ctx=ctx,
        )


@pytest.mark.asyncio
async def test_vector_calculus_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.vector_calculus_operation(
            operation="gradient", expression="x^2", ctx=None,
        )


@pytest.mark.asyncio
async def test_vector_calculus_default_variables(monkeypatch):
    """Verify that variables defaults to ['x', 'y', 'z'] when None."""
    session = StubSession("['2*x', '2*y', '2*z']")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.vector_calculus_operation(
        operation="gradient", expression="x^2 + y^2 + z^2",
        variables=None, ctx=ctx,
    )
    assert result["operation"] == "gradient"


# ---------------------------------------------------------------------------
# Phase 4 — Niche domain tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_operation_chromatic(monkeypatch):
    session = StubSession("3")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.graph_operation(
        graph="PetersenGraph", operation="chromatic_number", ctx=ctx,
    )
    assert result["operation"] == "chromatic_number"
    assert result["result"] == 3


@pytest.mark.asyncio
async def test_graph_operation_is_connected(monkeypatch):
    session = StubSession("True")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.graph_operation(
        graph="{0:[1,2], 1:[0,2], 2:[0,1]}",
        operation="is_connected", ctx=ctx,
    )
    assert result["result"] is True


@pytest.mark.asyncio
async def test_graph_operation_shortest_path(monkeypatch):
    session = StubSession("[0, 1, 2]")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.graph_operation(
        graph="PetersenGraph", operation="shortest_path",
        source=0, target=2, ctx=ctx,
    )
    assert result["operation"] == "shortest_path"


@pytest.mark.asyncio
async def test_graph_operation_invalid(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.graph_operation(
            graph="PetersenGraph", operation="invalid", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_graph_operation_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.graph_operation(
            graph="PetersenGraph", operation="order", ctx=None,
        )


@pytest.mark.asyncio
async def test_group_operation_order(monkeypatch):
    session = StubSession("120")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.group_operation(
        group="SymmetricGroup(5)", operation="order", ctx=ctx,
    )
    assert result["result"] == 120


@pytest.mark.asyncio
async def test_group_operation_is_abelian(monkeypatch):
    session = StubSession("True")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.group_operation(
        group="CyclicPermutationGroup(6)",
        operation="is_abelian", ctx=ctx,
    )
    assert result["result"] is True


@pytest.mark.asyncio
async def test_group_operation_is_cyclic(monkeypatch):
    session = StubSession("False")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.group_operation(
        group="SymmetricGroup(4)", operation="is_cyclic", ctx=ctx,
    )
    assert result["operation"] == "is_cyclic"


@pytest.mark.asyncio
async def test_group_operation_invalid(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.group_operation(
            group="SymmetricGroup(3)", operation="invalid", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_group_operation_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.group_operation(
            group="SymmetricGroup(3)", operation="order", ctx=None,
        )


@pytest.mark.asyncio
async def test_elliptic_curve_rank(monkeypatch):
    session = StubSession("0")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.elliptic_curve_operation(
        coefficients=[0, 0, 1, -1, 0], operation="rank", ctx=ctx,
    )
    assert result["operation"] == "rank"


@pytest.mark.asyncio
async def test_elliptic_curve_discriminant(monkeypatch):
    session = StubSession("'-37'")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.elliptic_curve_operation(
        coefficients=[0, -1], operation="discriminant", ctx=ctx,
    )
    assert result["operation"] == "discriminant"


@pytest.mark.asyncio
async def test_elliptic_curve_invalid(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.elliptic_curve_operation(
            coefficients=[0, 1], operation="invalid", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_elliptic_curve_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.elliptic_curve_operation(
            coefficients=[0, 1], operation="rank", ctx=None,
        )


@pytest.mark.asyncio
async def test_coding_theory_length(monkeypatch):
    session = StubSession("7")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.coding_theory_operation(
        code_type="HammingCode(GF(2), 3)",
        operation="length", ctx=ctx,
    )
    assert result["result"] == 7


@pytest.mark.asyncio
async def test_coding_theory_minimum_distance(monkeypatch):
    session = StubSession("3")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.coding_theory_operation(
        code_type="HammingCode(GF(2), 3)",
        operation="minimum_distance", ctx=ctx,
    )
    assert result["operation"] == "minimum_distance"


@pytest.mark.asyncio
async def test_coding_theory_rate(monkeypatch):
    session = StubSession("0.5714285714285714")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    result = await server.coding_theory_operation(
        code_type="HammingCode(GF(2), 3)",
        operation="rate", ctx=ctx,
    )
    assert result["operation"] == "rate"


@pytest.mark.asyncio
async def test_coding_theory_invalid(monkeypatch):
    session = StubSession("None")
    await _stub_manager(monkeypatch, session)
    ctx = FakeContext()
    with pytest.raises(ToolError, match="Unknown operation"):
        await server.coding_theory_operation(
            code_type="HammingCode(GF(2), 3)",
            operation="invalid", ctx=ctx,
        )


@pytest.mark.asyncio
async def test_coding_theory_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.coding_theory_operation(
            code_type="HammingCode(GF(2), 3)",
            operation="length", ctx=None,
        )


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


# ---------------------------------------------------------------------------
# Streaming evaluate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_sage_streaming(monkeypatch):
    """Streaming tool emits stdout lines as progress events."""
    fake_result = WorkerResult(
        result_type="expression",
        result="6",
        latex=None,
        stdout="line1\nline2\nline3",
        elapsed_ms=1.0,
    )

    class FakeSession:
        async def evaluate(self, *args, **kwargs):
            return fake_result

    async def fake_get(session_id):
        return FakeSession()

    monkeypatch.setattr(server, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(server.SESSION_MANAGER, "get", fake_get)

    ctx = FakeContext("streaming")
    result = await server.evaluate_sage_streaming("for i in range(3): print(i)", ctx=ctx)
    assert result.result == "6"
    # Each stdout line should have been emitted as progress
    assert len(ctx.progress_events) == 3


@pytest.mark.asyncio
async def test_evaluate_sage_streaming_no_context():
    with pytest.raises(ToolError, match="MCP context"):
        await server.evaluate_sage_streaming("1+1", ctx=None)


@pytest.mark.asyncio
async def test_evaluate_sage_streaming_empty_stdout(monkeypatch):
    """No progress events when stdout is empty."""
    fake_result = WorkerResult(
        result_type="expression",
        result="42",
        latex=None,
        stdout="",
        elapsed_ms=0.5,
    )

    class FakeSession:
        async def evaluate(self, *args, **kwargs):
            return fake_result

    async def fake_get(session_id):
        return FakeSession()

    monkeypatch.setattr(server, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(server.SESSION_MANAGER, "get", fake_get)

    ctx = FakeContext("stream-empty")
    result = await server.evaluate_sage_streaming("42", ctx=ctx)
    assert result.result == "42"
    assert len(ctx.progress_events) == 0


# ---------------------------------------------------------------------------
# Sage integration (requires real Sage)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which("sage") is None, reason="Sage executable not available"
)
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
        result = await server.calculate_expression("factorial(5)", ctx=ctx)
        assert result["numeric"] == 120.0
    finally:
        await session.shutdown()
