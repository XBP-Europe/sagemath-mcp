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


def run_claude(
    prompt: str, timeout: int = DEFAULT_TIMEOUT, allowed_tools: str | None = None
) -> tuple[str, float]:
    """Run ``claude --print "<prompt>"`` and return (output, elapsed_seconds).

    The working directory is set to the project root so that project-level
    ``.claude/settings.local.json`` is picked up automatically.
    """
    cli = _find_cli("claude")
    if cli is None:
        raise RuntimeError("claude CLI not found on PATH")

    argv = [cli, "--print", prompt]
    if allowed_tools:
        # Without this the run is non-interactive and MCP calls are declined.
        argv += ["--allowedTools", allowed_tools]
    start = time.monotonic()
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
    )
    elapsed = time.monotonic() - start
    output = result.stdout + result.stderr
    return output, elapsed


def run_gemini(
    prompt: str, timeout: int = DEFAULT_TIMEOUT, auto_approve: bool = False
) -> tuple[str, float]:
    """Run ``gemini -p "<prompt>"`` and return (output, elapsed_seconds).

    ``auto_approve`` passes --yolo; without it tool calls wait for a prompt that
    never comes in a non-interactive run.
    """
    cli = _find_cli("gemini")
    if cli is None:
        raise RuntimeError("gemini CLI not found on PATH")

    argv = [cli, "-p", prompt]
    if auto_approve:
        argv.append("--yolo")
    start = time.monotonic()
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
    )
    elapsed = time.monotonic() - start
    output = result.stdout + result.stderr
    return output, elapsed


def run_codex(prompt: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[str, float]:
    """Run ``codex exec "<prompt>"`` and return (output, elapsed_seconds).

    ``--skip-git-repo-check`` keeps the run non-interactive; without it Codex
    refuses to execute in some working directories.
    """
    cli = _find_cli("codex")
    if cli is None:
        raise RuntimeError("codex CLI not found on PATH")

    start = time.monotonic()
    result = subprocess.run(
        [cli, "exec", "--skip-git-repo-check", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
    )
    elapsed = time.monotonic() - start
    return result.stdout + result.stderr, elapsed


RUNNERS = {
    "claude": run_claude,
    "gemini": run_gemini,
    "codex": run_codex,
}
