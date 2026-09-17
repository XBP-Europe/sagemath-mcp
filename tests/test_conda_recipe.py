"""The conda-forge recipe must describe the package that actually exists.

A recipe drifts silently: nothing in this repository builds it, and the people
who would notice are downstream of a conda-forge review that happens weeks
later. So the parts that can disagree with `pyproject.toml` -- runtime
dependencies, the Python floor, the entry point -- are checked here, and the
source hash is checked against PyPI when the network is available.

The recipe is in the **v1 (`recipe.yaml`) format** from CEP 13/14.
staged-recipes deprecated the v0 `meta.yaml` format in August 2026 and warns
that v0 submissions are "less likely to be reviewed in a timely manner", so v1
is what gets submitted and therefore what is kept here. It is also plain YAML --
the `${{ }}` substitutions are ordinary strings to a YAML parser -- so this file
reads the recipe as data rather than with the regexes the v0 format forced.

One asymmetry is deliberate. The recipe pins a *released* sdist and its hash,
which only exist after a release is published, so the recipe version trails
`pyproject.toml` between a version bump and the upload that follows it. The
test therefore requires the recipe version to be less than or equal to the
project version, never equal to it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
RECIPE_PATH = ROOT / "packaging" / "conda" / "recipe.yaml"
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
RECIPE: dict[str, Any] = yaml.safe_load(RECIPE_PATH.read_text(encoding="utf-8"))
RECIPE_TEXT = RECIPE_PATH.read_text(encoding="utf-8")


def _normalise(spec: str) -> str:
    """`fastmcp>=3.4.7,<4` and `fastmcp >=3.4.7,<4` are the same requirement."""
    return spec.replace(" ", "")


def test_the_recipe_is_the_v1_format_staged_recipes_wants() -> None:
    """v0 `meta.yaml` is deprecated upstream, and a deprecated submission waits
    longer for review. The schema declaration is what selects the parser."""
    assert RECIPE["schema_version"] == 1
    assert not (ROOT / "packaging" / "conda" / "meta.yaml").exists(), (
        "the deprecated v0 recipe is back; one recipe, and it is the one submitted"
    )


def test_the_recipe_version_is_a_released_one() -> None:
    version = str(RECIPE["context"]["version"])
    assert version.count(".") == 2 and all(p.isdigit() for p in version.split("."))
    project = PYPROJECT["project"]["version"]
    as_tuple = tuple(int(part) for part in version.split("."))
    project_tuple = tuple(int(part) for part in project.split("."))
    assert as_tuple <= project_tuple, (
        f"the recipe packages {version}, which is newer than the project's {project}; "
        "the recipe must name a version that has been published to PyPI"
    )
    assert "sagemath_mcp-${{ version }}.tar.gz" in RECIPE["source"]["url"], (
        "the source url no longer derives the sdist name from the version"
    )


def test_the_recipe_runtime_dependencies_match_pyproject() -> None:
    declared = {_normalise(dep) for dep in PYPROJECT["project"]["dependencies"]}
    in_recipe = {_normalise(dep) for dep in RECIPE["requirements"]["run"]}
    # `python` is the recipe's own, expressed through conda's python_min.
    in_recipe = {dep for dep in in_recipe if not dep.startswith("python")}
    assert in_recipe == declared, (
        f"recipe run requirements {sorted(in_recipe)} disagree with pyproject "
        f"{sorted(declared)}"
    )


def test_the_recipe_python_floor_matches_requires_python() -> None:
    required = PYPROJECT["project"]["requires-python"]
    assert "python >=${{ python_min }}" in RECIPE["requirements"]["run"], (
        "the run requirement should express the floor through conda-forge's python_min"
    )
    assert "python ${{ python_min }}.*" in RECIPE["requirements"]["host"], (
        "the host requirement should pin python_min exactly, as noarch recipes do"
    )
    # conda-forge's global python_min is lower than this project's floor, so the
    # recipe overrides it in `context`. Getting this wrong does not warn: the
    # build environment simply gets the older Python and pip refuses the install
    # with "requires a different Python", which is how it was found.
    declared = RECIPE["context"]["python_min"]
    assert required == f">={declared}", (
        f"pyproject requires-python is {required} but the recipe's python_min is "
        f"{declared}; conda-forge would build against the wrong Python"
    )


def test_the_recipe_entry_point_matches_the_console_script() -> None:
    name, target = next(iter(PYPROJECT["project"]["scripts"].items()))
    assert RECIPE["build"]["python"]["entry_points"] == [f"{name} = {target}"]
    scripts = [
        line
        for test in RECIPE["tests"]
        for line in test.get("script", [])
    ]
    assert f"{name} --help" in scripts, (
        "the test command should still be the one that works without a Sage runtime"
    )


def test_the_recipe_does_not_depend_on_sage() -> None:
    """A hard Sage dependency would force a multi-gigabyte install on people
    who run the container or the passagemath extra instead."""
    assert not any(dep.split()[0] == "sage" for dep in RECIPE["requirements"]["run"])
    assert "deliberately not a dependency" in " ".join(RECIPE["about"]["description"].split())


def test_the_recipe_names_a_maintainer_who_exists() -> None:
    """Whoever is listed is publicly on the hook for the feedstock, including
    the bot's pull requests for every later release. An empty or placeholder
    list is how a recipe gets submitted in someone else's name."""
    maintainers = RECIPE["extra"]["recipe-maintainers"]
    assert maintainers == ["csteinlxbp"], maintainers


def test_the_recipe_source_hash_matches_pypi() -> None:
    """The hash is the one thing a reviewer cannot eyeball. Skipped offline."""
    import json
    import urllib.error
    import urllib.request

    version = str(RECIPE["context"]["version"])
    recorded = RECIPE["source"]["sha256"]
    assert isinstance(recorded, str) and len(recorded) == 64

    url = f"https://pypi.org/pypi/sagemath-mcp/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        pytest.skip(f"PyPI unreachable: {exc}")

    sdists = [f for f in payload["urls"] if f["packagetype"] == "sdist"]
    assert sdists, f"PyPI has no sdist for {version}"
    assert recorded == sdists[0]["digests"]["sha256"], (
        f"the recipe's sha256 does not match the {version} sdist on PyPI"
    )
