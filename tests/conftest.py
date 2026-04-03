"""Shared test fixtures for the sagemath-mcp test suite."""


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
