"""The manifests that directories and registries read must describe a working install.

A registry or plugin catalog builds the user's install command from these files,
so a mistake here is not a cosmetic one: the registry entry once listed plain
`sagemath-mcp`, which installs a server with no Sage behind it -- every
evaluation then fails with "Unable to locate Sage executable". Each test below
pins one property a client relies on.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVER = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
PLUGIN_DIR = ROOT / "packaging" / "claude-plugin"
PLUGIN = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
MARKETPLACE = json.loads(
    (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
)


def _package(kind: str) -> dict:
    matches = [p for p in SERVER["packages"] if p["registryType"] == kind]
    assert len(matches) == 1, f"server.json should list exactly one {kind} package"
    return matches[0]


def test_the_registry_entry_installs_a_sage_runtime() -> None:
    package = _package("pypi")
    assert package["runtimeHint"] == "uvx"
    pins = [a["value"] for a in package["runtimeArguments"] if a.get("name") == "--from"]
    assert pins == [f"sagemath-mcp[passagemath]=={SERVER['version']}"], pins


def test_the_registered_image_proves_whose_it_is() -> None:
    """The registry rejects an OCI package whose image lacks this label."""
    image = _package("oci")["identifier"]
    assert image == f"ghcr.io/xbp-europe/sagemath-mcp:{SERVER['version']}"
    label = f'LABEL io.modelcontextprotocol.server.name="{SERVER["name"]}"'
    for dockerfile in ("Dockerfile", "Dockerfile.passagemath"):
        text = (ROOT / dockerfile).read_text(encoding="utf-8")
        assert label in text, f"{dockerfile} lacks the registry ownership label"


def test_the_registered_image_speaks_stdio() -> None:
    """The image defaults to HTTP; a registry client runs it with `docker run -i`."""
    package = _package("oci")
    assert package["transport"] == {"type": "stdio"}
    assert {"type": "named", "name": "--transport", "value": "stdio"}.items() <= (
        package["packageArguments"][0].items()
    )


def test_the_registry_publish_waits_for_the_image() -> None:
    """Publishing before the tag exists would fail the label check, and the release."""
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["mcp-registry"]
    assert {"publish", "docker"} <= set(job["needs"])
    assert "needs.docker.result == 'success'" in job["if"]


def test_the_claude_plugin_launches_a_pinned_release() -> None:
    """The Claude directory blocks an unpinned uvx launcher."""
    args = PLUGIN["mcpServers"]["sagemath"]["args"]
    assert PLUGIN["mcpServers"]["sagemath"]["command"] == "uvx"
    assert args[args.index("--from") + 1] == f"sagemath-mcp[passagemath]=={PLUGIN['version']}"
    assert PLUGIN["license"] == "MIT"


def test_the_marketplace_lists_the_plugin_it_ships() -> None:
    """A source path or a name that disagrees is the usual failed install."""
    (entry,) = MARKETPLACE["plugins"]
    assert entry["name"] == PLUGIN["name"]
    assert entry["source"].startswith("./") and ".." not in entry["source"]
    assert (ROOT / entry["source"] / ".claude-plugin" / "plugin.json").exists()


def test_the_plugin_readme_is_long_enough_to_list() -> None:
    """The directory blocks a README under 40 words, not counting code blocks."""
    readme = (PLUGIN_DIR / "README.md").read_text(encoding="utf-8")
    prose = re.sub(r"```.*?```", "", readme, flags=re.S)
    assert len(prose.split()) >= 40


def test_the_plugin_ships_its_license_and_reporting_channels() -> None:
    """A plugin is installed as its own directory, without the repository around it.

    MIT requires the notice to travel with the code, and a reporter holding only
    the plugin needs the private channels. Plugin scanners check for both. The
    copies are tied to the root files: the reporting address was replaced once,
    and a copy nobody checks would still name the dead one.
    """
    assert (PLUGIN_DIR / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    root_policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    reporting = root_policy.split("## Reporting a Vulnerability", 1)[1].split("\n## ", 1)[0]
    channels = re.findall(
        r"https://github\.com/\S+/security/advisories/new|[\w.+-]+@[\w-]+\.\w+", reporting
    )
    assert channels, "the root policy no longer names a private reporting channel"
    plugin_policy = (PLUGIN_DIR / "SECURITY.md").read_text(encoding="utf-8")
    for channel in channels:
        assert channel in plugin_policy, f"the plugin's SECURITY.md lacks {channel}"


def test_the_desktop_bundle_ships_its_icon() -> None:
    manifest = json.loads(
        (ROOT / "packaging" / "mcpb" / "manifest.json").read_text(encoding="utf-8")
    )
    icon = ROOT / "packaging" / "mcpb" / manifest["icon"]
    assert icon.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert icon.read_bytes() == (ROOT / "docs" / "assets" / "icon.png").read_bytes()
