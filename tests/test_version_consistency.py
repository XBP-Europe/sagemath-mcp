"""Every file carrying the version must agree.

The Helm chart drifted for several releases because the bump script did not
touch it, and server.json had the same bug: the release workflow patched it only
in its own temporary checkout, so the manifest committed by the bump pull request
stayed stale and disagreed with the package it describes.
"""

from __future__ import annotations

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
    return found


def test_all_declared_versions_agree() -> None:
    versions = _declared_versions(ROOT)
    assert len(set(versions.values())) == 1, f"version files disagree: {versions}"


def test_bump_script_updates_every_version_file(tmp_path) -> None:
    """Run the real script against a copy and assert nothing is left behind."""
    for relative in (
        "pyproject.toml",
        "src/sagemath_mcp/__init__.py",
        "charts/sagemath-mcp/Chart.yaml",
        "server.json",
        "scripts/bump_version.py",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / relative, target)

    before = _declared_versions(tmp_path)
    subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / "bump_version.py"), "--segment", "minor"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    after = _declared_versions(tmp_path)

    assert len(set(after.values())) == 1, f"bump left files inconsistent: {after}"
    stale = [name for name, value in after.items() if value == before[name]]
    assert not stale, f"bump did not update: {stale}"


def test_dry_run_changes_nothing(tmp_path) -> None:
    for relative in ("pyproject.toml", "src/sagemath_mcp/__init__.py",
                     "charts/sagemath-mcp/Chart.yaml", "server.json",
                     "scripts/bump_version.py"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / relative, target)

    before = _declared_versions(tmp_path)
    subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / "bump_version.py"),
         "--segment", "minor", "--dry-run"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    assert _declared_versions(tmp_path) == before
