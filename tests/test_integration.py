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
        success = await server.evaluate_sage.fn("factorial(6)", ctx=ctx)
        assert success.result == "720"

        with pytest.raises(server.ToolError):
            await server.evaluate_sage.fn("import os", ctx=ctx)

        raw = await server.monitoring_resource.fn("metrics", None)
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
            await server.evaluate_sage.fn(
                "import time; time.sleep(10)", ctx=ctx
            )

        raw = await server.monitoring_resource.fn("metrics", None)
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
        result = await server.evaluate_sage.fn("1 + 1", ctx=ctx)
        assert result.result == "2"

        # Cancel the session and verify monitoring
        await server.cancel_sage_session.fn(ctx=ctx)

        raw = await server.monitoring_resource.fn("metrics", None)
        assert raw
        snapshot = json.loads(raw)
        assert snapshot["successes"] >= 1
    finally:
        await manager.shutdown()
