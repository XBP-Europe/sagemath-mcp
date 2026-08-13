import asyncio
import json
import shutil

import pytest

from sagemath_mcp import server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.monitoring import reset_metrics
from sagemath_mcp.session import SageEvaluationError, SageSession, SageSessionManager

from .conftest import FakeContext

requires_sage = pytest.mark.skipif(
    shutil.which("sage") is None, reason="Sage executable not available"
)


@pytest.fixture(autouse=True)
def unset_pure_python(monkeypatch):
    monkeypatch.delenv("SAGEMATH_MCP_PURE_PYTHON", raising=False)


@requires_sage
@pytest.mark.asyncio
async def test_real_sage_session_evaluates_expression():
    settings = SageSettings(force_python_worker=False)
    session = SageSession("integration-session", settings)
    try:
        result = await session.evaluate("factorial(5)", want_latex=False, capture_stdout=False)
        assert result.result == "120"
    finally:
        await session.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_security_violation_keeps_session_alive():
    settings = SageSettings(force_python_worker=False)
    session = SageSession("integration-security", settings)
    try:
        with pytest.raises(SageEvaluationError) as excinfo:
            await session.evaluate(
                "import os\nos.system('echo blocked')",
                want_latex=False,
                capture_stdout=False,
            )
        assert excinfo.value.error_type == "SecurityViolation"

        # Session should still respond to subsequent evaluations.
        follow_up = await session.evaluate("2 + 2", want_latex=False, capture_stdout=False)
        assert follow_up.result == "4"
    finally:
        await session.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_server_monitoring_resource_with_real_sage(monkeypatch):
    settings = SageSettings(force_python_worker=False)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)
    reset_metrics()
    ctx = FakeContext("integration-monitoring")

    try:
        success = await server.evaluate_sage("factorial(6)", ctx=ctx)
        assert success.result == "720"

        with pytest.raises(server.ToolError):
            await server.evaluate_sage("import os", ctx=ctx)

        raw = await server.monitoring_resource("metrics", None)
        assert raw
        snapshot = json.loads(raw)
        assert snapshot["successes"] >= 1
        assert snapshot["failures"] >= 1
        assert snapshot["security_failures"] >= 1
    finally:
        await manager.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_monitoring_metrics_on_timeout(monkeypatch):
    """Validate monitoring metrics capture timeout from a real Sage session."""
    settings = SageSettings(force_python_worker=False, eval_timeout=1.0)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)
    reset_metrics()
    ctx = FakeContext("integration-timeout")

    try:
        # Run a computation that exceeds the 1s timeout
        with pytest.raises(server.ToolError):
            await server.evaluate_sage(
                "import time; time.sleep(10)", ctx=ctx
            )

        raw = await server.monitoring_resource("metrics", None)
        assert raw
        snapshot = json.loads(raw)
        assert snapshot["failures"] >= 1
        assert snapshot["last_error"] is not None
    finally:
        await manager.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_monitoring_metrics_on_cancellation(monkeypatch):
    """Validate monitoring metrics capture cancellation from a real Sage session."""

    settings = SageSettings(force_python_worker=False)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)
    reset_metrics()
    ctx = FakeContext("integration-cancel")

    try:
        # First do a successful eval to establish the session
        result = await server.evaluate_sage("1 + 1", ctx=ctx)
        assert result.result == "2"

        # Cancel the session and verify monitoring
        await server.cancel_sage_session(ctx=ctx)

        raw = await server.monitoring_resource("metrics", None)
        assert raw
        snapshot = json.loads(raw)
        assert snapshot["successes"] >= 1
    finally:
        await manager.shutdown()


