#!/usr/bin/env python3
"""Record a Zenodo concept DOI everywhere it is read from.

Zenodo mints two DOIs per repository: a *version* DOI for each release and a
*concept* DOI that always resolves to the newest. The concept one belongs
here -- a version DOI in `CITATION.cff` freezes every citation at whichever
release happened to be first.

The number lands in four places, and keeping them in step by hand is the
failure this project keeps finding in its own documentation (REVIEW_ACTIONS
94 and 97). So it is one command, and a test asserts the four agree:

    uv run python scripts/set_zenodo_doi.py 10.5281/zenodo.1234567

Nothing here invents a DOI. Until Zenodo has minted one -- which needs the
GitHub integration switched on *and* a release published afterwards, since it
does not archive retroactively -- there is nothing to record, and
`tests/test_zenodo_doi.py` checks the machinery rather than the number.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: `10.5281/zenodo.` plus digits. Narrow on purpose: a typo that still looks
#: like a DOI would be recorded in four files and cited from all of them.
DOI_RE = re.compile(r"^10\.5281/zenodo\.\d+$")

CITATION = ROOT / "CITATION.cff"
README = ROOT / "README.md"
SUPPORT = ROOT / "SUPPORT.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"


def _citation(doi: str, text: str) -> str:
    """Add or replace the `identifiers:` block, keeping the header comment."""
    block = (
        "identifiers:\n"
        "  - type: doi\n"
        f"    value: {doi}\n"
        "    description: Concept DOI for all versions\n"
    )
    # A real key, not the header comment that *describes* the block. Matching
    # the comment made `--check` report no change to this file while happily
    # editing the other three -- caught by running it before trusting it.
    if re.search(r"^identifiers:$", text, re.MULTILINE):
        return re.sub(
            r"identifiers:\n(?:  - type: doi\n    value: \S+\n    description: [^\n]*\n)",
            block,
            text,
        )
    # Before `cff-version`, which is the first key after the header comment.
    return text.replace("cff-version:", block + "cff-version:", 1)


def _readme(doi: str, text: str) -> str:
    badge = (
        f"[![DOI](https://zenodo.org/badge/DOI/{doi}.svg)]"
        f"(https://doi.org/{doi})"
    )
    if "zenodo.org/badge/DOI/" in text:
        return re.sub(r"\[!\[DOI\]\([^)]*\)\]\([^)]*\)", badge, text)
    # Beside the other supply-chain badges, after the Scorecard one.
    marker = "[![OpenSSF Scorecard]"
    line_end = text.index("\n", text.index(marker))
    return text[:line_end] + "\n" + badge + text[line_end:]


def _support(doi: str, text: str) -> str:
    row = (
        "| Cite the software | [CITATION.cff](CITATION.cff), or GitHub's "
        "*Cite this repository* box |"
    )
    replacement = (
        "| Cite the software | [CITATION.cff](CITATION.cff), GitHub's *Cite this "
        f"repository* box, or the concept DOI [{doi}](https://doi.org/{doi}), "
        "which always resolves to the newest release |"
    )
    if row in text:
        return text.replace(row, replacement, 1)
    return re.sub(r"\| Cite the software \|[^\n]*\|", replacement, text, count=1)


def _contributing(doi: str, text: str) -> str:
    note = (
        "\nEvery tag is archived by Zenodo and gets its own version DOI; the "
        f"concept DOI [{doi}](https://doi.org/{doi}) always resolves to the "
        "newest release, and is the one to cite.\n"
    )
    if "archived by Zenodo" in text:
        # The note is one line. Matching an optional second line here ate the
        # blank line after it, so a re-run merged the note into the next
        # paragraph.
        return re.sub(r"\nEvery tag is archived by Zenodo[^\n]*\n", note, text, count=1)
    marker = "## Releasing\n"
    index = text.index(marker) + len(marker)
    return text[:index] + note + text[index:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("doi", help="the Zenodo CONCEPT DOI, e.g. 10.5281/zenodo.1234567")
    parser.add_argument("--check", action="store_true", help="report without writing")
    args = parser.parse_args(argv)

    doi = args.doi.strip().removeprefix("https://doi.org/")
    if not DOI_RE.match(doi):
        print(
            f"{doi!r} is not a Zenodo DOI. Expected 10.5281/zenodo.<digits> -- "
            "and the CONCEPT DOI, not a version one; Zenodo shows both, and the "
            "concept DOI is the one whose page says it resolves to all versions.",
            file=sys.stderr,
        )
        return 2

    changed = []
    for path, edit in (
        (CITATION, _citation),
        (README, _readme),
        (SUPPORT, _support),
        (CONTRIBUTING, _contributing),
    ):
        before = path.read_text(encoding="utf-8")
        after = edit(doi, before)
        if after != before:
            changed.append(path.name)
            if not args.check:
                path.write_text(after, encoding="utf-8")

    if args.check:
        print(f"would update: {', '.join(changed) or 'nothing'}")
        return 0
    print(f"recorded {doi} in: {', '.join(changed) or 'nothing (already current)'}")
    print("Validate with: pipx run cffconvert --validate -i CITATION.cff")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
