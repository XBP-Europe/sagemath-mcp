"""requirements-passagemath.txt must be exactly what uv.lock says.

Dockerfile.passagemath installs the passagemath runtime with
``pip install --require-hashes -r requirements-passagemath.txt`` so the image
gets the locked set and nothing else. That only holds while the exported file
and ``uv.lock`` agree. Both move: a pin bump edits the lock, so does a
Dependabot update or ``uv lock --upgrade``. If the export is not regenerated
(``make passagemath-lock``), the image silently installs the previous set --
or, worse, the old hashes stop matching and the build fails on a release tag.
This test makes the drift fail here instead.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXPORTED = ROOT / "requirements-passagemath.txt"

# The exact command `make passagemath-lock` runs, minus the output file: the
# header uv writes records the command, so the two are compared without it.
EXPORT_COMMAND = (
    "uv", "export", "--frozen", "--extra", "passagemath", "--no-dev",
    "--no-emit-project", "--format", "requirements.txt",
)


def _requirement_lines(text: str) -> list[str]:
    """Requirement and hash lines only: uv's header and its indented
    ``# via <parent>`` annotations are comments, not content."""
    return [
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_every_requirement_is_hash_pinned() -> None:
    """--require-hashes refuses a file with any unhashed requirement; check first
    so the failure names the package rather than a pip error inside a build."""
    lines = _requirement_lines(EXPORTED.read_text(encoding="utf-8"))
    requirements = [line for line in lines if not line.lstrip().startswith("--hash=")]
    assert requirements, "the exported file has no requirements"
    for i, line in enumerate(lines):
        if line.lstrip().startswith("--hash="):
            continue
        assert line.endswith("\\"), f"requirement without a hash continuation: {line!r}"
        assert i + 1 < len(lines) and lines[i + 1].lstrip().startswith("--hash="), (
            f"requirement without a hash: {line!r}"
        )
    assert not any(line.startswith("sagemath-mcp") for line in requirements), (
        "the project itself is in the export; it is installed separately with --no-deps"
    )
    assert any(line.startswith("passagemath-standard==") for line in requirements), (
        "the passagemath extra is not in the export"
    )


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_the_export_matches_the_lockfile() -> None:
    result = subprocess.run(
        [*EXPORT_COMMAND],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    expected = _requirement_lines(result.stdout)
    actual = _requirement_lines(EXPORTED.read_text(encoding="utf-8"))
    assert actual == expected, (
        "requirements-passagemath.txt does not match uv.lock; run `make passagemath-lock` "
        "and commit the result (the Dockerfile installs from this file with --require-hashes)"
    )
