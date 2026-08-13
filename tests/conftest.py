"""Shared test fixtures for the sagemath-mcp test suite."""

import pytest_asyncio


class FakeContext:
    """Stub MCP context that records messages and progress events."""

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


@pytest_asyncio.fixture
async def sage_manager(monkeypatch):
    """A pure-Python session manager wired into the runtime for one test.

    New tests should take this rather than patching module state by hand. The
    existing sites were retargeted to ``runtime.SESSION_MANAGER`` instead of
    being converted to this fixture: several depend on their own settings
    (eval_timeout, persist_dir, force_python_worker), and one shared fixture
    would have flattened those differences into an untested default.
    """
    from sagemath_mcp import runtime
    from sagemath_mcp.config import SageSettings
    from sagemath_mcp.session import SageSessionManager

    manager = SageSessionManager(SageSettings(force_python_worker=True))
    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    try:
        yield manager
    finally:
        await manager.shutdown()
