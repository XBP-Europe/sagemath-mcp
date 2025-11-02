import shutil

import pytest

from sagemath_mcp import server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.monitoring import reset_metrics
from sagemath_mcp.session import SageEvaluationError, SageSession, SageSessionManager

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


class _IntegrationContext:
    def __init__(self, session_id: str):
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


@requires_sage
@pytest.mark.asyncio
async def test_server_monitoring_resource_with_real_sage(monkeypatch):
    settings = SageSettings(force_python_worker=False)
    manager = SageSessionManager(settings)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)
    reset_metrics()
    ctx = _IntegrationContext("integration-monitoring")

    try:
        success = await server.evaluate_sage.fn("factorial(6)", ctx=ctx)
        assert success.result == "720"

        with pytest.raises(server.ToolError):
            await server.evaluate_sage.fn("import os", ctx=ctx)

        metrics = await server.monitoring_resource.fn("metrics", None)
        assert metrics
        snapshot = metrics[0]
        assert snapshot.successes >= 1
        assert snapshot.failures >= 1
        assert snapshot.security_failures >= 1
    finally:
        await manager.shutdown()
