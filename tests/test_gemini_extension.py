"""The Gemini CLI extension must install the server the CLI will actually run.

`gemini extensions install <github url>` reads `gemini-extension.json` from the
repository root, so this file is a published interface: a mistake in it fails at
someone else's install, not in CI. `gemini extensions validate` checks the
schema; these checks cover what a schema cannot.

Unlike the MCPB bundle, there is nothing to pack -- the repository *is* the
extension -- which is why the manifest lives at the root rather than under
`packaging/`.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "gemini-extension.json").read_text(encoding="utf-8"))
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
SERVERS = MANIFEST["mcpServers"]


def test_the_manifest_declares_one_server_by_the_project_name() -> None:
    assert MANIFEST["name"] == "sagemath"
    assert list(SERVERS) == ["sagemath"], SERVERS
    assert MANIFEST["description"]


def test_the_extension_installs_a_sage_runtime_with_the_server() -> None:
    """The same reasoning as the MCPB bundle: a server with no Sage behind it
    starts cleanly and then refuses every evaluation."""
    args = SERVERS["sagemath"]["args"]
    assert SERVERS["sagemath"]["command"] == "uvx"
    spec = args[args.index("--from") + 1]
    assert spec.startswith("sagemath-mcp[passagemath]=="), spec
    # The console script, not a module path: `uvx --from <spec> <command>`.
    assert args[-1] == "sagemath-mcp"
    assert "sagemath-mcp" in PYPROJECT["project"]["scripts"]


def test_the_pinned_version_matches_the_project() -> None:
    """An extension is installed from a git ref, so its pin has to be the
    version at that ref; `scripts/bump_version.py` moves it."""
    args = SERVERS["sagemath"]["args"]
    spec = args[args.index("--from") + 1]
    assert spec.endswith("==" + PYPROJECT["project"]["version"]), spec
    assert MANIFEST["version"] == PYPROJECT["project"]["version"]
