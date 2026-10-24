"""Every `uvx` launcher must ask for the Python the [passagemath] extra is tested on.

The extra is tested on one Python: the `passagemath` CI lane's. A launcher that
names no Python gets uv's choice instead, which is its own newest -- 3.15 at
the time of writing -- and passagemath's dependencies have no wheels there.
`memory-allocator` 0.1.4 has none past cp312 at all. uv ignores the upper bound
in passagemath's `requires-python`, so it resolves anyway, then tries to compile,
and on a machine without a C compiler the install fails. Measured on 0.9.6 in
a container with no Python and no compiler: the published launcher failed,
the same launcher with `--python 3.12` installed 191 wheels and started.

Each test reads one place a client takes its install command from and checks
it passes `--python` with the lane's version, so moving the lane moves every
launcher or fails here.
"""

from __future__ import annotations

import base64
import json
import re
import tomllib
import urllib.parse
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
EXTRA = "sagemath-mcp[passagemath]"


def _lane_python() -> str:
    """The Python the `passagemath` CI job installs the extra with."""
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))[
        "jobs"
    ]
    (version,) = [
        str(step["with"]["python-version"])
        for step in jobs["passagemath"]["steps"]
        if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ]
    assert re.fullmatch(r"3\.\d+", version), version
    return version


PYTHON = _lane_python()


def _assert_asks_for_the_lane_python(args: list[str], where: str) -> None:
    assert "--from" in args, f"{where}: no --from, so not a launcher this file understands"
    assert "--python" in args, f"{where}: names no Python, so uv picks its newest"
    position = args.index("--python")
    assert args[position + 1] == PYTHON, (
        f"{where}: asks for Python {args[position + 1]}, the passagemath lane runs {PYTHON}"
    )
    assert position < args.index("--from"), f"{where}: --python must come before --from"


def test_the_registry_entry_asks_for_the_lane_python() -> None:
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    (package,) = [p for p in server["packages"] if p["registryType"] == "pypi"]
    args: list[str] = []
    for argument in package["runtimeArguments"]:
        args += [argument["name"], argument["value"]]
    _assert_asks_for_the_lane_python(args, "server.json")


@pytest.mark.parametrize(
    "manifest",
    ["packaging/claude-plugin/.claude-plugin/plugin.json", "gemini-extension.json"],
)
def test_the_client_manifests_ask_for_the_lane_python(manifest: str) -> None:
    config = json.loads((ROOT / manifest).read_text(encoding="utf-8"))
    (server,) = config["mcpServers"].values()
    assert server["command"] == "uvx"
    _assert_asks_for_the_lane_python(server["args"], manifest)


def test_the_readme_install_buttons_ask_for_the_lane_python() -> None:
    """The buttons carry their config encoded in the link, where a text search
    for `uvx` cannot see it: VS Code's twice URL-encoded, Cursor's in base64."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    vscode = re.search(r"\(https://insiders\.vscode\.dev/redirect\?url=([^)]+)\)", readme)
    cursor = re.search(r"\(https://cursor\.com/en/install-mcp\?[^)]*config=([^)&]+)\)", readme)
    assert vscode and cursor, "an install button is gone; update this test with it"
    inner = urllib.parse.unquote(vscode.group(1))
    vscode_config = json.loads(urllib.parse.unquote(inner.split("?", 1)[1]))
    cursor_config = json.loads(base64.b64decode(cursor.group(1)))
    for name, config in (("VS Code", vscode_config), ("Cursor", cursor_config)):
        assert config["command"] == "uvx"
        _assert_asks_for_the_lane_python(config["args"], f"the README's {name} button")


@pytest.mark.parametrize(
    "document", ["README.md", "USAGE.md", "INSTALLATION.md", "DISTRIBUTION.md"]
)
def test_every_documented_uvx_command_asks_for_the_lane_python(document: str) -> None:
    text = (ROOT / document).read_text(encoding="utf-8")
    commands = re.findall(r"uvx [^`\n]*" + re.escape(EXTRA), text)
    assert commands, f"{document} shows no uvx command; drop it from this list"
    for command in commands:
        args = command.replace("=", " ").replace('"', "").split()
        _assert_asks_for_the_lane_python(args, f"{document}: {command!r}")


def test_the_desktop_bundle_caps_python_at_the_lane_python() -> None:
    """The bundle is not launched by `uvx`: the host runs `uv run` on its
    pyproject, and uv picks an interpreter inside `requires-python`. A floor
    alone lets it pick the newest."""
    bundle = tomllib.loads(
        (ROOT / "packaging" / "mcpb" / "pyproject.toml").read_text(encoding="utf-8")
    )
    major, minor = PYTHON.split(".")
    assert bundle["project"]["requires-python"] == f">={PYTHON},<{major}.{int(minor) + 1}"
