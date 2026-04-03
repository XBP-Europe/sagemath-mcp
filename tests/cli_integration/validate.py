"""Multi-tier validation for non-deterministic LLM output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .test_cases import MathTestCase

Status = Literal["PASS", "FAIL", "ERROR", "SOFT_PASS", "TIMEOUT", "SKIP"]

ERROR_INDICATORS = [
    "i don't have access",
    "i can't",
    "i cannot",
    "tool failed",
    "connection refused",
    "mcp server",
    "no tools available",
    "unable to connect",
]


@dataclass
class ValidationResult:
    status: Status
    matched_substring: str | None
    response_excerpt: str
    elapsed_seconds: float


def _extract_numbers(text: str) -> set[str]:
    """Extract all numeric strings from text."""
    return set(re.findall(r"-?\d+\.?\d*", text))


def validate(output: str, case: MathTestCase, elapsed: float) -> ValidationResult:
    """Validate LLM output against a test case."""
    excerpt = output[:500] if output else "(empty output)"
    lower = output.lower()

    # Check negative substrings (must NOT appear)
    for neg in case.negative_substrings:
        if neg.lower() in lower:
            return ValidationResult(
                status="FAIL",
                matched_substring=None,
                response_excerpt=excerpt,
                elapsed_seconds=elapsed,
            )

    # Primary: substring match (case-insensitive) — check before error indicators
    # so that a correct answer mentioning "MCP server" isn't wrongly flagged.
    for expected in case.expected_substrings:
        if expected.lower() in lower:
            return ValidationResult(
                status="PASS",
                matched_substring=expected,
                response_excerpt=excerpt,
                elapsed_seconds=elapsed,
            )

    # Secondary: numeric extraction
    numbers_in_output = _extract_numbers(output)
    for expected in case.expected_substrings:
        if expected in numbers_in_output:
            return ValidationResult(
                status="PASS",
                matched_substring=expected,
                response_excerpt=excerpt,
                elapsed_seconds=elapsed,
            )

    # Check for MCP connection / tool access errors (after content checks so
    # that a correct answer that happens to mention these phrases still passes).
    for indicator in ERROR_INDICATORS:
        if indicator in lower:
            return ValidationResult(
                status="ERROR",
                matched_substring=None,
                response_excerpt=excerpt,
                elapsed_seconds=elapsed,
            )

    # Soft-fail for session management tests
    if case.soft_fail_ok:
        return ValidationResult(
            status="SOFT_PASS",
            matched_substring=None,
            response_excerpt=excerpt,
            elapsed_seconds=elapsed,
        )

    return ValidationResult(
        status="FAIL",
        matched_substring=None,
        response_excerpt=excerpt,
        elapsed_seconds=elapsed,
    )
