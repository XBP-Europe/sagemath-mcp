"""Configuration primitives for the SageMath MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields


def _float_from_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid float for {name}: {raw}") from exc


def _int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid int for {name}: {raw}") from exc


def _bool_from_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class SageSettings:
    """Runtime settings for Sage session management."""

    sage_binary: str = "sage"
    startup_code: str = "from sage.all import *"
    eval_timeout: float = 30.0
    idle_ttl: float = 900.0
    shutdown_grace: float = 2.0
    max_stdout_chars: int = 100_000
    # Ceiling on concurrently live sessions (workers), 0 meaning unbounded.
    # Each session is a Sage subprocess holding real memory, so an unbounded
    # map is a way for one client -- opening a fresh named workspace per call --
    # to exhaust the host a worker at a time. Generous by default: local single
    # -client use never approaches it, and a shared deployment lowers it.
    max_sessions: int = 128
    # Spare workers kept warm (Sage preloaded) so a new session's first call does
    # not pay the ~2s `from sage.all import *`. 0 disables it. Each spare is an
    # idle Sage process holding memory, so this is a small pool by default; the
    # pool is filled at server startup and topped up in the background as spares
    # are adopted, never above `max_sessions`.
    warm_pool_size: int = 1
    force_python_worker: bool = False
    persist_sessions: bool = False
    persist_dir: str = ""

    @classmethod
    def from_env(cls) -> SageSettings:
        defaults = {field.name: field.default for field in fields(cls)}
        return cls(
            sage_binary=os.getenv("SAGEMATH_MCP_SAGE_BINARY", defaults["sage_binary"]),
            startup_code=os.getenv("SAGEMATH_MCP_STARTUP", defaults["startup_code"]),
            eval_timeout=_float_from_env("SAGEMATH_MCP_EVAL_TIMEOUT", defaults["eval_timeout"]),
            idle_ttl=_float_from_env("SAGEMATH_MCP_IDLE_TTL", defaults["idle_ttl"]),
            shutdown_grace=_float_from_env(
                "SAGEMATH_MCP_SHUTDOWN_GRACE", defaults["shutdown_grace"]
            ),
            max_stdout_chars=_int_from_env(
                "SAGEMATH_MCP_MAX_STDOUT", defaults["max_stdout_chars"]
            ),
            max_sessions=_int_from_env(
                "SAGEMATH_MCP_MAX_SESSIONS", defaults["max_sessions"]
            ),
            warm_pool_size=_int_from_env(
                "SAGEMATH_MCP_WARM_POOL_SIZE", defaults["warm_pool_size"]
            ),
            force_python_worker=_bool_from_env(
                "SAGEMATH_MCP_FORCE_PYTHON_WORKER", defaults["force_python_worker"]
            ),
            persist_sessions=_bool_from_env(
                "SAGEMATH_MCP_PERSIST_SESSIONS", defaults["persist_sessions"]
            ),
            persist_dir=os.getenv(
                "SAGEMATH_MCP_PERSIST_DIR", defaults["persist_dir"]
            ),
        )


DEFAULT_SETTINGS = SageSettings.from_env()
