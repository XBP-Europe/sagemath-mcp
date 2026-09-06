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
