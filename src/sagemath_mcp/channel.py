"""The session's side of the worker protocol: stdout events and responses."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable

from .errors import SageProcessError

# The session logger, not this module's own: these lines were logged under
# `sagemath_mcp.session` before the 2026-09 split and still are.
LOGGER = logging.getLogger("sagemath_mcp.session")


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


class WorkerChannelMixin:
    """Reading the worker's stdout: progress lines and the matching response.

    Mixed into `SageSession`, which provides `session_id`, `_process`,
    `_in_flight` and the two stdout counters. Kept apart because the framing
    rules -- stale responses, bounded progress queues, a slow callback that
    must not stall the read -- are a protocol, not session lifecycle.
    """

    # Provided by SageSession; declared so the type checker sees them here.
    session_id: str
    _process: asyncio.subprocess.Process | None
    _in_flight: str | None
    _dropped_stdout_lines: int
    _queued_stdout_chars: int

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
        assert self._process and self._process.stdout  # noqa: S101
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
