"""The pre-warmed spare-worker pool.

A worker pays a multi-second `from sage.all import *` on spawn, so without a
pool every new session's first call is slow. The manager keeps a small pool of
spares (Sage already loaded, no client identity yet); a new session adopts one
and the pool refills in the background. These tests use the pure-Python worker,
so "warm" is fast, but the pool mechanics are the same.
"""

from __future__ import annotations

import asyncio
import contextlib

from sagemath_mcp.config import SageSettings
from sagemath_mcp.session import _WARM_SPARE_ID, SageProcessError, SageSession, SageSessionManager


def _settings(**kw) -> SageSettings:
    base = {"force_python_worker": True, "startup_code": "from math import *"}
    base.update(kw)
    return SageSettings(**base)


async def test_warm_up_fills_the_pool():
    manager = SageSessionManager(_settings(warm_pool_size=2))
    try:
        await manager.warm_up()
        assert len(manager._warm_pool) == 2
        assert all(s.session_id == _WARM_SPARE_ID for s in manager._warm_pool)
        assert all(s.is_alive() for s in manager._warm_pool)
    finally:
        await manager.shutdown()


async def test_a_new_session_adopts_a_spare_and_the_pool_refills():
    manager = SageSessionManager(_settings(warm_pool_size=1))
    try:
        await manager.warm_up()
        spare = manager._warm_pool[0]
        session = await manager.get("client-a")
        # The very object that was warmed is now the client's session, re-keyed.
        assert session is spare
        assert session.session_id == "client-a"
        assert not manager._warm_pool  # popped
        # Background refill tops it back up.
        for _ in range(50):
            if manager._warm_pool:
                break
            await asyncio.sleep(0.02)
        assert len(manager._warm_pool) == 1
    finally:
        await manager.shutdown()


async def test_warm_pool_size_zero_disables_it():
    manager = SageSessionManager(_settings(warm_pool_size=0))
    try:
        await manager.warm_up()
        assert manager._warm_pool == []
        # A normal get still works, spawning fresh.
        session = await manager.get("client-b")
        assert session.is_alive()
        assert not manager._warm_pool  # nothing to refill
    finally:
        await manager.shutdown()


async def test_the_pool_never_grows_past_the_session_ceiling():
    # Ceiling 1: one live session leaves no room for a spare, so no refill fires.
    manager = SageSessionManager(_settings(warm_pool_size=1, max_sessions=1))
    try:
        await manager.warm_up()  # can warm to 1 (no sessions yet)
        assert len(manager._warm_pool) == 1
        await manager.get("only")  # adopts the spare; now 1 session, 0 spares
        await asyncio.sleep(0.1)
        # Refill must not push total workers over the ceiling.
        assert manager._warm_pool == []
        assert not manager._warm_tasks
    finally:
        await manager.shutdown()


async def test_a_failed_warm_up_is_survivable(monkeypatch):
    manager = SageSessionManager(_settings(warm_pool_size=2))

    async def boom(self):
        raise SageProcessError("cannot spawn")

    monkeypatch.setattr(SageSession, "ensure_started", boom)
    try:
        # warm_up stops at the first failure rather than looping forever, and
        # does not raise.
        await manager.warm_up()
        assert manager._warm_pool == []
    finally:
        await manager.shutdown()


async def test_shutdown_reclaims_unadopted_spares():
    manager = SageSessionManager(_settings(warm_pool_size=2))
    await manager.warm_up()
    spares = list(manager._warm_pool)
    assert spares
    await manager.shutdown()
    assert manager._warm_pool == []
    assert not any(s.is_alive() for s in spares)


async def test_refill_is_a_no_op_when_the_pool_is_already_full():
    manager = SageSessionManager(_settings(warm_pool_size=1))
    try:
        await manager.warm_up()  # pool is at target
        manager._schedule_warm_refill()  # nothing to do
        assert not manager._warm_tasks
    finally:
        await manager.shutdown()


async def test_shutdown_cancels_a_pending_refill(monkeypatch):
    manager = SageSessionManager(_settings(warm_pool_size=1))
    await manager.warm_up()

    stuck = asyncio.Event()

    async def never_finishes(spare=None):
        await stuck.wait()  # never set -> the refill task stays pending
        return True

    monkeypatch.setattr(manager, "_spawn_warm_worker", never_finishes)
    await manager.get("a")  # adopts the spare and schedules the (stuck) refill
    assert manager._warm_tasks
    await manager.shutdown()  # must cancel the pending task, not hang
    assert not manager._warm_tasks


def test_the_ceiling_and_pool_size_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("SAGEMATH_MCP_WARM_POOL_SIZE", "3")
    assert SageSettings.from_env().warm_pool_size == 3


