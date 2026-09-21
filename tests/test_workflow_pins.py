"""Workflow actions must be pinned to a commit, not to a tag.

A tag is mutable. `uses: some/action@v1` runs whatever that tag points at
today, so a compromised or simply retagged action executes in a job that holds
this repository's secrets and can push to GHCR and PyPI. Every workflow here
already pins by SHA; nothing checked that the next one would.

This is also what the OpenSSF Scorecard's Pinned-Dependencies check looks
for, but the reason to keep it is the release pipeline: `release.yml` is code
that publishes, and the trust placed in an action there is the trust placed in
everything it publishes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

_USES = re.compile(r"uses:\s*(?P<action>[^\s@]+)@(?P<ref>\S+)")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def test_there_are_workflows_to_check() -> None:
    """A glob that matches nothing passes every test below."""
    assert WORKFLOWS, "no workflows found; this file would pass vacuously"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit(workflow: Path) -> None:
    unpinned: list[str] = []
    for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
        match = _USES.search(line)
        if not match:
            continue
        action, ref = match["action"], match["ref"]
        if action.startswith("./"):
            continue  # a local composite action is this repository's own code
        if not _SHA.match(ref):
            unpinned.append(f"line {number}: {action}@{ref}")
    assert not unpinned, (
        f"{workflow.name} uses a mutable ref. Pin the commit and keep the "
        "version in a trailing comment:\n  " + "\n  ".join(unpinned)
    )


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_every_pin_records_the_version_it_came_from(workflow: Path) -> None:
    """A bare forty-character hash is unreviewable. The trailing `# vX.Y.Z` is
    what lets a reader tell an upgrade from a substitution, and it is what
    Dependabot rewrites when it bumps one."""
    missing: list[str] = []
    for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
        match = _USES.search(line)
        if not match or match["action"].startswith("./"):
            continue
        if _SHA.match(match["ref"]) and not re.search(r"#\s*v?\d", line):
            missing.append(f"line {number}: {match['action']}")
    assert not missing, (
        f"{workflow.name} pins a commit with no version comment:\n  " + "\n  ".join(missing)
    )
