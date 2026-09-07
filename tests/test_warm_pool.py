"""The pre-warmed spare-worker pool.

A worker pays a multi-second `from sage.all import *` on spawn, so without a
pool every new session's first call is slow. The manager keeps a small pool of
spares (Sage already loaded, no client identity yet); a new session adopts one
and the pool refills in the background. These tests use the pure-Python worker,
so "warm" is fast, but the pool mechanics are the same.
"""

from __future__ import annotations

import asyncio

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

    async def never_finishes():
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

        async def blocking_spawn():
            started.set()
            await release.wait()
            return await real_spawn()

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