async def test_a_refill_never_pushes_the_total_over_the_ceiling(monkeypatch):
    """Capacity race (external review, round 2): with max_sessions=2 and
    warm_pool_size=1, a client adopting the spare schedules a refill; a second
    client starting before that refill finishes must not overshoot the ceiling.
    The refill counted its slot but `get` counted only live sessions, so both
    could take the last slot (CAP 2 LIVE 2 SPARES 1).
    """
    manager = SageSessionManager(_settings(max_sessions=2, warm_pool_size=1))
    try:
        await manager.warm_up()
        assert len(manager._warm_pool) == 1

        started = asyncio.Event()
        release = asyncio.Event()
        real_spawn = manager._spawn_warm_worker

        async def blocking_spawn(spare=None):
            started.set()
            await release.wait()
            return await real_spawn(spare)

        monkeypatch.setattr(manager, "_spawn_warm_worker", blocking_spawn)

        await manager.get("A")  # adopts the spare, schedules the (blocked) refill
        await asyncio.wait_for(started.wait(), 2)  # refill is in flight
        await manager.get("B")  # must reclaim the pending slot, not overshoot

        total = len(manager._sessions) + len(manager._warm_pool) + len(manager._warm_tasks)
        assert total <= 2, f"total workers overshoot the ceiling: {total}"
        release.set()
        await asyncio.sleep(0.05)
        assert len(manager._sessions) + len(manager._warm_pool) + len(manager._warm_tasks) <= 2
    finally:
        release.set()
        await manager.shutdown()


async def test_shutdown_reclaims_a_spare_whose_refill_is_cancelled(monkeypatch):
    """Cancellation leak (external review, round 2): when shutdown cancels a
    refill after its worker has spawned, the worker must be reclaimed. The old
    `except Exception` did not cover CancelledError, so the spare leaked.
    """
    manager = SageSessionManager(_settings(max_sessions=4, warm_pool_size=1))
    entered = asyncio.Event()
    release = asyncio.Event()
    shut_down: list[SageSession] = []
    real_shutdown = SageSession.shutdown

    async def tracked_shutdown(self):
        shut_down.append(self)
        return await real_shutdown(self)

    real_eval = SageSession.evaluate

    async def blocking_eval(self, *args, **kwargs):
        if self.session_id == _WARM_SPARE_ID and not entered.is_set():
            entered.set()
            await release.wait()  # hold the spare in flight, worker already spawned
        return await real_eval(self, *args, **kwargs)

    monkeypatch.setattr(SageSession, "shutdown", tracked_shutdown)
    monkeypatch.setattr(SageSession, "evaluate", blocking_eval)
    try:
        manager._schedule_warm_refill()
        await asyncio.wait_for(entered.wait(), 3)
        assert len(manager._warm_in_flight) == 1
        spare = next(iter(manager._warm_in_flight))

        release.set()  # let cancellation win the race either way
        await manager.shutdown()

        assert spare in shut_down, "the in-flight spare's worker leaked on shutdown"
        assert not spare.is_alive()
    finally:
        release.set()


async def test_warm_up_respects_the_session_ceiling():
    """warm_up never fills the pool past max_sessions, even when the configured
    pool size is larger -- spares count against the same ceiling as live workers.
    """
    manager = SageSessionManager(_settings(max_sessions=1, warm_pool_size=3))
    try:
        await manager.warm_up()
        assert len(manager._warm_pool) == 1
    finally:
        await manager.shutdown()


async def test_reclaim_awaits_the_worker_exit_before_reusing_the_slot(monkeypatch):
    """Capacity reclamation must not release a slot until the spare's worker has
    actually exited (external review, round 3). Previously get() cancelled the
    refill and dropped the spare from tracking without awaiting its shutdown, so
    the replacement could start while the cancelled worker was still alive --
    three live processes for a ceiling of two.
    """
    manager = SageSessionManager(_settings(max_sessions=2, warm_pool_size=1))
    await manager.warm_up()  # W0 pooled (unpatched, so its warm eval completed)

    entered = asyncio.Event()
    real_eval = SageSession.evaluate

    async def blocking_eval(self, *args, **kwargs):
        # Hold the *refill* spare alive, mid warm-up, when B arrives.
        if self.session_id == _WARM_SPARE_ID and not entered.is_set():
            entered.set()
            await asyncio.Event().wait()  # until cancelled by the reclaim
        return await real_eval(self, *args, **kwargs)

    monkeypatch.setattr(SageSession, "evaluate", blocking_eval)
    try:
        await manager.get("A")  # adopts W0, schedules the refill for W1
        await asyncio.wait_for(entered.wait(), 3)  # W1 spawned and alive, blocked
        assert len(manager._warm_in_flight) == 1
        spare = next(iter(manager._warm_in_flight))
        assert spare.is_alive()

        await manager.get("B")  # must reclaim W1 (await its exit) before creating B

        assert not spare.is_alive(), "reclaimed worker still alive after the slot was reused"
        assert not manager._warm_in_flight
        assert not manager._warm_tasks
        live = [s for s in manager._sessions.values() if s.is_alive()]
        assert len(live) <= 2
    finally:
        await manager.shutdown()


