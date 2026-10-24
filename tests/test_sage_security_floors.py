"""The security floors must reach every Sage environment this project ships or tests.

The monolithic image runs on Sage's own Python, so packages the base image
ships (Pillow, certifi) are whatever the base was built with; uv.lock never
touches them. `sage-security-floors.txt` raises them when a fix lands before a
new base does. That only works while three places agree: the release
Dockerfile installs the file, `make sage-deps` installs it for the integration
suite (otherwise CI tests a Sage the image no longer ships), and uv.lock --
which the passagemath runtime installs from -- is not below any floor.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
FLOORS = ROOT / "sage-security-floors.txt"


def _floors() -> list[Requirement]:
    lines = FLOORS.read_text(encoding="utf-8").splitlines()
    return [Requirement(line) for line in lines if line.strip() and not line.startswith("#")]


def test_every_floor_is_a_lower_bound() -> None:
    """A floor that pinned or capped would block the next security fix."""
    floors = _floors()
    assert floors, "sage-security-floors.txt lists nothing"
    for req in floors:
        (spec,) = req.specifier
        assert spec.operator == ">=", f"{req} is not a plain lower bound"


def test_the_release_image_installs_the_floors() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    copy = re.search(r"^COPY (.*) \./$", dockerfile, re.MULTILINE)
    assert copy and FLOORS.name in copy.group(1).split()
    assert f"sage -python -m pip install --no-cache-dir -r {FLOORS.name}" in dockerfile


def test_the_integration_environment_installs_the_floors() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\nsage-deps:", 1)[1].split("\n\n", 1)[0]
    assert f"-r {FLOORS.name}" in recipe


def test_the_lock_is_not_below_any_floor() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = {p["name"]: Version(p["version"]) for p in lock["package"] if "version" in p}
    for req in _floors():
        if req.name in locked:
            assert locked[req.name] in req.specifier, (
                f"uv.lock has {req.name} {locked[req.name]}, below the floor {req}"
            )
