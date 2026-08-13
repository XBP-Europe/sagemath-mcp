"""Process-wide runtime state: the settings and the session manager.

This lives apart from ``server`` so tool modules can reach the session manager
without importing the module that imports them. Everything refers to
``runtime.SESSION_MANAGER`` by attribute rather than binding it at import time,
which is what lets a test swap the manager for a pure-Python one.
"""

from __future__ import annotations

from .config import DEFAULT_SETTINGS, SageSettings
from .session import SageSessionManager

SETTINGS: SageSettings = DEFAULT_SETTINGS
SESSION_MANAGER = SageSessionManager(SETTINGS)


def get_session_manager() -> SageSessionManager:
    """The live session manager.

    Always read through this (or ``runtime.SESSION_MANAGER``) rather than
    importing the object itself: a module-level ``from .runtime import
    SESSION_MANAGER`` binds the manager that existed at import time, and a test
    that replaces it would silently be running against the real one.
    """
    return SESSION_MANAGER


async def resolve_session(client_session_id: str, name: str):
    """Look up (or start) the worker for one client's named workspace.

    Every worker-backed tool needs this pair of calls, and spelling it out at
    each of the ~30 sites is what made the lines unwieldy once the manager moved
    out of ``server``. Reading the manager here also keeps the lookup late-bound.
    """
    manager = get_session_manager()
    return await manager.get(manager.key_for(client_session_id, name))
