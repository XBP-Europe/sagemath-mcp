"""Run all 44 test cases against Claude Code CLI."""

from __future__ import annotations

import subprocess

import pytest

from .runner import run_claude
from .test_cases import ALL_TEST_CASES
from .validate import validate


@pytest.mark.parametrize("case", ALL_TEST_CASES, ids=lambda c: c.id)
def test_claude(claude_config, case):
    try:
        output, elapsed = run_claude(case.prompt, timeout=case.timeout_seconds)
    except subprocess.TimeoutExpired:
        pytest.fail(f"[{case.id}] TIMEOUT after {case.timeout_seconds}s")
    except RuntimeError as exc:
        pytest.skip(str(exc))

    result = validate(output, case, elapsed)

    if result.status in ("PASS", "SOFT_PASS"):
        return
    if result.status == "ERROR":
        pytest.fail(
            f"[{case.id}] MCP ERROR ({result.elapsed_seconds:.1f}s): "
            f"{result.response_excerpt}"
        )
    pytest.fail(
        f"[{case.id}] {result.status} ({result.elapsed_seconds:.1f}s): "
        f"{result.response_excerpt}"
    )
