"""Invoke Claude Code CLI and Gemini CLI with prompts, capture output."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Default timeout for a single LLM invocation (seconds).
DEFAULT_TIMEOUT = 120


def _find_cli(name: str) -> str | None:
    return shutil.which(name)


def run_claude(prompt: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[str, float]:
    """Run ``claude --print "<prompt>"`` and return (output, elapsed_seconds).

    The working directory is set to the project root so that project-level
    ``.claude/settings.local.json`` is picked up automatically.
    """
    cli = _find_cli("claude")
    if cli is None:
        raise RuntimeError("claude CLI not found on PATH")

    start = time.monotonic()
    result = subprocess.run(
        [cli, "--print", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
    )
    elapsed = time.monotonic() - start
    output = result.stdout + result.stderr
    return output, elapsed


def run_gemini(prompt: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[str, float]:
    """Run ``gemini -p "<prompt>"`` and return (output, elapsed_seconds)."""
    cli = _find_cli("gemini")
    if cli is None:
        raise RuntimeError("gemini CLI not found on PATH")

    start = time.monotonic()
    result = subprocess.run(
        [cli, "-p", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
    )
    elapsed = time.monotonic() - start
    output = result.stdout + result.stderr
    return output, elapsed
