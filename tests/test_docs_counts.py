"""Counts quoted in prose must be derivable from the thing they count.

`ROADMAP.md` said `REVIEW_ACTIONS.md` held "34 items ... All are closed". It
holds 93, numbered to 96, and two are open by design. Wrong by nearly a factor
of three, and wrong in the direction that flatters: a reader takes "34,
all closed" as a finished piece of work rather than a running ledger.

This is the same failure as the corpus figures that had drifted two releases
(REVIEW_ACTIONS 94) -- a number nothing regenerates -- and the tests added
then only cover acceptance percentages. Counts of tools, resources and review
items are equally derivable and were equally unchecked.

Numbers presented as *history* are exempt, on the same terms as the superseded
corpus figures: they may stay where the sentence says when they were true.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Every document that makes a claim about how many of something there is.
_DOCUMENTS = ("README.md", "ROADMAP.md", "CLAUDE.md", "USAGE.md", "INSTALLATION.md")


def _review_items() -> tuple[int, list[str]]:
    """(how many items, which are not marked DONE)."""
    text = (ROOT / "REVIEW_ACTIONS.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (\d+)\. (.+)$", text, re.MULTILINE)
    assert headings, "REVIEW_ACTIONS.md has no numbered items; the shape changed"
    return len(headings), [number for number, title in headings if "DONE" not in title]


def test_the_review_item_count_is_current() -> None:
    count, _ = _review_items()
    roadmap = " ".join((ROOT / "ROADMAP.md").read_text(encoding="utf-8").split())
    assert f"{count} items" in roadmap, (
        f"REVIEW_ACTIONS.md holds {count} items; ROADMAP.md does not say so. "
        "Read it off the file rather than editing the prose to a plausible "
        "number.\n"
        "Yes, this means adding an item means editing that line. That is the "
        "cost of the number being true, and it is one line against a count "
        "that was wrong by a factor of three when nothing checked it."
    )


def test_the_roadmap_does_not_claim_every_item_is_closed() -> None:
    """Two are open on purpose -- one accepted, one deferred -- and a blanket
    "all are closed" erases a deliberate decision rather than a backlog."""
    _, still_open = _review_items()
    roadmap = " ".join((ROOT / "ROADMAP.md").read_text(encoding="utf-8").split())
    if still_open:
        assert "All are closed" not in roadmap, (
            f"items {', '.join(still_open)} are not marked DONE, but ROADMAP.md "
            "says all are closed"
        )


@pytest.mark.parametrize("document", _DOCUMENTS)
def test_no_document_misstates_the_tool_count(document: str) -> None:
    """The tool count appears in four documents and the registry is the only
    authority. A tool added without touching the prose would leave four
    numbers wrong at once.

    A count inside a sentence that dates itself is history and is left alone --
    `ROADMAP.md` keeps a 2026-08-13 competitive snapshot at 37 tools.
    """
    import json

    from tests.test_tool_inventory import SNAPSHOT

    # The snapshot is the tool contract, regenerated deliberately and reviewed
    # in its diff -- so it is the right authority for a count in prose, and it
    # needs no event loop here.
    expected = len(json.loads(SNAPSHOT.read_text(encoding="utf-8"))["tools"])
    text = (ROOT / document).read_text(encoding="utf-8")
    for match in re.finditer(r"(\d+) tools\b", text):
        if int(match.group(1)) == expected:
            continue
        window = " ".join(text[max(0, match.start() - 300) : match.end() + 200].split())
        assert re.search(r"\d{4}-\d{2}-\d{2}", window), (
            f"{document} says {match.group(1)} tools; the server registers "
            f"{expected}, and the sentence does not date itself as history"
        )
