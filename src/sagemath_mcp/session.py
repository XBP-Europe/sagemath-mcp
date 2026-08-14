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

# Subdirectory holding journals written by the current naming scheme.
_JOURNAL_NAMESPACE = "v2"

# How many non-matching lines to skip before declaring the worker unusable.
_MAX_DISCARDED_RESPONSES = 64

# Two budgets, because each one alone has a hole. Characters alone: ten thousand
# empty lines account for zero characters and still cost a queue entry each.
# Entries alone: a thousand lines bounds nothing when a line can be a gigabyte.
# The full stdout still travels with the result, so dropping progress events
# loses nothing a caller cannot recover.
_MAX_QUEUED_STDOUT_CHARS = 1_000_000
_MAX_QUEUED_STDOUT_LINES = 1_000

# A single line longer than the whole budget cannot be made to fit by dropping
# others, so it is truncated rather than stored whole.
_STDOUT_TRUNCATION_MARKER = "... [truncated]"
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


def _journal_entry(item) -> tuple[str, bool]:
    """Read one journal entry, in either the old or the current shape.

    Journals written before trust was recorded are plain strings. Those predate
    the specialized tools ever being replayable, so untrusted is both the safe
    reading and the accurate one.
    """
    if isinstance(item, dict):
        return item.get("code", ""), bool(item.get("trusted", False))
    return str(item), False


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

    def _start_stdout_pump(
        self, on_stdout: Callable[[str], Awaitable[None]]
    ) -> tuple[asyncio.Queue[str | None], asyncio.Task[None]]:
        # No maxsize: the bound is the character budget enforced in
        # _offer_stdout_line. A maxsize'd queue also refuses the sentinel that
        # ends the pump, so a full queue turned a completed evaluation into a
        # QueueFull -- the bound must never be able to fail the request itself.
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._queued_stdout_chars = 0
        return queue, asyncio.create_task(self._pump_stdout(queue, on_stdout))

    def _offer_stdout_line(self, queue: asyncio.Queue[str | None], text: str) -> None:
        """Queue a progress line, dropping the oldest if the consumer is behind.

        Progress events are advisory: the complete stdout is returned with the
        result either way, so dropping the middle of a burst loses nothing a
        caller cannot recover. Blocking here, or growing without limit, would
        lose the whole session.
        """
        if len(text) > _MAX_QUEUED_STDOUT_CHARS:
            # Dropping every other line still would not make room for this one.
            keep = _MAX_QUEUED_STDOUT_CHARS - len(_STDOUT_TRUNCATION_MARKER)
            text = text[:keep] + _STDOUT_TRUNCATION_MARKER
        while (
            (
                self._queued_stdout_chars + len(text) > _MAX_QUEUED_STDOUT_CHARS
                or queue.qsize() >= _MAX_QUEUED_STDOUT_LINES
            )
            and not queue.empty()
        ):
            try:
                dropped = queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - guarded by empty()
                break
            # `or ""` rather than a None check: the sentinel is only queued when
            # draining, which cannot overlap with offering, so a None here is
            # impossible -- and an unreachable branch is worse than an arithmetic
            # identity.
            self._queued_stdout_chars -= len(dropped or "")
            self._dropped_stdout_lines += 1
        queue.put_nowait(text)
        self._queued_stdout_chars += len(text)

    async def _stop_stdout_pump(self, pump: asyncio.Task[None] | None) -> None:
        """Stop the consumer without waiting on the caller's callback.

        Used on every exit path. After a successful drain the task is already
        finished and this is a no-op; after a timeout or a cancellation it is
        what guarantees the task does not outlive the request, and it must not
        block on a callback that may never return.
        """
        if pump is None or pump.done():
            return
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await pump

    async def _drain_stdout_pump(
        self, queue: asyncio.Queue[str | None] | None, pump: asyncio.Task[None] | None
    ) -> None:
        """Deliver whatever is queued, then stop the consumer.

        Deliberately not inside the evaluation timeout. Draining waits on the
        caller's callback, and counting that against the computation clock turned
        a finished evaluation into a TimeoutError -- which then restarted a worker
        that had already answered, losing the namespace.
        """
        if queue is None or pump is None:
            return
        queue.put_nowait(None)                  # sentinel: no more lines
        with contextlib.suppress(Exception):
            await pump

    async def _pump_stdout(
        self, queue: asyncio.Queue[str | None], on_stdout: Callable[[str], Awaitable[None]]
    ) -> None:
        """Deliver stdout lines in order, off the read loop's critical path."""
        while True:
            text = await queue.get()
            if text is None:
                return
            self._queued_stdout_chars -= len(text)
            with contextlib.suppress(Exception):
                await on_stdout(text)

    async def _read_matching_response(
        self, request_id: str, queue: asyncio.Queue[str | None] | None
    ) -> tuple[bytes, dict]:
        """Read until the response for *request_id* arrives, discarding stragglers.

        A cancelled or timed-out request leaves its response in the pipe. Without
        this the next request read that stale line and returned the previous
        computation's result as its own.

        Interleaved {"type": "stdout"} events go onto *queue* rather than being
        awaited here. A caller's callback is arbitrary code and may be slow, and
        awaiting it stopped the read loop: the worker could finish, print its
        response and go back to waiting for input -- genuinely idle -- while this
        session still believed a computation was running.
        """
        assert self._process and self._process.stdout
        discarded = 0
        while True:
            raw = await self._process.stdout.readline()
            if not raw:
                self._in_flight = None      # the worker is gone, not computing
                return raw, {}
            try:
                message = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                LOGGER.warning("Discarding unparsable worker line in %s", self.session_id)
                continue
            if message.get("type") == "stdout" and message.get("id") == request_id:
                if queue is not None:
                    self._offer_stdout_line(queue, message.get("text", ""))
                continue
            incoming = message.get("id")
            if incoming != request_id:
                # Including id-less lines. Accepting those let anything the
                # worker printed stand in for the answer to this request.
                discarded += 1
                if discarded > _MAX_DISCARDED_RESPONSES:
                    # Bounded, because "keep reading until the right id turns
                    # up" is unbounded when the peer keeps repeating itself: a
                    # worker stuck on one line spun here until the process ran
                    # out of memory.
                    raise SageProcessError(
                        f"Sage worker sent {discarded} responses that do not answer "
                        f"request {request_id}; abandoning it."
                    )
                LOGGER.warning(
                    "Discarding stale worker response %r in %s (waiting for %s)",
                    incoming, self.session_id, request_id,
                )
                continue
            # The worker has answered and is back waiting for input: it is idle
            # from here, whatever the caller still has to do with the result.
            self._in_flight = None
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
            raise TimeoutError(
                f"Sage evaluation timed out after {effective_timeout:.2f}s"
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

    def _persist_path(self) -> Path | None:
        """Return the journal file path if persistence is enabled."""
        if not self.settings.persist_sessions or not self.settings.persist_dir:
            return None
        # Versioned namespace: digest-named files live in their own directory
        # so they cannot collide with a legacy flat file that happens to share a
        # name, and so a future scheme change is a new directory rather than
        # another round of ambiguity.
        d = Path(self.settings.persist_dir) / _JOURNAL_NAMESPACE
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self._journal_stem()}.journal.json"

    def _legacy_persist_paths(self) -> list[Path]:
        """Journal paths written by earlier versions of this code.

        Two schemes preceded the digest: the raw session id, and a lossy
        sanitisation of it. Both are still on disk for anyone upgrading, and
        without this the rename silently orphans every persisted session --
        including plain default ones, whose filename was previously just the
        session id.
        """
        if not self.settings.persist_sessions or not self.settings.persist_dir:
            return []
        d = Path(self.settings.persist_dir)
        # The un-namespaced digest file, from the scheme between the two. The
        # digest covers the whole session id, so this one names its owner
        # unambiguously and is always safe to adopt.
        candidates = [d / f"{self._journal_stem()}.journal.json"]
        # The oldest scheme sanitised unsafe characters away, which is exactly
        # why it was replaced: "a/b" and "a?b" both wrote "a_b.journal.json".
        # Adopting such a file would be guessing whose state it is, so fall back
        # only when the sanitisation changed nothing and the name proves identity.
        sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", self.session_id)
        if sanitized == self.session_id and self.session_id:
            candidates.append(d / f"{self.session_id}.journal.json")
        seen: set[Path] = set()
        return [p for p in candidates if not (p in seen or seen.add(p))]

    def existing_journal_path(self) -> Path | None:
        """The journal to restore from, preferring the current scheme."""
        current = self._persist_path()
        if current is not None and current.exists():
            return current
        for legacy in self._legacy_persist_paths():
            if legacy.exists():
                LOGGER.info(
                    "Restoring %s from a legacy journal path (%s)", self.session_id, legacy.name
                )
                return legacy
        return None

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
        if path is not None:
            # Retire any pre-digest file so the two schemes cannot diverge.
            for legacy in self._legacy_persist_paths():
                if legacy != path and legacy.exists():
                    with contextlib.suppress(OSError):
                        legacy.unlink()
        if path is None:
            return
        # Atomic: a crash or a full disk mid-write previously left a truncated
        # journal that failed to parse on the next start, losing the session.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps([{"code": code, "trusted": trusted}
                        for code, trusted in self._code_journal])
        )
        os.replace(tmp, path)
        LOGGER.debug("Saved journal for %s (%d entries)", self.session_id, len(self._code_journal))

    @classmethod
    def load_journal(cls, path: Path) -> list[str]:
        """Read a code journal from disk."""
        return json.loads(path.read_text())

    async def restore_from_journal(self, journal: list) -> int:
        """Replay saved code entries to rebuild session state.

        Each entry carries the trust mode it originally ran under. Blessing
        every entry instead would put caller code on the trusted path, which is
        the one thing the policy split exists to prevent; refusing every entry
        (the previous behaviour) broke restoration for any session that had used
        a specialized tool.

        Returns the number of entries successfully replayed.
        """
        replayed = 0
        for code, trusted in (_journal_entry(item) for item in journal):
            try:
                await self.evaluate(
                    code, want_latex=False, capture_stdout=False, trusted=trusted
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
            # Falls back to pre-digest filenames so upgrading does not lose state.
            path = session.existing_journal_path()
            if path:
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
                # Listed and popped under the same lock, so it is still there.
                sessions_to_shutdown.append((sid, self._sessions.pop(sid)))
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
