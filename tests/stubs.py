"""Stand-ins for a Sage session, shared by the tool test modules."""



from sagemath_mcp import runtime, server
from sagemath_mcp.manager import SageSessionManager
from sagemath_mcp.session import WorkerResult


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
        trusted: bool = False,
        on_stdout=None,
    ):
        self.calls.append(
            {
                "code": code,
                "want_latex": want_latex,
                "capture_stdout": capture_stdout,
                "timeout_seconds": timeout_seconds,
            }
        )
        if on_stdout is not None:
            for line in (self.stdout or "").splitlines():
                await on_stdout(line)
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

    monkeypatch.setattr(runtime, "SESSION_MANAGER", manager)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "get", fake_get)
    monkeypatch.setattr(runtime.SESSION_MANAGER, "cancel", fake_cancel)
    return manager
