"""Unit tests for evaluate_sage and the core expression tools (src/sagemath_mcp/tools/core.py).

Moved out of tests/test_server.py in the 2026-09 refactor, unchanged.
"""

import asyncio
import contextlib
import shutil

import pytest
from fastmcp.exceptions import ToolError

from sagemath_mcp import runtime, server
from sagemath_mcp.errors import SageEvaluationError, SageProcessError
from sagemath_mcp.manager import SageSessionManager
from sagemath_mcp.models import EvaluateResult
from sagemath_mcp.session import WorkerResult

from ..conftest import FakeContext
from ..stubs import StubSession, _stub_manager


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

    monkeypatch.setattr(runtime, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))

    async def fake_get(session_id: str) -> FakeSession:
        return FakeSession()

    async def fake_cancel(session_id: str) -> None:
        raise AssertionError("cancel should not be called")

    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fake_get)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "cancel", fake_cancel)

    ctx = FakeContext()
    payload: EvaluateResult = await server.evaluate_sage("x = 6", ctx=ctx)

    assert payload.result == "42"
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

    monkeypatch.setattr(runtime, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))

    async def fake_get(session_id: str) -> FakeSession:
        return FakeSession()

    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fake_get)

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

    monkeypatch.setattr(runtime, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fake_get)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "cancel", fake_cancel)

    ctx = FakeContext()
    with pytest.raises(asyncio.CancelledError):
        await server.evaluate_sage("long_calculation()", ctx=ctx)

    assert fake_session.cancelled is True


@pytest.mark.asyncio
async def test_evaluate_sage_process_error(monkeypatch):
    class FakeSession:
        async def evaluate(self, *args, **kwargs):
            raise server.SageProcessError("boom")

    async def fake_get(session_id: str) -> FakeSession:
        return FakeSession()

    async def fake_cancel(session_id: str) -> None:
        pass

    monkeypatch.setattr(runtime, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fake_get)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "cancel", fake_cancel)

    ctx = FakeContext()
    with pytest.raises(server.ToolError):
        await server.evaluate_sage("f()", ctx=ctx)


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

    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fake_get)

    ctx = FakeContext("violation")
    with pytest.raises(ToolError):
        await server.evaluate_sage("import os", ctx=ctx)


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

    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)

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

    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)

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
async def test_calculate_expression_no_context():
    with pytest.raises(ToolError):
        await server.calculate_expression("1+1", ctx=None)


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
    from sagemath_mcp.errors import SageEvaluationError

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

    monkeypatch.setattr(runtime, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fake_get)

    ctx = FakeContext("sec-violation")
    with pytest.raises(ToolError):
        await server.evaluate_sage("import os", ctx=ctx)


@pytest.mark.asyncio
async def test_evaluate_sage_non_security_error_branch(monkeypatch):
    """Cover line 189: SageEvaluationError with non-security error type."""
    from sagemath_mcp.errors import SageEvaluationError

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

    monkeypatch.setattr(runtime, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fake_get)

    ctx = FakeContext("name-error")
    with pytest.raises(ToolError):
        await server.evaluate_sage("x + 1", ctx=ctx)


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

    monkeypatch.setattr(runtime, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fake_get)

    ctx = FakeContext("process-error-cause")
    with pytest.raises(ToolError):
        await server.evaluate_sage("1+1", ctx=ctx)


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
        async def evaluate(self, *args, on_stdout=None, **kwargs):
            # The real worker emits each line while the computation runs; the
            # tool no longer splits accumulated stdout afterwards.
            if on_stdout is not None:
                for line in fake_result.stdout.splitlines():
                    await on_stdout(line)
            return fake_result

    async def fake_get(session_id):
        return FakeSession()

    monkeypatch.setattr(runtime, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fake_get)

    ctx = FakeContext("streaming")
    result = await server.evaluate_sage_streaming("for i in range(3): print(i)", ctx=ctx)
    assert result.result == "6"
    # Each stdout line should have been emitted as progress, as it arrived.
    assert len(ctx.progress_events) == 3
    assert [event[2] for event in ctx.progress_events] == ["line1", "line2", "line3"]


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
        async def evaluate(self, *args, on_stdout=None, **kwargs):
            # The real worker emits each line while the computation runs; the
            # tool no longer splits accumulated stdout afterwards.
            if on_stdout is not None:
                for line in fake_result.stdout.splitlines():
                    await on_stdout(line)
            return fake_result

    async def fake_get(session_id):
        return FakeSession()

    monkeypatch.setattr(runtime, "SESSION_MANAGER", SageSessionManager(server.DEFAULT_SETTINGS))
    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fake_get)

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
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fake_get)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "cancel", fake_cancel)

    ctx = FakeContext("sage-integration")
    try:
        result = await server.calculate_expression("factorial(5)", ctx=ctx)
        assert result["numeric"] == 120.0
    finally:
        await session.shutdown()


