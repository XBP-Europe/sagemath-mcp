"""Async management of SageMath worker processes."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_SETTINGS, SageSettings

LOGGER = logging.getLogger(__name__)
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])

# Workspace used when a caller does not name one.
DEFAULT_SESSION_NAME = "default"
# Separates the MCP client scope from the workspace name in a storage key.
# Chosen so it cannot collide with a name a caller might pick.
_NAME_SEPARATOR = "::"

# Buffer for a single JSON response line from the worker. asyncio defaults to
# 64 KiB, which is smaller than legitimate results such as a base64-encoded
# plot. 8 MiB leaves generous headroom above the default max_stdout_chars
# without letting a runaway worker consume unbounded memory.
_STREAM_LIMIT = 8 * 1024 * 1024


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
        self._code_journal: list[str] = []

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
        pythonpath_entries: list[str] = []
        if (sage_venv := env.get("SAGE_VENV")):
            py_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
            site_packages = Path(sage_venv) / "lib" / py_version / "site-packages"
            pythonpath_entries.append(str(site_packages))
        pythonpath_entries.append(_PROJECT_ROOT)
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
            # One JSON response is read with a single readline(), so the whole
            # payload must fit in the stream buffer. asyncio's 64 KiB default
            # raises LimitOverrunError on larger results -- a base64 PNG from
            # plot3d_expression is around 100 KiB, and matrices or series can
            # also exceed it. Sized against max_stdout, which already bounds
            # how much a result may carry.
            limit=_STREAM_LIMIT,
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

    async def _read_response(
        self, request_id: str, on_stdout: Callable[[str], Awaitable[None]] | None = None
    ) -> tuple[bytes, dict]:
        """Read until the response for *request_id* arrives, discarding stragglers.

        A cancelled or timed-out request leaves its response in the pipe. Without
        this the next request read that stale line and returned the previous
        computation's result as its own.

        Interleaved {"type": "stdout"} events are dispatched to *on_stdout* as
        they arrive, which is what makes streaming actually stream rather than
        replay after completion.
        """
        assert self._process and self._process.stdout
        while True:
            raw = await self._process.stdout.readline()
            if not raw:
                return raw, {}
            try:
                message = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                LOGGER.warning("Discarding unparsable worker line in %s", self.session_id)
                continue
            if message.get("type") == "stdout" and message.get("id") == request_id:
                if on_stdout is not None:
                    await on_stdout(message.get("text", ""))
                continue
            incoming = message.get("id")
            if incoming is not None and incoming != request_id:
                LOGGER.warning(
                    "Discarding stale worker response %s in %s (waiting for %s)",
                    incoming, self.session_id, request_id,
                )
                continue
            return raw, message

    async def evaluate(
        self,
        code: str,
        *,
        want_latex: bool,
        capture_stdout: bool,
        timeout_seconds: float | None = None,
        trusted: bool = False,
        on_stdout: Callable[[str], Awaitable[None]] | None = None,
    ) -> WorkerResult:
        await self.ensure_started()
        assert self._process and self._process.stdin and self._process.stdout
        payload = {
            "id": str(uuid.uuid4()),
            "type": "execute",
            "code": code,
            "want_latex": want_latex,
            "capture_stdout": capture_stdout,
            # Server-generated snippets may use sage_eval; caller code may not.
            "trusted": trusted,
            # Ask the worker to emit stdout line events as they happen.
            "stream": on_stdout is not None,
        }
        data = json.dumps(payload).encode("utf-8") + b"\n"
        effective_timeout = timeout_seconds or self.settings.eval_timeout
        async with self._lock:
            self._process.stdin.write(data)
            await self._process.stdin.drain()
            try:
                raw, response = await asyncio.wait_for(
                    self._read_response(payload["id"], on_stdout), timeout=effective_timeout
                )
            except TimeoutError as exc:
                await self._handle_timeout()
                raise TimeoutError(
                    f"Sage evaluation timed out after {effective_timeout:.2f}s"
                ) from exc
            if not raw:
                raise SageProcessError("Sage worker terminated unexpectedly.")
        self.last_used_at = time.time()
        if not response.get("ok", False):
            error = response.get("error", {})
            raise SageEvaluationError(
                error.get("message", "Unknown Sage error"),
                error_type=error.get("type", "Exception"),
                stdout=response.get("stdout", ""),
                traceback=error.get("traceback", ""),
            )
        self._code_journal.append(code)
        return WorkerResult(
            result_type=response["result_type"],
            result=response.get("result"),
            latex=response.get("latex"),
            stdout=response.get("stdout", ""),
            elapsed_ms=float(response.get("elapsed_ms", 0.0)),
        )

    def _persist_path(self) -> Path | None:
        """Return the journal file path if persistence is enabled."""
        if not self.settings.persist_sessions or not self.settings.persist_dir:
            return None
        d = Path(self.settings.persist_dir)
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self._journal_stem()}.journal.json"

    def _journal_stem(self) -> str:
        """A filename that is unique per session id.

        Replacing every unsafe character with "_" was not injective: the
        workspaces "a/b" and "a?b" both became "a_b", so one could overwrite the
        other's journal and later restore the wrong code into its namespace.

        A readable prefix keeps the files identifiable while a digest of the
        full id guarantees distinct keys get distinct paths.
        """
        readable = re.sub(r"[^A-Za-z0-9._-]", "_", self.session_id)[:48]
        digest = hashlib.sha256(self.session_id.encode("utf-8")).hexdigest()[:12]
        return f"{readable}-{digest}"

    def save_journal(self) -> None:
        """Write the code journal to disk for later restoration."""
        path = self._persist_path()
        if path is None:
            return
        path.write_text(json.dumps(self._code_journal))
        LOGGER.debug("Saved journal for %s (%d entries)", self.session_id, len(self._code_journal))

    @classmethod
    def load_journal(cls, path: Path) -> list[str]:
        """Read a code journal from disk."""
        return json.loads(path.read_text())

    async def restore_from_journal(self, journal: list[str]) -> int:
        """Replay saved code entries to rebuild session state.

        Returns the number of entries successfully replayed.
        """
        replayed = 0
        for code in journal:
            try:
                await self.evaluate(
                    code, want_latex=False, capture_stdout=False
                )
                replayed += 1
            except Exception:
                LOGGER.warning(
                    "Journal replay failed at entry %d for %s",
                    replayed, self.session_id,
                )
                break
        return replayed

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
        self._code_journal.clear()
        self.last_used_at = time.time()

    async def interrupt(self) -> bool:
        """Abort the running computation but keep the namespace.

        Deliberately does not take ``self._lock``: the evaluation being
        interrupted is holding it, so waiting for it would deadlock until the
        computation everyone is trying to stop finishes on its own.

        The worker turns the resulting KeyboardInterrupt into an "Interrupted"
        error response, so the in-flight ``evaluate`` returns normally and every
        variable defined so far survives. Contrast ``cancel``, which restarts
        the worker and discards the namespace.

        Returns False when there is no live worker to signal. POSIX only.
        """
        if not self._process or self._process.returncode is not None:
            return False
        LOGGER.info("Interrupting Sage session %s (pid=%s)", self.session_id, self._process.pid)
        try:
            self._process.send_signal(signal.SIGINT)
        except (ProcessLookupError, OSError) as exc:
            LOGGER.warning("Could not interrupt session %s: %s", self.session_id, exc)
            return False
        self.last_used_at = time.time()
        return True

    async def cancel(self) -> None:
        """Restart the worker to cooperatively cancel any in-flight computation.

        This discards the namespace. Prefer ``interrupt`` unless the worker is
        wedged badly enough that signalling it does not help.
        """
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

    @staticmethod
    def key_for(scope: str, name: str = DEFAULT_SESSION_NAME) -> str:
        """Storage key for a named workspace within an MCP client scope.

        The default workspace keys on the bare scope, so keys and their journal
        filenames are unchanged from before named sessions existed.
        """
        name = (name or DEFAULT_SESSION_NAME).strip() or DEFAULT_SESSION_NAME
        return scope if name == DEFAULT_SESSION_NAME else f"{scope}{_NAME_SEPARATOR}{name}"

    @staticmethod
    def split_key(key: str) -> tuple[str, str]:
        """Inverse of key_for: recover (scope, name)."""
        scope, sep, name = key.partition(_NAME_SEPARATOR)
        return (scope, name) if sep else (key, DEFAULT_SESSION_NAME)

    async def list_for_scope(self, scope: str) -> list[dict[str, object]]:
        """Describe every workspace belonging to one MCP client."""
        async with self._lock:
            items = [
                (key, session)
                for key, session in self._sessions.items()
                if self.split_key(key)[0] == scope
            ]
        return [
            {
                "name": self.split_key(key)[1],
                "alive": session.is_alive(),
                "started_at": session.started_at,
                "last_used_at": session.last_used_at,
                "statements": len(session._code_journal),
            }
            for key, session in sorted(items, key=lambda pair: self.split_key(pair[0])[1])
        ]

    async def stop(self, scope: str, name: str) -> bool:
        """Shut down one named workspace. Returns False if it did not exist."""
        key = self.key_for(scope, name)
        async with self._lock:
            session = self._sessions.pop(key, None)
        if session is None:
            return False
        with contextlib.suppress(Exception):
            session.save_journal()
        await session.shutdown()
        return True

    async def get(self, session_id: str) -> SageSession:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = SageSession(session_id, self.settings)
                self._sessions[session_id] = session
        await session.ensure_started()
        # Restore persisted journal if available
        if not session._code_journal:
            path = session._persist_path()
            if path and path.exists():
                journal = SageSession.load_journal(path)
                if journal:
                    LOGGER.info(
                        "Restoring %d entries for %s",
                        len(journal), session_id,
                    )
                    await session.restore_from_journal(journal)
        return session

    async def reset(self, session_id: str) -> None:
        session = await self.get(session_id)
        await session.reset()

    async def cancel(self, session_id: str) -> None:
        session = await self.get(session_id)
        await session.cancel()

    async def interrupt(self, session_id: str) -> bool:
        """Signal a running computation without creating a session if absent."""
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return False
        return await session.interrupt()

    async def cull_idle(self) -> None:
        now = time.time()
        sessions_to_shutdown: list[tuple[str, SageSession]] = []
        async with self._lock:
            stale = [sid for sid, sess in self._sessions.items() if sess.should_cull(now)]
            for sid in stale:
                session = self._sessions.pop(sid, None)
                if session:
                    sessions_to_shutdown.append((sid, session))
        if not sessions_to_shutdown:
            return
        LOGGER.info("Culling %d idle Sage session(s)", len(sessions_to_shutdown))
        # Persist before terminating. shutdown() and stop() already do this, but
        # culling did not -- so with persistence enabled the ordinary idle
        # lifecycle silently discarded state that was meant to survive.
        for sid, session in sessions_to_shutdown:
            try:
                session.save_journal()
            except Exception:  # never let a journal failure block reclaiming a worker
                LOGGER.warning("Failed to persist journal for culled session %s", sid)
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
        # Persist journals before shutting down workers
        for session in sessions:
            try:
                session.save_journal()
            except Exception:
                LOGGER.debug("Failed to save journal for %s", session.session_id)
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
