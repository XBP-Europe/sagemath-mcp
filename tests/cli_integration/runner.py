"""Invoke Claude Code CLI and Gemini CLI with prompts, capture output."""

from __future__ import annotations

import json
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
    prompt: str,
    timeout: int = DEFAULT_TIMEOUT,
    allowed_tools: str | None = None,
    no_tools: bool = False,
) -> tuple[str, float]:
    """Run ``claude --print "<prompt>"`` and return (output, elapsed_seconds).

    The working directory is set to the project root so that project-level
    ``.claude/settings.local.json`` is picked up automatically -- which is also
    why ``no_tools`` exists: that file pre-approves ``Bash(python3:*)`` and the
    like for the harness, so a "reasoning only" run would otherwise be free to
    compute in a shell. ``--tools ""`` removes every built-in tool (the init
    event then reports ``tools: []``); the prompt goes in on stdin because the
    variadic ``--tools`` would swallow a positional prompt.
    """
    cli = _find_cli("claude")
    if cli is None:
        raise RuntimeError("claude CLI not found on PATH")

    argv = [cli, "--print"]
    stdin_text: str | None = None
    if no_tools:
        argv += ["--tools", ""]
        stdin_text = prompt
    else:
        argv.append(prompt)
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
        input=stdin_text,
        stdin=None if stdin_text is not None else subprocess.DEVNULL,
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


def run_gemini_observed(
    prompt: str, timeout: int = DEFAULT_TIMEOUT
) -> tuple[str, float, list[str]]:
    """``gemini -p ... -o json`` without ``--yolo``: the answer plus the names of
    every tool Gemini called, from the run's own statistics.

    Without --yolo a tool call needs an approval nobody gives in a headless
    run, so this is close to enforcement; the statistics make it verifiable
    rather than assumed (``stats.tools.byName`` lists what was attempted).
    """
    cli = _find_cli("gemini")
    if cli is None:
        raise RuntimeError("gemini CLI not found on PATH")

    start = time.monotonic()
    result = subprocess.run(
        [cli, "-p", prompt, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
    )
    elapsed = time.monotonic() - start
    raw = result.stdout
    begin = raw.find("{")
    try:
        data = json.loads(raw[begin:]) if begin >= 0 else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    by_name = ((data.get("stats") or {}).get("tools") or {}).get("byName") or {}
    calls: list[str] = []
    for name, info in by_name.items():
        count = info.get("count", 1) if isinstance(info, dict) else 1
        calls.extend([str(name)] * max(int(count), 1))
    output = str(data.get("response", "")) if data else raw + result.stderr
    return output, elapsed, calls


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


def run_codex_observed(
    prompt: str, timeout: int = DEFAULT_TIMEOUT
) -> tuple[str, float, list[str]]:
    """``codex exec --json``: the final answer plus every shell command Codex ran.

    Codex cannot be told to have no shell -- its sandbox governs *what* a
    command may touch, not whether one runs -- so a "reasoning only" arm can
    only be an instruction to the model. This makes compliance observable: the
    JSON event stream carries a ``command_execution`` item for every command,
    and the caller records them as tool traffic the arm did not expect.
    """
    cli = _find_cli("codex")
    if cli is None:
        raise RuntimeError("codex CLI not found on PATH")

    start = time.monotonic()
    result = subprocess.run(
        [cli, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--json", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
    )
    elapsed = time.monotonic() - start
    answers: list[str] = []
    commands: list[str] = []
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if not isinstance(item, dict):
            continue
        if item.get("type") == "command_execution":
            commands.append(str(item.get("command", ""))[:200])
        elif item.get("type") == "agent_message":
            answers.append(str(item.get("text", "")))
    output = "\n".join(answers) if answers else result.stdout + result.stderr
    return output, elapsed, commands


RUNNERS = {
    "claude": run_claude,
    "gemini": run_gemini,
    "codex": run_codex,
}
