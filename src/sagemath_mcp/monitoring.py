"""Lightweight evaluation metrics for the Sage MCP server."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class EvaluationMetrics:
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    security_failures: int = 0
    total_elapsed_ms: float = 0.0
    max_elapsed_ms: float = 0.0
    last_run_at: float | None = None
    last_error: str | None = None
    last_security_violation: str | None = None
    last_error_details: str | None = None

    def snapshot(self) -> dict:
        # NOTE: Average latency is computed lazily so it never divides by zero.
        avg_elapsed = self.total_elapsed_ms / self.successes if self.successes else 0.0
        return {
            "attempts": self.attempts,
            "successes": self.successes,
            "failures": self.failures,
            "security_failures": self.security_failures,
            "avg_elapsed_ms": avg_elapsed,
            "max_elapsed_ms": self.max_elapsed_ms,
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "last_security_violation": self.last_security_violation,
            "last_error_details": self.last_error_details,
        }

    def reset(self) -> None:
        self.attempts = 0
        self.successes = 0
        self.failures = 0
        self.security_failures = 0
        self.total_elapsed_ms = 0.0
        self.max_elapsed_ms = 0.0
        self.last_run_at = None
        self.last_error = None
        self.last_security_violation = None
        self.last_error_details = None


_METRICS = EvaluationMetrics()
_LOCK = threading.Lock()


def record_success(elapsed_ms: float) -> None:
    now = time.time()
    with _LOCK:
        _METRICS.attempts += 1
        _METRICS.successes += 1
        _METRICS.total_elapsed_ms += float(elapsed_ms)
        if elapsed_ms > _METRICS.max_elapsed_ms:
            _METRICS.max_elapsed_ms = float(elapsed_ms)
        _METRICS.last_run_at = now


def record_failure(message: str, *, is_security: bool = False, details: str | None = None) -> None:
    now = time.time()
    with _LOCK:
        _METRICS.attempts += 1
        _METRICS.failures += 1
        _METRICS.last_run_at = now
        _METRICS.last_error = message
        if is_security:
            _METRICS.security_failures += 1
            _METRICS.last_security_violation = message
        _METRICS.last_error_details = details or message


def snapshot() -> dict:
    with _LOCK:
        return _METRICS.snapshot()


# The free-text fields carry the message, rejected code and (untruncated) stdout
# of a *single* client's most recent failing evaluation. `_METRICS` is a
# process-global singleton, so any client that reads it sees another client's
# data. They are recorded for server-side logs but must never leave the process
# through the monitoring resource, which is unscoped and, on the shipped HTTP
# deployment, readable by any client. See REVIEW_ACTIONS item 58.
_CLIENT_TEXT_FIELDS = ("last_error", "last_security_violation", "last_error_details")


def public_snapshot() -> dict:
    """Snapshot with the per-client free-text fields removed.

    The aggregate counters and latencies are process-wide totals and disclose
    nothing about any one client, so they stay. Everything a caller could mine
    for another client's inputs or outputs is dropped here rather than at the
    resource, so the redaction travels with the data.
    """
    data = snapshot()
    for field in _CLIENT_TEXT_FIELDS:
        data.pop(field, None)
    return data


def reset_metrics() -> None:
    with _LOCK:
        _METRICS.reset()
