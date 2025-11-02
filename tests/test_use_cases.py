import shutil

import pytest

from sagemath_mcp import server
from sagemath_mcp.config import SageSettings
from sagemath_mcp.models import EvaluateResult
from sagemath_mcp.session import SageSessionManager


class FakeContext:
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


requires_sage = pytest.mark.skipif(
    shutil.which("sage") is None, reason="Sage executable not available"
)


@requires_sage
@pytest.mark.asyncio
async def test_use_cases_cover_manual_examples(monkeypatch):
    original_manager = server.SESSION_MANAGER
    settings = SageSettings()
    manager = SageSessionManager(settings)
    monkeypatch.setattr(server, "SESSION_MANAGER", manager)

    ctx = FakeContext("manual-use-cases")

    try:
        # Calculus: differentiation + integration
        deriv: EvaluateResult = await server.evaluate_sage.fn(
            "var('x'); f = cos(x)**2; diff(f, x)",
            ctx=ctx,
        )
        assert "sin(x)" in deriv.result

        integral: EvaluateResult = await server.evaluate_sage.fn(
            "integral(diff(cos(x)**2, x), x)",
            ctx=ctx,
        )
        assert "cos(x)^2" in integral.result

        # Rings and factorisation
        factor = await server.evaluate_sage.fn(
            "var('x'); factor(x**3 - 2*x**2 - x + 2)",
            ctx=ctx,
        )
        assert {"(x - 2)", "(x - 1)", "(x + 1)"}.issubset(set(factor.result.split("*")))

        # Matrix algebra
        matrix_inverse = await server.evaluate_sage.fn(
            "A = matrix(QQ,[[1,2],[3,5]]); A.inverse()",
            ctx=ctx,
        )
        assert "[ 3 -1]" in (matrix_inverse.result or "")

        product = await server.matrix_multiply.fn([[1, 2], [3, 4]], [[5, 6], [7, 8]], ctx=ctx)
        assert product["product"][0][0] == 19.0

        # Series / sums
        series_sum = await server.evaluate_sage.fn(
            "sum(n**2 for n in range(1, 11))",
            ctx=ctx,
        )
        assert series_sum.result == "385"

        # Statistics helper tool (pure Python)
        stats = await server.statistics_summary.fn([1, 2, 3, 4, 5], ctx=ctx)
        assert stats["mean"] == pytest.approx(3.0)

        # Solve equation tool (linked to sage_eval)
        solutions = await server.solve_equation.fn("x^2 - 4 = 0", ctx=ctx)
        assert "x == 2" in solutions["solutions"]

        # Ensure progress events were recorded
        assert ctx.progress_events
    finally:
        await manager.shutdown()
        server.SESSION_MANAGER = original_manager
