"""Async management of SageMath worker processes."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from .channel import WorkerChannelMixin
from .config import DEFAULT_SETTINGS, SageSettings
from .errors import SageEvaluationError, SageProcessError
from .journal import JournalMixin

LOGGER = logging.getLogger(__name__)
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])

# Buffer for a single JSON response line from the worker. asyncio defaults to
# 64 KiB, which is smaller than legitimate results such as a base64-encoded
# plot. 8 MiB leaves generous headroom above the default max_stdout_chars
# without letting a runaway worker consume unbounded memory.
_STREAM_LIMIT = 8 * 1024 * 1024


@dataclass(slots=True)
class WorkerResult:
    result_type: str
    result: str | None
    latex: str | None
    stdout: str
    elapsed_ms: float


class SageSession(JournalMixin, WorkerChannelMixin):
    """Encapsulates a single long-lived Sage worker."""

    def __init__(self, session_id: str, settings: SageSettings | None = None):
        self.session_id = session_id
        self.settings = settings or DEFAULT_SETTINGS
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        # Serialises worker startup alone. `SageSessionManager.get` inserts the
        # session under the manager lock and then calls `ensure_started` outside
        # it, so two simultaneous first requests to one session share the object
        # but race into `_launch_worker` -- a scheduling probe produced two live
        # workers for two concurrent first calls, the second leaked. This is a
        # separate lock from `self._lock` on purpose: `evaluate` and `reset`
        # call `ensure_started` and then take `self._lock`, so reusing it would
        # be a re-entrant acquire, and `self._lock`'s no-take contract for
        # cancel/interrupt is load-bearing enough not to widen.
        self._startup_lock = asyncio.Lock()
        self.started_at = time.time()
        self.last_used_at = self.started_at
        # (code, trusted) per statement. Trust is not a property of the text:
        # replaying a specialized tool's snippet under the caller policy fails,
        # and replaying caller code under the trusted one would hand it sage_eval.
        self._code_journal: list[tuple[str, bool]] = []
        # The request id the worker is executing right now, or None when idle.
        self._in_flight: str | None = None
        self._dropped_stdout_lines = 0
        self._queued_stdout_chars = 0

    async def ensure_started(self) -> None:
        if self._process and self._process.returncode is None:
            return
        async with self._startup_lock:
            # Re-check under the lock: the loser of the race arrives here after
            # the winner has already launched, and must not launch a second.
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
            # The worker leads its own process group. Sage spawns helpers of
            # its own -- the pexpect interfaces fork GAP and friends -- and a
            # kill that reaches only the worker leaves those orphaned and
            # computing. Killing the group (see _kill_worker_group) reaps them.
            start_new_session=True,
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
            # Created inside the lock: a request cancelled while queued for it
            # never reaches the cleanup below, so a pump started earlier would
            # outlive the request that owned it.
            queue: asyncio.Queue[str | None] | None = None
            pump: asyncio.Task[None] | None = None
            if on_stdout is not None:
                queue, pump = self._start_stdout_pump(on_stdout)
            try:
                raw, response = await self._exchange(
                    data, payload["id"], queue, pump, effective_timeout
                )
            finally:
                # Whatever happened, no consumer task outlives this request.
                await self._stop_stdout_pump(pump)
            if not raw:
                raise SageProcessError("Sage worker terminated unexpectedly.")
        self.last_used_at = time.time()
        return self._result_from(response, code, trusted)

    async def _exchange(
        self,
        data: bytes,
        request_id: str,
        queue: asyncio.Queue[str | None] | None,
        pump: asyncio.Task[None] | None,
        effective_timeout: float,
    ) -> tuple[bytes, dict]:
        """Send one request and read its response, under the caller's timeout."""
        assert self._process and self._process.stdin
        self._process.stdin.write(data)
        await self._process.stdin.drain()
        self._in_flight = request_id
        try:
            raw, response = await asyncio.wait_for(
                self._read_matching_response(request_id, queue),
                timeout=effective_timeout,
            )
        except TimeoutError as exc:
            await self._handle_timeout()
            # Deliberately no drain here. Waiting on the caller's callback held
            # the TimeoutError until the callback was released, so the caller
            # waited indefinitely for news of a computation already abandoned.
            # The message coaches the model, not just the operator: it says
            # what happened to the state and which tool fits the retry. A bare
            # "timed out" reads as "try the same call again", which repeats the
            # timeout and discards a fresh namespace each time.
            raise TimeoutError(
                f"Sage evaluation timed out after {effective_timeout:.2f}s. "
                "The worker was restarted and the session's variables were "
                "discarded. Retry with a larger per-call `timeout`; for long "
                "computations prefer evaluate_sage_streaming to watch "
                "progress, and interrupt_sage_session to stop one while "
                "keeping its variables."
            ) from exc
        except asyncio.CancelledError:
                # The caller went away, but the worker is still computing: the
                # next request would queue behind a computation nobody wants.
                # Only evaluate_sage used to handle this, by restarting the
                # worker; streaming and the specialised tools left it running.
                # Interrupting here covers all three and keeps the namespace,
                # and the resulting "Interrupted" response is discarded by the
                # id check in _read_response.
            await self.interrupt()
            raise
        finally:
            self._in_flight = None
        # Success only: deliver everything queued before the caller sees the
        # result, and outside the timeout so a slow callback cannot turn a
        # finished computation into a timeout.
        await self._drain_stdout_pump(queue, pump)
        return raw, response

    def _result_from(self, response: dict, code: str, trusted: bool) -> WorkerResult:
        if not response.get("ok", False):
            error = response.get("error", {})
            raise SageEvaluationError(
                error.get("message", "Unknown Sage error"),
                error_type=error.get("type", "Exception"),
                stdout=response.get("stdout", ""),
                traceback=error.get("traceback", ""),
            )
        self._code_journal.append((code, trusted))
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
            # Match the response id, exactly as evaluate() does. Reading the next
            # line unconditionally meant a cancelled evaluation's response was
            # consumed here: reset saw someone else's failure and reported
            # "Failed to reset Sage session" for a reset that was fine.
            raw, response = await self._read_matching_response(payload["id"], None)
            if not raw:
                raise SageProcessError("Sage worker terminated during reset.")
        if not response.get("ok", False):
            raise SageProcessError("Failed to reset Sage session.")
        self._code_journal.clear()
        self._discard_persisted_journal()
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

        Returns False when there is nothing to interrupt. POSIX only.
        """
        if not self._process or self._process.returncode is not None:
            return False
        # Nothing running: do NOT signal. An idle worker is blocked in
        # readline(), where a SIGINT has no computation to abort -- and against
        # real Sage it left the worker unable to answer the next request at all,
        # which then timed out and cost the namespace the interrupt was meant to
        # protect. Reporting "nothing running" is also simply true.
        if self._in_flight is None:
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
            self._kill_worker_group()
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
        if self._in_flight is None:
            # The worker already answered; whatever ran long was on this side.
            # Restarting here would discard a namespace over a delay the worker
            # had no part in. Belt and braces -- the drain now happens outside
            # the timeout, so this should no longer be reachable.
            LOGGER.warning(
                "Timeout in Sage session %s after the worker had answered; "
                "keeping the worker",
                self.session_id,
            )
            return
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
                self._kill_worker_group()
                await self._process.wait()
        self._process = None

    def _kill_worker_group(self) -> None:
        """SIGKILL the worker and everything it spawned.

        The worker was started with ``start_new_session=True``, so its pid is
        its process group. Killing only the worker left the children Sage forks
        for its pexpect interfaces (GAP most visibly) alive and computing after
        a cancel or timeout. ``interrupt`` deliberately does NOT use this: a
        SIGINT goes to the worker alone, which forwards it to its interfaces
        the same way the Sage REPL does.
        """
        assert self._process is not None
        # AttributeError: no killpg outside POSIX. OSError: the group is
        # already gone, or the pid was reaped and reused by another user.
        with contextlib.suppress(AttributeError, OSError):
            os.killpg(self._process.pid, signal.SIGKILL)
        # Reaching the worker directly is harmless after a successful group
        # kill and is what remains of the old behaviour everywhere else.
        with contextlib.suppress(OSError):
            self._process.kill()
