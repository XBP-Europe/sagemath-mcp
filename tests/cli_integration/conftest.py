"""Pytest fixtures for CLI integration tests."""

from __future__ import annotations

import shutil

import pytest

from .cli_config import (
    ensure_docker_container,
    setup_claude_mcp_config,
    setup_gemini_mcp_config,
)


def _has_cli(name: str) -> bool:
    return shutil.which(name) is not None


@pytest.fixture(scope="session")
def docker_sage():
    """Ensure the sage-mcp Docker container is running for the test session."""
    ensure_docker_container()


@pytest.fixture(scope="session")
def claude_config(docker_sage):
    """Configure Claude Code CLI with sagemath MCP server, restore after."""
    if not _has_cli("claude"):
        pytest.skip("claude CLI not found on PATH")
    restore = setup_claude_mcp_config()
    yield
    restore()


@pytest.fixture(scope="session")
def gemini_config(docker_sage):
    """Configure Gemini CLI with sagemath MCP server, restore after."""
    if not _has_cli("gemini"):
        pytest.skip("gemini CLI not found on PATH")
    restore = setup_gemini_mcp_config()
    yield
    restore()