@pytest.mark.asyncio
async def test_sage_manager_fixture_reaches_a_specialized_tool(sage_manager):
    """The fixture must actually be what the tools use.

    Patching the wrong module is silent: the tool runs against the real manager
    and the test still passes. Asserting through a *specialized* tool (not
    evaluate_sage) proves the swap reaches the whole tool surface.
    """
    # A specialized tool, not evaluate_sage: they resolve their session on a
    # different path, and that path is the one worth pinning. Their generated
    # prelude imports sage.all, so the evaluation itself cannot succeed without
    # a Sage runtime -- but routing happens first, and routing is the claim.
    # Whatever the evaluation raises without Sage is irrelevant here.
    with contextlib.suppress(Exception):
        await server.calculate_expression(
            "6 * 7", session="fx", ctx=FakeContext("fixture-client")
        )

    workspaces = [entry["session_id"] for entry in sage_manager.snapshot()]
    assert any("fx" in name for name in workspaces), (
        "the specialized tool resolved its session somewhere other than the "
        f"fixture's manager; it holds {workspaces}"
    )


@pytest.mark.asyncio
async def test_a_timeout_is_reported_as_a_tool_error_and_recorded(sage_manager, monkeypatch):
    """A timeout must reach the caller as a tool error, and be counted.

    It used to propagate as a bare TimeoutError: no monitoring record, and an
    unstructured error at the client. The test meant to cover this used
    `import time; time.sleep(10)`, which became a SecurityViolation once callers
    lost imports -- also a ToolError, so it kept passing while testing nothing.
    """
    from sagemath_mcp import monitoring
    from sagemath_mcp.session import SageSession

    async def always_times_out(self, *args, **kwargs):
        raise TimeoutError("Sage evaluation timed out after 1.00s")

    monkeypatch.setattr(SageSession, "evaluate", always_times_out)
    monitoring.reset_metrics()

    with pytest.raises(ToolError, match="timed out"):
        await server.evaluate_sage("1 + 1", ctx=FakeContext("timeout-client"))

    snapshot = monitoring.snapshot()
    assert snapshot["failures"] >= 1
    assert "timed out" in str(snapshot["last_error"])


@pytest.mark.asyncio
async def test_specialized_tools_report_a_timeout_the_same_way(sage_manager, monkeypatch):
    from sagemath_mcp.session import SageSession

    async def always_times_out(self, *args, **kwargs):
        raise TimeoutError("Sage evaluation timed out after 1.00s")

    monkeypatch.setattr(SageSession, "evaluate", always_times_out)
    with pytest.raises(ToolError, match="timed out"):
        await server.calculate_expression("1 + 1", ctx=FakeContext("timeout-client"))


@pytest.mark.parametrize(
    "raised,expected",
    [
        (TimeoutError("Sage evaluation timed out after 1.00s"), "timed out"),
        (
            SageEvaluationError(
                "boom", error_type="SecurityViolation", stdout="", traceback=""
            ),
            "boom",
        ),
        (SageProcessError("worker gone"), "worker gone"),
    ],
    ids=["timeout", "evaluation-error", "dead-worker"],
)
@pytest.mark.asyncio
async def test_streaming_reports_failures_like_evaluate_sage(
    raised, expected, sage_manager, monkeypatch
):
    """Streaming had no exception handling at all.

    A timeout, a security violation or a dead worker propagated raw from this
    tool while evaluate_sage reported each properly, and monitoring recorded
    none of them.
    """
    from sagemath_mcp import monitoring
    from sagemath_mcp.session import SageSession

    async def failing(self, *args, **kwargs):
        raise raised

    monkeypatch.setattr(SageSession, "evaluate", failing)
    monitoring.reset_metrics()

    with pytest.raises(ToolError, match=expected):
        await server.evaluate_sage_streaming("1 + 1", ctx=FakeContext("stream-fail"))

    assert monitoring.snapshot()["failures"] >= 1
