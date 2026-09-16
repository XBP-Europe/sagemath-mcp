"""The conda-forge recipe must describe the package that actually exists.

A recipe drifts silently: nothing in this repository builds it, and the people
who would notice are downstream of a conda-forge review that happens weeks
later. So the parts that can disagree with `pyproject.toml` -- runtime
dependencies, the Python floor, the entry point -- are checked here, and the
source hash is checked against PyPI when the network is available.

One asymmetry is deliberate. The recipe pins a *released* sdist and its hash,
which only exist after a release is published, so the recipe version trails
`pyproject.toml` between a version bump and the upload that follows it. The
test therefore requires the recipe version to be less than or equal to the
project version, never equal to it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "packaging" / "conda" / "meta.yaml"
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
RECIPE_TEXT = RECIPE.read_text(encoding="utf-8")


def _jinja_value(name: str) -> str:
    match = re.search(rf'{{%\s*set\s+{name}\s*=\s*"([^"]+)"\s*%}}', RECIPE_TEXT)
    assert match, f"the recipe no longer sets {name!r}"
    return match.group(1)


def _run_requirements() -> list[str]:
    """The `requirements: run:` list, comments and blank lines dropped."""
    block = re.search(r"\n  run:\n(.*?)(?=\n\w|\n  \w+:\n)", RECIPE_TEXT, re.DOTALL)
    assert block, "the recipe has no requirements/run block"
    found = []
    for line in block.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            found.append(stripped[2:].strip())
    return found


def _normalise(spec: str) -> str:
    """`fastmcp>=3.4.7,<4` and `fastmcp >=3.4.7,<4` are the same requirement."""
    return spec.replace(" ", "")


def test_the_recipe_version_is_a_released_one() -> None:
    version = _jinja_value("version")
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    project = PYPROJECT["project"]["version"]
    as_tuple = tuple(int(part) for part in version.split("."))
    project_tuple = tuple(int(part) for part in project.split("."))
    assert as_tuple <= project_tuple, (
        f"the recipe packages {version}, which is newer than the project's {project}; "
        "the recipe must name a version that has been published to PyPI"
    )
    assert "sagemath_mcp-{{ version }}.tar.gz" in RECIPE_TEXT, (
        "the source url no longer derives the sdist name from the version"
    )


def test_the_recipe_runtime_dependencies_match_pyproject() -> None:
    declared = {_normalise(dep) for dep in PYPROJECT["project"]["dependencies"]}
    in_recipe = {_normalise(dep) for dep in _run_requirements()}
    # `python` is the recipe's own, expressed through conda's python_min.
    in_recipe = {dep for dep in in_recipe if not dep.startswith("python")}
    assert in_recipe == declared, (
        f"recipe run requirements {sorted(in_recipe)} disagree with pyproject "
        f"{sorted(declared)}"
    )


def test_the_recipe_python_floor_matches_requires_python() -> None:
    required = PYPROJECT["project"]["requires-python"]
    assert "python >={{ python_min }}" in RECIPE_TEXT, (
        "the run requirement should express the floor through conda-forge's python_min"
    )
    # python_min is supplied by conda-forge's pinning, so the recipe cannot
    # state the number; what it can do is not contradict it.
    assert required == ">=3.12", (
        f"requires-python changed to {required}; check conda-forge's python_min "
        "still matches before the next recipe submission"
    )


def test_the_recipe_entry_point_matches_the_console_script() -> None:
    name, target = next(iter(PYPROJECT["project"]["scripts"].items()))
    assert f"- {name} = {target}" in RECIPE_TEXT, (
        f"the recipe's entry_points no longer builds {name} = {target}"
    )
    assert f"- {name} --help" in RECIPE_TEXT, (
        "the test command should still be the one that works without a Sage runtime"
    )


def test_the_recipe_does_not_depend_on_sage() -> None:
    """A hard Sage dependency would force a multi-gigabyte install on people
    who run the container or the passagemath extra instead."""
    assert not any(dep.split()[0] == "sage" for dep in _run_requirements())
    # The description is wrapped prose, so compare with whitespace collapsed.
    assert "deliberately not a dependency" in " ".join(RECIPE_TEXT.split())


def test_the_recipe_source_hash_matches_pypi() -> None:
    """The hash is the one thing a reviewer cannot eyeball. Skipped offline."""
    import json
    import urllib.error
    import urllib.request

    version = _jinja_value("version")
    match = re.search(r"sha256:\s*([0-9a-f]{64})", RECIPE_TEXT)
    assert match, "the recipe has no sha256"

    url = f"https://pypi.org/pypi/sagemath-mcp/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        pytest.skip(f"PyPI unreachable: {exc}")

    sdists = [f for f in payload["urls"] if f["packagetype"] == "sdist"]
    assert sdists, f"PyPI has no sdist for {version}"
    assert match.group(1) == sdists[0]["digests"]["sha256"], (
        f"the recipe's sha256 does not match the {version} sdist on PyPI"
    )