@requires_sage
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("equation", "function", "variable", "expected"),
    [
        # The documented form from the tool's own docstring. This is the exact
        # call reported in issue #12.
        ("diff(y(x), x) + y(x) = cos(x)", "y", "x", ("_C", "cos(x)", "sin(x)")),
        # The bare form, which worked before the fix and must keep working:
        # the fix must not simply trade one broken spelling for another.
        ("diff(y, x) + y = cos(x)", "y", "x", ("_C", "cos(x)", "sin(x)")),
        # Second order, both spellings.
        ("diff(y(x), x, 2) + y(x) = 0", "y", "x", ("_K1", "_K2")),
        ("diff(y, x, 2) + y = 0", "y", "x", ("_K1", "_K2")),
        # "==" takes the non-split branch through the generated code.
        ("diff(y(x), x) == y(x)", "y", "x", ("_C", "e^x")),
        # The applied/bare handling must not assume the names y and x.
        ("diff(f(t), t) = f(t)", "f", "t", ("_C", "e^t")),
        ("diff(y(x), x) = x*y(x)", "y", "x", ("_C", "e^")),
    ],
)
async def test_solve_ode_equation_forms(monkeypatch, equation, function, variable, expected):
    """Regression test for #12: solve_ode rejected the documented "y(x)" form.

    The generated Sage code bound the dependent name to the *applied*
    expression y(x), so "y(x)" in the user's equation became "(y(x))(x)" and
    Sage raised "Substitution using function-call syntax and unnamed arguments
    has been removed". Every spelling below must now solve.
    """

    settings = SageSettings(force_python_worker=False)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)
    ctx = FakeContext("integration-ode-forms")

    try:
        result = await server.solve_ode(
            equation, function=function, variable=variable, ctx=ctx
        )
        solution = str(result["solution"])

        # The exact failure reported in #12 must not resurface.
        assert "Substitution using function-call syntax" not in solution
        for fragment in expected:
            assert fragment in solution, f"{fragment!r} missing from {solution!r}"
    finally:
        await manager.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_solve_ode_applied_and_bare_agree(monkeypatch):
    """#12: the two spellings describe one ODE, so they must solve identically."""

    settings = SageSettings(force_python_worker=False)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)
    ctx = FakeContext("integration-ode-agree")

    try:
        applied = await server.solve_ode(
            "diff(y(x), x) + y(x) = cos(x)", function="y", variable="x", ctx=ctx
        )
        bare = await server.solve_ode(
            "diff(y, x) + y = cos(x)", function="y", variable="x", ctx=ctx
        )
        assert str(applied["solution"]) == str(bare["solution"])
    finally:
        await manager.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_large_result_exceeds_asyncio_default_stream_limit():
    """A result larger than asyncio's 64 KiB default must survive the round trip.

    One JSON response is read with a single readline(), so the whole payload
    has to fit in the subprocess stream buffer. With asyncio's default limit
    this raised LimitOverrunError, which is what broke plot3d_expression: its
    base64 PNG is around 100 KiB.
    """

    settings = SageSettings(force_python_worker=False)
    session = SageSession("integration-large-result", settings)
    try:
        # Comfortably past the 64 KiB default.
        result = await session.evaluate(
            "'x' * 200000", want_latex=False, capture_stdout=False
        )
        assert result.result is not None
        assert len(result.result) >= 200000
    finally:
        await session.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_interrupt_preserves_state_with_real_sage(monkeypatch):
    """Interrupt against a real Sage worker, not the pure-Python shim.

    Sage installs its own signal handling during startup, so the pure-Python
    worker passing this is not evidence that Sage does.
    """
    settings = SageSettings(force_python_worker=False, eval_timeout=120.0)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)
    ctx = FakeContext("integration-interrupt")

    try:
        await server.evaluate_sage("treasure = factorial(20)", ctx=ctx)

        async def long_running():
            with pytest.raises(server.ToolError):
                await server.evaluate_sage("sum(k for k in range(10**9))", ctx=ctx)

        task = asyncio.create_task(long_running())
        await asyncio.sleep(1.5)
        result = await server.interrupt_sage_session(ctx=ctx)
        assert "state preserved" in result.message
        await task

        # The namespace must have survived the interrupt.
        kept = await server.evaluate_sage("treasure", ctx=ctx)
        assert kept.result == str(factorial_20())
    finally:
        await manager.shutdown()


def factorial_20() -> int:
    result = 1
    for value in range(2, 21):
        result *= value
    return result


@requires_sage
@pytest.mark.asyncio
async def test_named_sessions_isolated_with_real_sage(monkeypatch):
    settings = SageSettings(force_python_worker=False, eval_timeout=120.0)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)
    ctx = FakeContext("integration-named")

    try:
        await server.evaluate_sage("E = EllipticCurve([0,-1])", session="curves", ctx=ctx)
        await server.evaluate_sage("G = graphs.PetersenGraph()", session="graphs", ctx=ctx)

        rank = await server.evaluate_sage("E.rank()", session="curves", ctx=ctx)
        assert rank.result == "0"
        order = await server.evaluate_sage("G.order()", session="graphs", ctx=ctx)
        assert order.result == "10"

        # Each workspace sees only its own definitions.
        with pytest.raises(server.ToolError):
            await server.evaluate_sage("E.rank()", session="graphs", ctx=ctx)

        listed = await server.list_sage_sessions(ctx=ctx)
        assert {entry["name"] for entry in listed["sessions"]} == {"curves", "graphs"}
    finally:
        await manager.shutdown()
