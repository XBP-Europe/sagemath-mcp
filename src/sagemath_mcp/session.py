"""Async management of SageMath worker processes."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_SETTINGS, SageSettings

LOGGER = logging.getLogger(__name__)


class SageProcessError(RuntimeError):
    """Raised when the underlying Sage process terminates unexpectedly."""


class SageEvaluationError(RuntimeError):
    """Raised when Sage returns an execution error."""

    def __init__(self, message: str, *, error_type: str, stdout: str, traceback: str):
        super().__init__(message)
        self.error_type = error_type
        self.stdout = stdout
        self.traceback = traceback


@dataclass(slots=True)
class WorkerResult:
    result_type: str
    result: str | None
    latex: str | None
    stdout: str
    elapsed_ms: float


class SageSession:
    """Encapsulates a single long-lived Sage worker."""

    def __init__(self, session_id: str, settings: SageSettings | None = None):
        self.session_id = session_id
        self.settings = settings or DEFAULT_SETTINGS
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.started_at = time.time()
        self.last_used_at = self.started_at

    async def ensure_started(self) -> None:
        if self._process and self._process.returncode is None:
            return
        await self._launch_worker()

    async def _launch_worker(self) -> None:
        sage_binary = self.settings.sage_binary
        if self.settings.force_python_worker:
            python_exe = sys.executable or shutil.which("python3") or shutil.which("python")
            if not python_exe:
                raise SageProcessError("Unable to locate a Python interpreter for the worker.")
            command = [python_exe, "-m", "sagemath_mcp._sage_worker"]
        else:
            if not shutil.which(sage_binary):
                raise SageProcessError(
                    f"Unable to locate Sage executable '{sage_binary}'. "
                    "Adjust SAGEMATH_MCP_SAGE_BINARY or install SageMath."
                )
            command = [sage_binary, "-python", "-m", "sagemath_mcp._sage_worker"]
        env = os.environ.copy()
        project_root = Path(__file__).resolve().parents[1]
        pythonpath_entries: list[str] = []
        if (sage_venv := env.get("SAGE_VENV")):
            py_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
            site_packages = Path(sage_venv) / "lib" / py_version / "site-packages"
            pythonpath_entries.append(str(site_packages))
        pythonpath_entries.append(str(project_root))
        if (existing_pythonpath := env.get("PYTHONPATH")):
            pythonpath_entries.append(existing_pythonpath)
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
        env.setdefault("SAGEMATH_MCP_STARTUP", self.settings.startup_code)
        if self.settings.force_python_worker:
            env.setdefault("SAGEMATH_MCP_PURE_PYTHON", "1")
        LOGGER.debug("Launching Sage worker %s with command %s", self.session_id, command)
        self._process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._stderr_task = asyncio.create_task(self._consume_stderr())
        self.started_at = time.time()
        self.last_used_at = self.started_at
        LOGGER.info("Started Sage session %s (pid=%s)", self.session_id, self._process.pid)

    async def _consume_stderr(self) -> None:
        assert self._process and self._process.stderr
        while True:
            line = await self._process.stderr.readline()
            if not line:
                break
            LOGGER.warning("sage[%s] stderr: %s", self.session_id, line.decode().rstrip())

    async def evaluate(
        self,
        code: str,
        *,
        want_latex: bool,
        capture_stdout: bool,
        timeout_seconds: float | None = None,
    ) -> WorkerResult:
        await self.ensure_started()
        assert self._process and self._process.stdin and self._process.stdout
        payload = {
            "id": str(uuid.uuid4()),
            "type": "execute",
            "code": code,
            "want_latex": want_latex,
            "capture_stdout": capture_stdout,
        }
        data = json.dumps(payload).encode("utf-8") + b"\n"
        effective_timeout = timeout_seconds or self.settings.eval_timeout
        async with self._lock:
            self._process.stdin.write(data)
            await self._process.stdin.drain()
            try:
                raw = await asyncio.wait_for(
                    self._process.stdout.readline(), timeout=effective_timeout
                )
            except TimeoutError as exc:
                await self._handle_timeout()
                raise TimeoutError(
                    f"Sage evaluation timed out after {effective_timeout:.2f}s"
                ) from exc
            if not raw:
                raise SageProcessError("Sage worker terminated unexpectedly.")
        response = json.loads(raw.decode("utf-8"))
        self.last_used_at = time.time()
        if not response.get("ok", False):
            error = response.get("error", {})
            raise SageEvaluationError(
                error.get("message", "Unknown Sage error"),
                error_type=error.get("type", "Exception"),
                stdout=response.get("stdout", ""),
                traceback=error.get("traceback", ""),
            )
        return WorkerResult(
            result_type=response["result_type"],
            result=response.get("result"),
            latex=response.get("latex"),
            stdout=response.get("stdout", ""),
            elapsed_ms=float(response.get("elapsed_ms", 0.0)),
        )

    async def reset(self) -> None:
        await self.ensure_started()
        assert self._process and self._process.stdin and self._process.stdout
        payload = {"id": str(uuid.uuid4()), "type": "reset"}
        data = json.dumps(payload).encode("utf-8") + b"\n"
        async with self._lock:
            self._process.stdin.write(data)
            await self._process.stdin.drain()
            raw = await self._process.stdout.readline()
            if not raw:
                raise SageProcessError("Sage worker terminated during reset.")
        response = json.loads(raw.decode("utf-8"))
        if not response.get("ok", False):
            raise SageProcessError("Failed to reset Sage session.")
        self.last_used_at = time.time()

    async def cancel(self) -> None:
        """Restart the worker to cooperatively cancel any in-flight computation."""
        LOGGER.info("Cancelling Sage session %s", self.session_id)
        await self._restart_worker()
        self.last_used_at = time.time()

    async def shutdown(self) -> None:
        if not self._process or self._process.returncode is not None:
            return
        assert self._process.stdin
        payload = {"id": str(uuid.uuid4()), "type": "shutdown"}
        self._process.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
        await self._process.stdin.drain()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=self.settings.shutdown_grace)
        except TimeoutError:
            self._process.kill()
        self._process.stdin.close()
        with contextlib.suppress(Exception):
            await self._process.stdin.wait_closed()
        if self._stderr_task:
            self._stderr_task.cancel()

    def is_alive(self) -> bool:
        return bool(self._process and self._process.returncode is None)

    def should_cull(self, now: float | None = None) -> bool:
        now = now or time.time()
        return (now - self.last_used_at) > self.settings.idle_ttl

    async def _handle_timeout(self) -> None:
        LOGGER.error("Timeout in Sage session %s - restarting worker", self.session_id)
        await self._restart_worker()

    async def _restart_worker(self) -> None:
        await self._terminate_worker()
        await self._launch_worker()

    async def _terminate_worker(self) -> None:
        if self._stderr_task:
            self._stderr_task.cancel()
            self._stderr_task = None
        if self._process:
            if self._process.stdin:
                self._process.stdin.close()
                with contextlib.suppress(Exception):
                    await self._process.stdin.wait_closed()
            if self._process.returncode is None:
                self._process.kill()
                await self._process.wait()
        self._process = None


class SageSessionManager:
    """Track Sage sessions keyed by MCP session id."""

    def __init__(self, settings: SageSettings | None = None):
        self.settings = settings or DEFAULT_SETTINGS
        self._sessions: dict[str, SageSession] = {}
        self._lock = asyncio.Lock()

    async def get(self, session_id: str) -> SageSession:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = SageSession(session_id, self.settings)
                self._sessions[session_id] = session
        await session.ensure_started()
        return session

    async def reset(self, session_id: str) -> None:
        session = await self.get(session_id)
        await session.reset()

    async def cancel(self, session_id: str) -> None:
        session = await self.get(session_id)
        await session.cancel()

    async def cull_idle(self) -> None:
        now = time.time()
        async with self._lock:
            stale = [sid for sid, sess in self._sessions.items() if sess.should_cull(now)]
        sessions_to_shutdown: list[tuple[str, SageSession]] = []
        for sid in stale:
            session = self._sessions.pop(sid, None)
            if session:
                sessions_to_shutdown.append((sid, session))
        if not sessions_to_shutdown:
            return
        LOGGER.info("Culling %d idle Sage session(s)", len(sessions_to_shutdown))
        results = await asyncio.gather(
            *(session.shutdown() for _, session in sessions_to_shutdown),
            return_exceptions=True,
        )
        for (sid, _), result in zip(sessions_to_shutdown, results, strict=False):
            if isinstance(result, Exception):
                LOGGER.warning("Failed to shut down session %s cleanly: %s", sid, result)

    async def shutdown(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        if not sessions:
            return
        results = await asyncio.gather(
            *(session.shutdown() for session in sessions),
            return_exceptions=True,
        )
        for session, result in zip(sessions, results, strict=False):
            if isinstance(result, Exception):
                LOGGER.warning(
                    "Failed to shut down session %s cleanly: %s", session.session_id, result
                )

    def snapshot(self) -> list[dict[str, float | str | bool]]:
        now = time.time()
        return [
            {
                "session_id": sid,
                "live": sess.is_alive(),
                "started_at": sess.started_at,
                "last_used_at": sess.last_used_at,
                "idle_seconds": now - sess.last_used_at,
            }
            for sid, sess in self._sessions.items()
        ]
