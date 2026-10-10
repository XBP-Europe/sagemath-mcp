"""Every client's workspaces: keys, aliases, admission, the warm pool, culling."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time

from .config import DEFAULT_SETTINGS, SageSettings
from .errors import SageProcessError
from .session import SageSession

# The session logger, not this module's own: these lines were logged under
# `sagemath_mcp.session` before the 2026-09 split and still are.
LOGGER = logging.getLogger("sagemath_mcp.session")


# Workspace used when a caller does not name one.
DEFAULT_SESSION_NAME = "default"


# Separates the MCP client scope from the workspace name in a storage key.
# Chosen so it cannot collide with a name a caller might pick.
_NAME_SEPARATOR = "::"


# Server-issued workspace handles carry this prefix. A `session` argument that
# starts with it is treated as a portable handle (resolved through the alias
# map) rather than a workspace name, so the prefix is reserved: an ordinary
# name must not begin with it.
WORKSPACE_TOKEN_PREFIX = "wsk_"  # noqa: S105 - a prefix, not a credential


# Placeholder id a pre-warmed spare carries until a session adopts it and takes
# its real key. Never used as a storage key or a journal name.
_WARM_SPARE_ID = "__warm_spare__"


# Ceiling on the throwaway warm-up evaluation, so a wedged spare cannot hang the
# server's startup or a background refill.
_WARM_EVAL_TIMEOUT = 30.0


class SageSessionManager:
    """Track Sage sessions keyed by MCP session id."""

    def __init__(self, settings: SageSettings | None = None):
        self.settings = settings or DEFAULT_SETTINGS
        self._sessions: dict[str, SageSession] = {}
        self._lock = asyncio.Lock()
        # Portable workspace handles: token -> storage key. A token addresses a
        # workspace independently of the transport session id, so state survives
        # a reconnect or a transport that rotates the id per call. Mutated only
        # in coroutine steps with no await between read and write, so the
        # single-threaded event loop already serialises it -- no lock needed.
        self._aliases: dict[str, str] = {}
        # Spare workers with Sage preloaded but no client identity yet. A new
        # session adopts one instead of paying the ~2s startup import. Filled by
        # warm_up() at server start and topped up in the background; the refill
        # tasks are tracked so shutdown can cancel them.
        self._warm_pool: list[SageSession] = []
        # Refill task -> the spare it is warming, so whoever cancels a refill
        # holds a reference to reclaim that worker in its own (uncancelled)
        # context. A cancelled task cannot reliably shut its own worker down.
        self._warm_tasks: dict[asyncio.Task[bool], SageSession] = {}
        # Spares whose refill is still running -- tracked so a cancelled refill
        # (shutdown, or a real session reclaiming its slot) cannot leak the
        # worker it had already spawned, and so total-worker accounting can see
        # them before they reach `_warm_pool`.
        self._warm_in_flight: set[SageSession] = set()
        # Manager-owned reclamations: shutting a cancelled refill's worker down
        # is started here, not in the requesting task, so a caller cancelled
        # mid-cleanup cannot orphan a live worker. Its spare stays reserved in
        # `_warm_in_flight` until the process exits, and shutdown awaits these.
        self._reclaim_tasks: set[asyncio.Task[None]] = set()

    @staticmethod
    def key_for(scope: str, name: str = DEFAULT_SESSION_NAME) -> str:
        """Storage key for a named workspace within an MCP client scope.

        The default workspace keys on the bare scope, so keys and their journal
        filenames are unchanged from before named sessions existed.

        That shortcut is what makes the separator load-bearing. With it, two
        distinct pairs can compose to one key:

            key_for("A", "x")         -> "A::x"
            key_for("A::x", "default") -> "A::x"

        -- one client's named workspace and another client's default, sharing
        a worker and its namespace. It is not reachable today: the scope is
        the MCP session id, fastmcp issues it as a hex UUID and answers a
        client-supplied `Mcp-Session-Id` with 404 (measured, 2026-09-21). But
        that is an invariant of a dependency, asserted nowhere here, and the
        isolation this composes is the one thing the whole key scheme is for.

        So the scope is checked rather than trusted. Refusing costs nothing --
        no id fastmcp issues contains the separator -- and changing the key
        format instead would rename every persisted journal on disk.
        """
        if _NAME_SEPARATOR in scope:
            raise SageProcessError(
                f"A session scope may not contain {_NAME_SEPARATOR!r}: it would "
                "compose to the same storage key as another client's named "
                "workspace, and the two would share a worker"
            )
        name = (name or DEFAULT_SESSION_NAME).strip() or DEFAULT_SESSION_NAME
        return scope if name == DEFAULT_SESSION_NAME else f"{scope}{_NAME_SEPARATOR}{name}"

    @staticmethod
    def split_key(key: str) -> tuple[str, str]:
        """Inverse of key_for: recover (scope, name)."""
        scope, sep, name = key.partition(_NAME_SEPARATOR)
        return (scope, name) if sep else (key, DEFAULT_SESSION_NAME)

    def resolve_key(self, scope: str, name: str = DEFAULT_SESSION_NAME) -> str:
        """Storage key for a `session` argument, token-aware.

        An ordinary name composes with the transport `scope`, exactly as before.
        A server-issued handle (the reserved prefix) resolves through the alias
        map to the key it was minted for, ignoring `scope` entirely -- that is
        what makes the workspace portable across transport sessions. An
        unrecognised handle is refused rather than silently opening a fresh
        workspace: a caller cannot fabricate a handle to reach another's state,
        so unguessability is the isolation guarantee.
        """
        candidate = (name or DEFAULT_SESSION_NAME).strip() or DEFAULT_SESSION_NAME
        if candidate.startswith(WORKSPACE_TOKEN_PREFIX):
            key = self._aliases.get(candidate)
            if key is None:
                raise SageProcessError(
                    "Unknown or expired workspace handle. Start a workspace with "
                    "start_sage_session to get a valid one."
                )
            return key
        return self.key_for(scope, candidate)

    def mint_workspace_token(self, key: str) -> str:
        """Issue an unguessable portable handle addressing `key`."""
        token = WORKSPACE_TOKEN_PREFIX + secrets.token_urlsafe(24)
        self._aliases[token] = key
        return token

    def _forget_aliases_for(self, key: str) -> None:
        """Drop every handle pointing at a key whose worker is gone."""
        for token in [t for t, k in self._aliases.items() if k == key]:
            del self._aliases[token]

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
        """Shut down one workspace by name or handle. False if it did not exist."""
        try:
            key = self.resolve_key(scope, name)
        except SageProcessError:
            # An unknown handle names no live workspace, which is what "False"
            # says. Stopping is idempotent, so this is not an error.
            return False
        async with self._lock:
            session = self._sessions.pop(key, None)
        self._forget_aliases_for(key)
        if session is None:
            return False
        with contextlib.suppress(Exception):
            session.save_journal()
        await session.shutdown()
        return True

    async def warm_up(self) -> None:
        """Fill the spare-worker pool. Called once at server startup.

        Best-effort: a spare that fails to spawn is skipped, not fatal -- the
        next real ``get`` just spawns normally and pays the startup cost once.
        """
        target = max(0, self.settings.warm_pool_size)
        limit = self.settings.max_sessions
        while len(self._warm_pool) < target:
            # Spares count against the same ceiling as live workers, so the pool
            # never fills past max_sessions even before any client connects.
            if limit and (
                len(self._sessions) + len(self._warm_pool) + len(self._warm_in_flight)
            ) >= limit:
                break
            if not await self._spawn_warm_worker():
                break

    async def _spawn_warm_worker(self, spare: SageSession | None = None) -> bool:
        """Warm one spare and add it to the pool. Returns whether it landed.

        Spawning imports Sage, but the expensive part is the *first evaluation*
        -- Sage defers a second of lazy setup to it (~1.3s measured, then ~2ms).
        So the spare runs a throwaway `1+1` here, off any client's critical path,
        and its journal is wiped so it is pristine when adopted.

        The spare is created by the caller when this runs as a cancellable refill
        task (`_schedule_warm_refill`), so the canceller keeps a reference to it;
        `warm_up` passes ``None`` and one is made here.
        """
        if spare is None:
            spare = SageSession(_WARM_SPARE_ID, self.settings)
            self._warm_in_flight.add(spare)
        try:
            await spare.ensure_started()
            await spare.evaluate(
                "1+1",
                want_latex=False,
                capture_stdout=False,
                timeout_seconds=min(_WARM_EVAL_TIMEOUT, self.settings.eval_timeout),
            )
            spare._code_journal.clear()
        except asyncio.CancelledError:
            # Do NOT shut the worker down here. Awaiting a shutdown inside a
            # cancelled task is unreliable -- a re-delivered cancellation is
            # swallowed mid-way and the worker survives, which is exactly the
            # leak the reviewer reproduced. The spare stays in `_warm_in_flight`;
            # whoever cancelled this refill (get's reclaim, or shutdown) owns the
            # cleanup and performs it in an uncancelled context.
            raise
        except Exception as exc:
            with contextlib.suppress(Exception):
                await spare.shutdown()
            self._warm_in_flight.discard(spare)
            LOGGER.warning("Could not pre-warm a spare Sage worker: %s", exc)
            return False
        self._warm_in_flight.discard(spare)
        self._warm_pool.append(spare)
        return True

    def _start_reclaim(self, task: asyncio.Task[bool], spare: SageSession) -> asyncio.Task[None]:
        """Cancel a refill and hand its worker to a MANAGER-OWNED cleanup task.

        The cleanup is tracked in `_reclaim_tasks`, not run inline in the
        requesting coroutine, so a caller cancelled while waiting for it cannot
        abandon a live worker -- the earlier design ran the shutdown in the
        waiter's task and leaked the process when that task was cancelled.
        """
        task.cancel()
        cleanup = asyncio.ensure_future(self._reclaim_refill(task, spare))
        self._reclaim_tasks.add(cleanup)
        cleanup.add_done_callback(self._reclaim_tasks.discard)
        return cleanup

    async def _reclaim_refill(self, task: asyncio.Task[bool], spare: SageSession) -> None:
        """Await the cancelled refill, shut its worker down, then release the slot.

        The spare stays in `_warm_in_flight` -- counted by admission -- until its
        process has actually exited, so a replacement cannot start alongside it.
        """
        with contextlib.suppress(BaseException):
            await asyncio.gather(task, return_exceptions=True)
        with contextlib.suppress(Exception):
            await spare.shutdown()
        self._warm_in_flight.discard(spare)

    def _schedule_warm_refill(self) -> None:
        """Top the pool back up in the background after a spare is adopted.

        Never pushes total workers (live sessions + pool + in-flight refills)
        above ``max_sessions``; the refill is fire-and-forget, and its task is
        tracked so shutdown can cancel it.
        """
        target = max(0, self.settings.warm_pool_size)
        limit = self.settings.max_sessions
        # `_warm_in_flight` is the true reservation for the ceiling -- it holds a
        # spare through warming AND reclamation, so a worker mid-cleanup still
        # counts. The pool-target check uses live refills, since a reclaiming
        # spare is on its way out and should not block a fresh one.
        committed = len(self._sessions) + len(self._warm_pool) + len(self._warm_in_flight)
        if len(self._warm_pool) + len(self._warm_tasks) >= target:
            return
        if limit and committed >= limit:
            return
        spare = SageSession(_WARM_SPARE_ID, self.settings)
        self._warm_in_flight.add(spare)
        task = asyncio.create_task(self._spawn_warm_worker(spare))
        self._warm_tasks[task] = spare
        task.add_done_callback(lambda t: self._warm_tasks.pop(t, None))

    async def get(self, session_id: str) -> SageSession:
        adopted = False
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                # The ceiling is checked only when creating: an existing session
                # is always reachable, so a client can never be locked out of
                # state it already holds. Culling idle workers is the pressure
                # valve; this is the backstop for when even that is not enough.
                limit = self.settings.max_sessions
                if limit and len(self._sessions) >= limit:
                    raise SageProcessError(
                        f"Session limit reached ({limit} live workers). Stop an "
                        "unused workspace with stop_sage_session, or raise "
                        "SAGEMATH_MCP_MAX_SESSIONS."
                    )
                # Adopt a pre-warmed spare if one is ready: its worker has
                # already run the Sage preload, so the first call is fast. The
                # spare has no client identity until now -- reassigning its id is
                # safe because its namespace holds only the preload, no state.
                spare = self._warm_pool.pop() if self._warm_pool else None
                if spare is not None:
                    spare.session_id = session_id
                    session = spare
                    adopted = True
                else:
                    # A real worker takes priority over an opportunistic spare.
                    # If creating it would push the total -- live sessions + pool
                    # + in-flight refills -- over the ceiling, reclaim a pending
                    # refill's slot first. Without this, `get` counted only
                    # `_sessions` while the refill counted its own slot, so a
                    # spare and a new session could both take the last slot and
                    # overshoot max_sessions (CAP 2 LIVE 2 SPARES 1). The
                    # reservation (a spare in `_warm_in_flight`) is counted until
                    # its process has EXITED, and reclamation is manager-owned and
                    # shielded, so this waits for a genuinely free slot even if
                    # this request is cancelled mid-cleanup -- the worker still
                    # gets reclaimed and the slot is not double-counted.
                    # Loop only while there is something to reclaim: a live refill
                    # to cancel, or a reclamation already draining a slot. If the
                    # ceiling is hit with neither, the session ceiling (checked
                    # above) governs and there is nothing more to free here.
                    while (
                        limit
                        and len(self._sessions) + len(self._warm_pool) + len(self._warm_in_flight)
                        >= limit
                        and (self._warm_tasks or self._reclaim_tasks)
                    ):
                        if self._warm_tasks:
                            victim, victim_spare = next(iter(self._warm_tasks.items()))
                            del self._warm_tasks[victim]
                            await asyncio.shield(self._start_reclaim(victim, victim_spare))
                        else:
                            # A reclamation already owns the slot; wait for it to
                            # free one rather than overshoot.
                            await asyncio.shield(
                                asyncio.gather(*self._reclaim_tasks, return_exceptions=True)
                            )
                    session = SageSession(session_id, self.settings)
                    adopted = False
                self._sessions[session_id] = session
        if adopted:
            self._schedule_warm_refill()
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
        # Handles to a culled worker are dead; drop them so the map cannot grow
        # without bound. Presenting a forgotten handle now refuses rather than
        # silently opening an empty workspace -- parity with a culled name,
        # which the caller re-creates by name, is not possible for a handle
        # whose only identity was the token.
        for sid, _ in sessions_to_shutdown:
            self._forget_aliases_for(sid)
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
        # Stop refilling, and reclaim any spares that never got adopted.
        for task in list(self._warm_tasks):
            task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*self._warm_tasks, return_exceptions=True)
        self._warm_tasks.clear()
        # Await any manager-owned reclamations still in flight (a caller cancelled
        # mid-cleanup handed its worker to one of these), so shutdown does not
        # return while an owned worker is still being torn down.
        if self._reclaim_tasks:
            with contextlib.suppress(Exception):
                await asyncio.gather(*self._reclaim_tasks, return_exceptions=True)
        self._reclaim_tasks.clear()
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            # Include in-flight spares: a refill cancelled just above may not have
            # finished its own cleanup, so reclaim its worker here too (shutting
            # a session down twice is harmless).
            spares = list(self._warm_pool) + list(self._warm_in_flight)
            self._warm_pool.clear()
            self._warm_in_flight.clear()
        # Persist journals before shutting down workers (spares hold no state).
        for session in sessions:
            try:
                session.save_journal()
            except Exception:
                LOGGER.debug("Failed to save journal for %s", session.session_id)
        to_stop = sessions + spares
        if not to_stop:
            return
        results = await asyncio.gather(
            *(session.shutdown() for session in to_stop),
            return_exceptions=True,
        )
        sessions = to_stop
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
