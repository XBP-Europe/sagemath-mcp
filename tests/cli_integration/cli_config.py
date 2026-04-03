"""Setup and teardown MCP server configuration for Claude and Gemini CLIs."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# The stdio command that both CLIs use to spawn the MCP server.
# Uses Docker exec to get a real Sage runtime.
MCP_STDIO_COMMAND = "docker"
MCP_STDIO_ARGS = [
    "exec", "-i", "sage-mcp",
    "sage", "-python", "-m", "sagemath_mcp.server",
]

# Fallback: use uv if Docker is not available (pure-Python, no real Sage)
MCP_STDIO_COMMAND_LOCAL = "uv"
MCP_STDIO_ARGS_LOCAL = ["run", "sagemath-mcp"]


def _docker_container_running() -> bool:
    """Check if the sage-mcp Docker container is running."""
    result = subprocess.run(
        ["docker", "ps", "--filter", "name=sage-mcp", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    return "sage-mcp" in result.stdout


def ensure_docker_container(timeout: int = 10) -> None:
    """Ensure the sage-mcp Docker container is running.

    Starts it via ``docker-compose up -d`` if needed and waits for readiness.
    Raises RuntimeError if the container does not start in *timeout* seconds.
    """
    if _docker_container_running():
        return

    try:
        subprocess.run(
            ["docker-compose", "up", "-d"],
            cwd=str(PROJECT_ROOT),
            check=True,
            capture_output=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise RuntimeError(f"docker-compose up failed: {exc}") from exc

    # Wait for the container to be ready
    for _ in range(min(timeout, 30)):
        if _docker_container_running():
            return
        time.sleep(1)
    raise RuntimeError(f"sage-mcp container did not start within {timeout}s")


def _get_mcp_server_config() -> dict:
    """Return the MCP server config dict based on what's available."""
    if _docker_container_running():
        return {
            "command": MCP_STDIO_COMMAND,
            "args": MCP_STDIO_ARGS,
        }
    return {
        "command": MCP_STDIO_COMMAND_LOCAL,
        "args": MCP_STDIO_ARGS_LOCAL,
    }


# ---------------------------------------------------------------------------
# Claude Code CLI configuration
# ---------------------------------------------------------------------------

# Claude Code reads MCP servers from .mcp.json (project-level) or
# ~/.claude.json (local). We use .mcp.json so `claude --print` in this
# project directory picks it up.
CLAUDE_MCP_PATH = PROJECT_ROOT / ".mcp.json"
CLAUDE_MCP_BACKUP = PROJECT_ROOT / ".mcp.json.bak"
CLAUDE_SETTINGS_PATH = PROJECT_ROOT / ".claude" / "settings.local.json"
CLAUDE_SETTINGS_BACKUP = PROJECT_ROOT / ".claude" / "settings.local.json.bak"

# All sagemath MCP tool names that need to be pre-approved for --print mode.
_MCP_TOOL_PERMISSIONS = [
    "mcp__sagemath__evaluate_sage",
    "mcp__sagemath__calculate_expression",
    "mcp__sagemath__solve_equation",
    "mcp__sagemath__differentiate_expression",
    "mcp__sagemath__integrate_expression",
    "mcp__sagemath__simplify_expression",
    "mcp__sagemath__expand_expression",
    "mcp__sagemath__factor_expression",
    "mcp__sagemath__limit_expression",
    "mcp__sagemath__series_expansion",
    "mcp__sagemath__matrix_multiply",
    "mcp__sagemath__matrix_operation",
    "mcp__sagemath__solve_ode",
    "mcp__sagemath__number_theory_operation",
    "mcp__sagemath__statistics_summary",
    "mcp__sagemath__plot_expression",
    "mcp__sagemath__reset_sage_session",
    "mcp__sagemath__cancel_sage_session",
]


def setup_claude_mcp_config() -> callable:
    """Add sagemath MCP server to .mcp.json and pre-approve tool permissions.

    Returns a callable that restores the original files.
    """
    # --- .mcp.json: register the MCP server ---
    mcp_existing = {}
    if CLAUDE_MCP_PATH.exists():
        mcp_existing = json.loads(CLAUDE_MCP_PATH.read_text())
        shutil.copy2(CLAUDE_MCP_PATH, CLAUDE_MCP_BACKUP)

    mcp_settings = dict(mcp_existing)
    mcp_servers = mcp_settings.get("mcpServers", {})
    server_config = _get_mcp_server_config()
    mcp_servers["sagemath"] = {"type": "stdio", **server_config}
    mcp_settings["mcpServers"] = mcp_servers
    CLAUDE_MCP_PATH.write_text(json.dumps(mcp_settings, indent=2) + "\n")

    # --- settings.local.json: pre-approve all tool permissions ---
    settings_existing = {}
    if CLAUDE_SETTINGS_PATH.exists():
        settings_existing = json.loads(CLAUDE_SETTINGS_PATH.read_text())
        shutil.copy2(CLAUDE_SETTINGS_PATH, CLAUDE_SETTINGS_BACKUP)

    settings = dict(settings_existing)
    permissions = settings.get("permissions", {})
    allow_list = list(permissions.get("allow", []))
    for tool in _MCP_TOOL_PERMISSIONS:
        if tool not in allow_list:
            allow_list.append(tool)
    permissions["allow"] = allow_list
    settings["permissions"] = permissions

    CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")

    def restore():
        # Restore .mcp.json
        if CLAUDE_MCP_BACKUP.exists():
            shutil.move(str(CLAUDE_MCP_BACKUP), str(CLAUDE_MCP_PATH))
        else:
            CLAUDE_MCP_PATH.unlink(missing_ok=True)
        # Restore settings.local.json
        if CLAUDE_SETTINGS_BACKUP.exists():
            shutil.move(str(CLAUDE_SETTINGS_BACKUP), str(CLAUDE_SETTINGS_PATH))

    return restore


# ---------------------------------------------------------------------------
# Gemini CLI configuration
# ---------------------------------------------------------------------------


def setup_gemini_mcp_config() -> callable:
    """Register sagemath MCP server with Gemini CLI.

    Returns a callable that removes the registration.
    """
    config = _get_mcp_server_config()
    cmd = [config["command"]] + config["args"]

    subprocess.run(
        ["gemini", "mcp", "add", "--trust", "sagemath", "--", *cmd],
        capture_output=True,
        text=True,
    )

    def restore():
        subprocess.run(
            ["gemini", "mcp", "remove", "sagemath"],
            capture_output=True,
            text=True,
        )

    return restore
