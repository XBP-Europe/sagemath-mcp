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


def test_every_job_that_runs_a_repository_script_checks_the_repository_out() -> None:
    """A job that calls `scripts/…` or `make` needs a working tree.

    `docker-passagemath-manifest` assembles an index from images another job
    already pushed, so it needs no source to *build* — and the tag guard added
    in #130 put a `python3 scripts/check_image_tags.py` in it anyway. There
    was no checkout, the script was not there, the job exited 2, and
    `publish`, `github-release` and `mcp-registry` were skipped behind it.
    v0.8.4 reached GHCR and never reached PyPI (REVIEW_ACTIONS 98).

    Nothing caught it because the guard reads as configuration rather than as
    code, and a job that needs no source to build does not obviously need a
    checkout.
    """
    import yaml

    uses_tree = re.compile(r"\b(?:python3?\s+)?scripts/[\w./-]+|^\s*make\s+[a-z]", re.MULTILINE)
    offenders: list[str] = []
    for workflow in WORKFLOWS:
        config = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job_name, job in (config.get("jobs") or {}).items():
            steps = job.get("steps") or []
            checks_out = any("actions/checkout" in str(step.get("uses", "")) for step in steps)
            if checks_out:
                continue
            for step in steps:
                run = step.get("run") or ""
                if uses_tree.search(run):
                    offenders.append(
                        f"{workflow.name}:{job_name} runs a repository command "
                        "with no checkout"
                    )
                    break
    assert not offenders, "\n  ".join(["", *offenders])
