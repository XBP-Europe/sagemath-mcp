"""`SUPPORT.md` describes what this project does not have. Keep it true.

The Scorecard `Code-Review` check reads 0/10 because one account opens and
merges everything. Saying so in `SUPPORT.md` is the honest alternative to
enabling required reviews, and it is a claim like any other: it can go stale
in the direction that flatters, which is exactly what happened to the corpus
figures and the review-item count (REVIEW_ACTIONS 94 and 97).

The two ways it rots are opposite and both matter. If required reviews are
ever turned on, the note becomes a false confession and should go. If the
note is deleted while nothing changed, the repository stops disclosing
something a reader evaluating it would want.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = (ROOT / "SUPPORT.md").read_text(encoding="utf-8")


def test_the_note_exists_and_names_the_score() -> None:
    prose = " ".join(SUPPORT.split())
    assert "Code-Review 0/10" in prose, (
        "SUPPORT.md no longer states the Scorecard Code-Review score. If "
        "required reviews were enabled, delete this test with the note; if "
        "not, the disclosure belongs there."
    )
    assert "No second person reads a change before it lands" in prose


def test_the_note_does_not_overstate_the_protection() -> None:
    """`main` requires status checks but not reviews, and admin enforcement is
    off. The note has to say the second and third parts, not just the first —
    claiming protection without those qualifiers would read as stronger than
    it is."""
    prose = " ".join(SUPPORT.split())
    assert "requires seven status checks" in prose
    assert "does not require an approving review" in prose
    assert "administrator enforcement is off" in prose


def test_the_note_cites_the_incident_rather_than_only_the_principle() -> None:
    """A disclosure with no consequence attached reads as boilerplate. The
    0.8.4 release failed twice on an unreviewed change, and the write-up is in
    REVIEW_ACTIONS."""
    prose = " ".join(SUPPORT.split())
    assert "v0.8.4" in prose and "item 98" in prose
    review = (ROOT / "REVIEW_ACTIONS.md").read_text(encoding="utf-8")
    assert re.search(r"^## 98\. ", review, re.MULTILINE), (
        "SUPPORT.md points at REVIEW_ACTIONS item 98, which is not there"
    )


def test_the_claimed_check_count_matches_the_workflows() -> None:
    """Seven required status checks is a number, and numbers in prose drift.
    It cannot be read from the API without admin rights in CI, so this checks
    the weaker thing it can: that the repository still has at least that many
    distinct CI jobs to require."""
    import yaml

    jobs = set()
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        config = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        jobs |= set(config.get("jobs") or {})
    assert len(jobs) >= 7, (
        f"SUPPORT.md claims seven required status checks; only {len(jobs)} "
        "jobs exist across all workflows"
    )
