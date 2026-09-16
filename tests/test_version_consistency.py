"""Every file carrying the version must agree.

The Helm chart drifted for several releases because the bump script did not
touch it, and server.json had the same bug: the release workflow patched it only
in its own temporary checkout, so the manifest committed by the bump pull request
stayed stale and disagreed with the package it describes.
"""

from __future__ import annotations

import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _declared_versions(root: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    found["pyproject"] = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M).group(1)

    init = (root / "src" / "sagemath_mcp" / "__init__.py").read_text(encoding="utf-8")
    found["__init__"] = re.search(r'__version__\s*=\s*"([^"]+)"', init).group(1)

    chart = (root / "charts" / "sagemath-mcp" / "Chart.yaml").read_text(encoding="utf-8")
    found["chart.version"] = re.search(r"^version:\s*(\S+)", chart, re.M).group(1)
    found["chart.appVersion"] = re.search(r'^appVersion:\s*"([^"]+)"', chart, re.M).group(1)

    manifest = json.loads((root / "server.json").read_text(encoding="utf-8"))
    found["server.json"] = manifest["version"]
    found["server.json.package"] = manifest["packages"][0]["version"]

    # CITATION.cff is what GitHub's "Cite this repository" box and Zenodo read;
    # a stale version there is a citation to a release that does not exist.
    citation = (root / "CITATION.cff").read_text(encoding="utf-8")
    found["CITATION.cff"] = re.search(r"^version:\s*(\S+)", citation, re.M).group(1)

    # The MCPB bundle pins the release it installs, so a stale version here is a
    # desktop one-click install of the *previous* release.
    manifest_path = root / "packaging" / "mcpb" / "manifest.json"
    if manifest_path.exists():       # absent in the copied tree the bump test uses
        found["mcpb.manifest"] = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )["version"]
        bundle = (root / "packaging" / "mcpb" / "pyproject.toml").read_text(encoding="utf-8")
        found["mcpb.pyproject"] = re.search(
            r'^version = "([^"]+)"$', bundle, re.M
        ).group(1)
        found["mcpb.dependency"] = re.search(
            r'"sagemath-mcp\[passagemath\]==([^"]+)"', bundle
        ).group(1)

    # uv.lock records this project as a package. The v0.5.0 release bumped every
    # other file and left the lock saying 0.4.0, so `uv lock --check` failed and
    # anyone installing with `uv sync` got metadata for a version that was never
    # released. Checking it here is offline and instant.
    lock_path = root / "uv.lock"
    if lock_path.exists():          # absent in the copied tree the bump test uses
        lock = lock_path.read_text(encoding="utf-8")
        match = re.search(r'name = "sagemath-mcp"\nversion = "([^"]+)"', lock)
        assert match, "uv.lock no longer records a version for this project"
        found["uv.lock"] = match.group(1)
    return found


def test_all_declared_versions_agree() -> None:
    versions = _declared_versions(ROOT)
    assert len(set(versions.values())) == 1, f"version files disagree: {versions}"


VERSIONED_FILES = (
    "pyproject.toml",
    "src/sagemath_mcp/__init__.py",
    "charts/sagemath-mcp/Chart.yaml",
    "server.json",
    "CITATION.cff",
    "packaging/mcpb/manifest.json",
    "packaging/mcpb/pyproject.toml",
    "scripts/bump_version.py",
)


def _copy_versioned_files(tmp_path: Path) -> None:
    for relative in VERSIONED_FILES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / relative, target)


def _release_date(root: Path) -> str:
    citation = (root / "CITATION.cff").read_text(encoding="utf-8")
    return re.search(r"^date-released:\s*(\S+)", citation, re.M).group(1)


def test_bump_script_updates_every_version_file(tmp_path) -> None:
    """Run the real script against a copy and assert nothing is left behind."""
    _copy_versioned_files(tmp_path)

    before = _declared_versions(tmp_path)
    subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / "bump_version.py"), "--segment", "minor"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    after = _declared_versions(tmp_path)

    assert len(set(after.values())) == 1, f"bump left files inconsistent: {after}"
    stale = [name for name, value in after.items() if value == before[name]]
    assert not stale, f"bump did not update: {stale}"

    # The citation's release date must move with the version, or the DOI record
    # says the new version was released on the old date.
    released = _release_date(tmp_path)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", released), released
    assert released == datetime.datetime.now(datetime.UTC).date().isoformat()


def test_dry_run_changes_nothing(tmp_path) -> None:
    _copy_versioned_files(tmp_path)

    before = _declared_versions(tmp_path)
    subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / "bump_version.py"),
         "--segment", "minor", "--dry-run"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    assert _declared_versions(tmp_path) == before