async def test_cancelling_the_reclaimer_mid_cleanup_does_not_overshoot(monkeypatch):
    """Cancellation of the reclaiming waiter (external review, round 4).

    B triggers reclamation of an in-flight spare and is cancelled while that
    spare is still shutting down; C then asks for a workspace. Reclamation is
    manager-owned and its reservation is held (counted) until the process exits,
    so C waits for the freed slot instead of overshooting the ceiling.
    """
    manager = SageSessionManager(_settings(max_sessions=2, warm_pool_size=1))
    warming = asyncio.Event()
    shutting = asyncio.Event()
    release_shutdown = asyncio.Event()
    real_eval = SageSession.evaluate
    real_shutdown = SageSession.shutdown

    async def blocking_eval(self, *args, **kwargs):
        if self.session_id == _WARM_SPARE_ID and not warming.is_set():
            warming.set()
            await asyncio.Event().wait()  # hold the refill spare warming until reclaimed
        return await real_eval(self, *args, **kwargs)

    async def blocking_shutdown(self):
        if self.session_id == _WARM_SPARE_ID and not release_shutdown.is_set():
            shutting.set()
            await release_shutdown.wait()  # hold the reclamation mid-cleanup
        return await real_shutdown(self)

    try:
        await manager.warm_up()  # W0 pooled (unpatched, so its warm-up completes)
        # Patch AFTER warm_up so only the *refill* spare (W1) blocks.
        monkeypatch.setattr(SageSession, "evaluate", blocking_eval)
        monkeypatch.setattr(SageSession, "shutdown", blocking_shutdown)

        await manager.get("A")  # adopts W0, schedules W1 (its warm eval blocks)
        await asyncio.wait_for(warming.wait(), 3)
        assert len(manager._warm_in_flight) == 1
        w1 = next(iter(manager._warm_in_flight))

        # B reclaims W1; cancel B while W1's shutdown (the cleanup) is blocked.
        b = asyncio.create_task(manager.get("B"))
        await asyncio.wait_for(shutting.wait(), 3)
        b.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await b

        # C must wait for the manager-owned reclamation, not start a third worker.
        c = asyncio.create_task(manager.get("C"))
        await asyncio.sleep(0.1)
        assert not c.done(), "C proceeded before the reclaimed worker's slot was freed"
        release_shutdown.set()
        await asyncio.wait_for(c, 5)

        assert not w1.is_alive(), "the reclaimed worker survived a cancelled reclaimer"
        assert not manager._warm_in_flight
        live = [s for s in manager._sessions.values() if s.is_alive()]
        assert len(live) <= 2, f"overshoot: {len(live)} live workers for a ceiling of 2"
    finally:
        release_shutdown.set()
        await manager.shutdown()


async def test_shutdown_awaits_an_in_flight_reclamation(monkeypatch):
    """Shutdown must not return while a manager-owned reclamation is still tearing
    a worker down (external review, round 4).

    A refill's reclaimer is cancelled mid-cleanup, leaving the shutdown of its
    worker owned by ``_reclaim_tasks``. ``manager.shutdown()`` has to await that
    cleanup so it does not return over a still-live worker.
    """
    manager = SageSessionManager(_settings(max_sessions=2, warm_pool_size=1))
    warming = asyncio.Event()
    shutting = asyncio.Event()
    release_shutdown = asyncio.Event()
    real_eval = SageSession.evaluate
    real_shutdown = SageSession.shutdown

    async def blocking_eval(self, *args, **kwargs):
        if self.session_id == _WARM_SPARE_ID and not warming.is_set():
            warming.set()
            await asyncio.Event().wait()
        return await real_eval(self, *args, **kwargs)

    async def blocking_shutdown(self):
        if self.session_id == _WARM_SPARE_ID and not release_shutdown.is_set():
            shutting.set()
            await release_shutdown.wait()
        return await real_shutdown(self)

    try:
        await manager.warm_up()
        monkeypatch.setattr(SageSession, "evaluate", blocking_eval)
        monkeypatch.setattr(SageSession, "shutdown", blocking_shutdown)

        await manager.get("A")  # schedules the refill whose warm eval blocks
        await asyncio.wait_for(warming.wait(), 3)
        w1 = next(iter(manager._warm_in_flight))

        b = asyncio.create_task(manager.get("B"))  # reclaims the refill
        await asyncio.wait_for(shutting.wait(), 3)
        b.cancel()  # reclamation becomes manager-owned, still mid-cleanup
        with contextlib.suppress(asyncio.CancelledError):
            await b
        assert manager._reclaim_tasks

        sd = asyncio.create_task(manager.shutdown())
        await asyncio.sleep(0.1)
        assert not sd.done(), "shutdown returned while a reclamation was still in flight"
        release_shutdown.set()
        await asyncio.wait_for(sd, 5)

        assert not w1.is_alive()
        assert not manager._reclaim_tasks
    finally:
        release_shutdown.set()
        await manager.shutdown()
