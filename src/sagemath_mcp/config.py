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
    force_python_worker: bool = False

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
            force_python_worker=_bool_from_env(
                "SAGEMATH_MCP_FORCE_PYTHON_WORKER", defaults["force_python_worker"]
            ),
        )


DEFAULT_SETTINGS = SageSettings.from_env()
