"""The release's supply-chain claims must be checkable, and the recipe correct.

Three README badges say this project signs and attests what it publishes.
`SECURITY.md` now carries the commands to check that. A verification recipe is
the worst kind of documentation to let rot: a stale `--certificate-identity`
either fails for everyone, or -- if it is loosened to make the failure go away
-- passes for identities that should not be trusted, which is worse than having
no recipe at all.

So the documented signer pattern is applied here to the identity a release
actually produces, and to identities it must reject. And the tags the recipe
tells people to pull are checked against the tag set the workflow is required
to publish, which is the gap v0.8.3 shipped with: the chart told operators to
prefer a release tag, and no bare version tag existed.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_image_tags import expected_tags  # noqa: E402

SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
IMAGE = "ghcr.io/xbp-europe/sagemath-mcp"

#: The identity GitHub puts in the signing certificate: the signing workflow's
#: path at the ref it ran on. Verified against the live v0.8.3 signature.
RELEASE_IDENTITY = (
    "https://github.com/XBP-Europe/sagemath-mcp/.github/workflows/release.yml@refs/tags/v0.8.3"
)


def _documented_identity_pattern() -> str:
    """The regexp SECURITY.md hands to `cosign verify`, unescaped from Markdown."""
    match = re.search(r"--certificate-identity-regexp='([^']+)'", SECURITY)
    assert match, "SECURITY.md documents no --certificate-identity-regexp"
    # The fenced block escapes backslashes for the shell line continuation it
    # sits on; what cosign receives is the single-backslash form.
    return match.group(1).replace("\\\\", "\\")


def test_the_documented_signer_pattern_matches_a_real_release() -> None:
    assert re.search(_documented_identity_pattern(), RELEASE_IDENTITY)


def test_the_documented_signer_pattern_rejects_what_it_must() -> None:
    """A pattern that matches everything verifies nothing. Each of these is a
    signature someone could genuinely produce through Sigstore."""
    for identity in (
        # Another repository's release workflow.
        "https://github.com/attacker/sagemath-mcp/.github/workflows/release.yml@refs/tags/v9.9.9",
        # This repository, but a workflow that is not the release.
        "https://github.com/XBP-Europe/sagemath-mcp/.github/workflows/ci.yml@refs/heads/main",
        # The release workflow run from a branch rather than a release tag.
        "https://github.com/XBP-Europe/sagemath-mcp/.github/workflows/release.yml@refs/heads/main",
        # A lookalike owner, which an unanchored pattern would accept.
        "https://github.com/evil-XBP-Europe/sagemath-mcp/.github/workflows/release.yml@refs/tags/v1",
    ):
        assert not re.search(_documented_identity_pattern(), identity), identity


def test_the_documented_workflow_path_exists() -> None:
    """The pattern names release.yml; if the file were renamed, every published
    recipe would fail and the rename would look like a compromise."""
    assert (ROOT / ".github" / "workflows" / "release.yml").is_file()
    assert "cosign sign" in WORKFLOW


def test_the_recipe_pulls_tags_the_release_actually_publishes() -> None:
    """v0.8.3's lesson. Every image reference in the recipe must be a tag the
    workflow is required to produce for the current version."""
    published = expected_tags(IMAGE, f"v{VERSION}") | expected_tags(
        IMAGE, f"v{VERSION}", "-passagemath"
    )
    referenced = set(re.findall(rf"{re.escape(IMAGE)}:[\w.\-]+", SECURITY))
    assert referenced, "the verification recipe names no image"
    assert referenced <= published, sorted(referenced - published)


def test_the_workflow_asks_for_the_tags_the_guard_requires() -> None:
    """The guard script states the requirement; the metadata step has to be
    configured to meet it, in both image jobs."""
    assert WORKFLOW.count("type=semver,pattern={{version}}") == 2
    assert WORKFLOW.count("type=semver,pattern={{major}}.{{minor}}") == 2
    # Invocations, not mentions. This counted occurrences in the file and
    # broke when a comment named the script -- a test that fails because the
    # code around it was explained is measuring the wrong thing.
    import yaml

    config = yaml.safe_load(WORKFLOW)
    invocations = sum(
        1
        for job in config["jobs"].values()
        for step in (job.get("steps") or [])
        if "scripts/check_image_tags.py" in (step.get("run") or "")
    )
    assert invocations == 2, f"the tag guard runs in {invocations} jobs, expected 2"


def test_no_bare_major_tag_is_promised() -> None:
    """A `0` tag would promise stability the version number denies, and moving
    it on a 0.x minor bump would break whoever pinned it."""
    assert f"{IMAGE}:0 " not in SECURITY
    assert "{{major}}}}" not in WORKFLOW


def test_the_signing_badges_link_to_the_recipe() -> None:
    """Both badges pointed at the workflow source, which tells a reader that
    signing happens but not how to check it."""
    for label in ("Signed", "Provenance"):
        match = re.search(rf"!\[{label}\]\([^)]+\)\]\(([^)]+)\)", README)
        assert match, f"no {label} badge in the README"
        assert match.group(1).endswith("SECURITY.md#verifying-a-release"), match.group(1)


def test_the_recipe_warns_that_gh_prints_nothing_when_piped() -> None:
    """`gh attestation verify` exits 0 and prints nothing without a terminal.
    A reader who checks the output instead of the status concludes the opposite
    of the truth, so the recipe has to say so."""
    # Whitespace-collapsed: the sentence wraps, and an earlier version of this
    # assertion failed for that alone. The same wrap made a Helm README check
    # pass vacuously once, which is the worse direction.
    prose = " ".join(SECURITY.lower().split())
    assert "read the exit status, not the output" in prose
