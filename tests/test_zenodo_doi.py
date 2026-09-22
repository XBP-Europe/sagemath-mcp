"""The Zenodo DOI, wherever it is recorded, must be one number.

Issue #92. Zenodo mints a *concept* DOI that resolves to the newest release
and a *version* DOI per release; the concept one is what a citation should
carry, and it appears in four files. Four copies of a number is exactly the
shape that drifted in REVIEW_ACTIONS 94 and 97, so it is written by one
command and checked here.

These tests are meaningful **before** the DOI exists as well as after. Until
Zenodo has minted one -- which needs the GitHub integration enabled *and* a
release published afterwards, since it does not archive retroactively -- they
assert the machinery is intact and that nothing has invented a number. That
matters: a placeholder DOI committed by accident would render as a real badge
and resolve to someone else's record.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOI_RE = re.compile(r"10\.5281/zenodo\.\d+")

_FILES = ("CITATION.cff", "README.md", "SUPPORT.md", "CONTRIBUTING.md")


def _dois() -> dict[str, set[str]]:
    found = {}
    for name in _FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        # Skip the header comment in CITATION.cff, which shows the shape with
        # an XXXXXXX placeholder rather than claiming a DOI.
        found[name] = {d for d in DOI_RE.findall(text)}
    return found


def test_the_recorded_doi_is_the_same_everywhere() -> None:
    found = _dois()
    present = {name: dois for name, dois in found.items() if dois}
    if not present:
        pytest.skip("no Zenodo DOI recorded yet; issue #92 is still blocked")
    numbers = {doi for dois in present.values() for doi in dois}
    assert len(numbers) == 1, (
        f"more than one DOI is recorded: { {k: sorted(v) for k, v in present.items()} }. "
        "Run scripts/set_zenodo_doi.py rather than editing the files by hand."
    )
    missing = sorted(set(_FILES) - set(present))
    assert not missing, (
        f"the DOI is recorded in {sorted(present)} but not in {missing}; "
        "run scripts/set_zenodo_doi.py to write all four"
    )


def test_no_placeholder_doi_is_committed() -> None:
    """A placeholder renders as a real badge and resolves to someone else's
    record. `XXXXXXX` in the CITATION.cff header comment is the documented
    shape and is not a number, so it is fine; digits are not."""
    for name, dois in _dois().items():
        for doi in dois:
            digits = doi.rsplit(".", 1)[1]
            assert not digits.strip("0") == "" and digits not in {"1234567", "9999999"}, (
                f"{name} carries the placeholder {doi}"
            )


def test_the_doi_can_be_recorded_by_one_command() -> None:
    """Four files by hand is how the corpus figures and the review-item count
    drifted. The script exists and refuses anything that is not a Zenodo DOI,
    because a typo would be recorded in all four and cited from all four."""
    import subprocess
    import sys

    script = ROOT / "scripts" / "set_zenodo_doi.py"
    assert script.is_file()
    result = subprocess.run(
        [sys.executable, str(script), "not-a-doi"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 2, result.stderr
    assert "not a Zenodo DOI" in result.stderr


def test_the_issue_is_reachable_from_the_citation_file() -> None:
    """Until the DOI exists, the file has to say what is missing and how the
    shape looks — otherwise the next person adds a version DOI, which freezes
    every citation at one release."""
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    if DOI_RE.search(citation):
        return  # recorded; the comment has done its job
    assert "concept doi" in citation.lower()
    assert "zenodo" in citation.lower()
