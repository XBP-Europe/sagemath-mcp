"""The MCPB bundle must describe a server that can actually start.

A bundle fails in the worst place: inside someone's desktop app, after a
one-click install, with no log they will read. Nothing here needs the bundle to
be packed or a host to run it -- these are the mistakes that survive review and
only surface there.

`tests/test_version_consistency.py` covers the version fields; this file covers
the rest of the manifest's promises.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "packaging" / "mcpb"
MANIFEST = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
BUNDLE_PYPROJECT = tomllib.loads((BUNDLE / "pyproject.toml").read_text(encoding="utf-8"))
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_manifest_has_what_the_spec_requires() -> None:
    for field in ("manifest_version", "name", "version", "description", "author", "server"):
        assert field in MANIFEST, f"manifest is missing the required field {field!r}"
    assert MANIFEST["author"].get("name"), "author.name is required"
    # The uv server type arrived in 0.4; declaring an older spec version with it
    # would be rejected by hosts that honour the declaration.
    assert MANIFEST["manifest_version"] >= "0.4"
    assert MANIFEST["server"]["type"] == "uv"


def test_the_entry_point_exists_and_starts_the_server() -> None:
    entry = BUNDLE / MANIFEST["server"]["entry_point"]
    assert entry.is_file(), f"entry_point {entry} does not exist in the bundle"
    source = entry.read_text(encoding="utf-8")
    assert "from sagemath_mcp.server import main" in source
    # `main([])`, not `main()`: with no argument the parser reads *this
    # process's* argv, which for `uv run src/server.py` is not what the server
    # expects. The empty list selects the default stdio transport, which is what
    # a desktop host speaks.
    assert "main([])" in source


def test_the_bundle_installs_a_sage_runtime() -> None:
    """A bundle that installs only the server would start and then refuse every
    evaluation, because there would be no Sage behind it."""
    deps = BUNDLE_PYPROJECT["project"]["dependencies"]
    assert any(dep.startswith("sagemath-mcp[passagemath]==") for dep in deps), deps
    assert len(deps) == 1, "the bundle should pin one thing and let uv resolve the rest"


def test_the_bundle_does_not_ship_an_environment() -> None:
    """The uv server type's whole point is that the host resolves dependencies
    for its own platform; a shipped venv would break that and the spec forbids
    it."""
    ignored = (BUNDLE / ".mcpbignore").read_text(encoding="utf-8")
    assert ".venv/" in ignored
    assert "server/lib/" in ignored
    assert not (BUNDLE / ".venv").exists()
    assert not (BUNDLE / "server" / "lib").exists()


def test_the_declared_platforms_match_what_passagemath_supports() -> None:
    """Windows is excluded deliberately.

    `docs/passagemath_evaluation.md` measured native Windows as partial --
    `plot` yes, `pari`/`singular`/`maxima` no -- so a one-click Windows install
    would produce a server that starts and then fails most of its tools.
    """
    platforms = MANIFEST["compatibility"]["platforms"]
    assert set(platforms) == {"darwin", "linux"}, platforms
    floor = MANIFEST["compatibility"]["runtimes"]["python"]
    assert floor == PYPROJECT["project"]["requires-python"], (
        f"bundle requires python {floor}, project requires "
        f"{PYPROJECT['project']['requires-python']}"
    )
    assert BUNDLE_PYPROJECT["project"]["requires-python"] == floor


def test_the_description_warns_about_the_first_launch_download() -> None:
    """A gigabyte arriving after a one-click install is the kind of surprise
    that gets an extension uninstalled before it ever works."""
    blurb = MANIFEST.get("long_description", "")
    assert "1 GB" in blurb
    assert "first" in blurb.lower()
    # And the security posture, since a local install is not the container.
    assert "container" in blurb.lower()


def test_the_release_builds_and_attaches_the_bundle() -> None:
    """A bundle nobody can download is a file in a repository, not an install
    path. It is built in the `build` job on purpose: `mcpb pack` validates the
    manifest as it packs, so a bad manifest fails before anything publishes.
    """
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "mcpb@latest pack packaging/mcpb" in release, (
        "release.yml no longer builds the bundle"
    )
    assert 'bundle/sagemath-mcp-${VERSION}.mcpb' in release
    # Packed in one job, attached in another, so it needs to travel as an
    # artifact; without this the release page has no bundle on it.
    assert "name: mcpb" in release, "the bundle is not uploaded as an artifact"
    assert "dist/* bundle/* sbom/* provenance/*" in release, (
        "the release no longer attaches the bundle and the provenance"
    )


def test_the_bundle_is_not_in_the_directory_pypi_publishes() -> None:
    """dist/ is uploaded to PyPI, and twine reads the whole directory.

    A .mcpb there fails the upload with `InvalidDistribution: Unknown
    distribution format`, and it fails it in the publish job -- after the
    container images have been pushed and signed. That is why the bundle is
    packed into bundle/ and why the build job refuses anything else in dist/.
    """
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "packages-dir: dist" in release, (
        "the publish job no longer uploads dist/; re-check where the bundle may live"
    )
    assert "dist/sagemath-mcp-" not in release, "the bundle is being packed into dist/ again"
    assert "Keep dist/ to what PyPI accepts" in release, (
        "the guard that keeps non-distributions out of dist/ is gone"
    )
    # The Makefile has to agree, or `make mcpb` reintroduces locally what the
    # release forbids.
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "pack packaging/mcpb bundle/" in makefile


def test_the_release_attaches_signed_provenance() -> None:
    """Provenance in GitHub's attestation store is verifiable but invisible.

    A `.intoto.jsonl` on the release is the same Sigstore bundle in the place a
    consumer -- or a scanner reading release assets, which is how OpenSSF
    Scorecard's Signed-Releases check works -- actually looks. The bundle is one
    of its subjects, and the release-page copy is the only provenance it has.
    """
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "attest-build-provenance" in release
    assert "bundle/*.mcpb" in release, "the desktop bundle is no longer attested"
    assert "steps.attest.outputs.bundle-path" in release, (
        "the attestation bundle is no longer copied out of the action's output"
    )
    assert '.intoto.jsonl' in release, (
        "Scorecard's Signed-Releases probe matches on this exact suffix"
    )
