"""The release's provenance asset must cover everything the release ships.

`scripts/check_provenance_bundle.py` is the only thing standing between "the
release has a provenance file" and "the provenance file is provenance for this
release". It runs once a year, inside a job nobody watches, so its behaviour is
pinned here instead of being discovered on a tag.

The bundles below are the real Sigstore shape reduced to what the script reads:
a JSON Lines file whose every line carries a DSSE envelope with a base64 in-toto
statement. The v0.8.0 release is the worked example -- it attested the wheel and
the sdist but not the desktop bundle, which did not exist yet.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_provenance_bundle.py"


def _bundle(path: Path, *lines: list[str]) -> Path:
    """Write a JSON Lines bundle file, one DSSE envelope per subject list."""
    written = []
    for names in lines:
        statement = {
            "_type": "https://in-toto.io/Statement/v1",
            "predicateType": "https://slsa.dev/provenance/v1",
            "subject": [
                {"name": name, "digest": {"sha256": "0" * 64}} for name in names
            ],
        }
        payload = base64.b64encode(json.dumps(statement).encode()).decode()
        written.append(json.dumps({"dsseEnvelope": {"payload": payload}}))
    path.write_text("\n".join(written) + "\n", encoding="utf-8")
    return path


def _run(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_bundle_naming_all_three_artifacts_passes(tmp_path: Path) -> None:
    bundle = _bundle(
        tmp_path / "ok.intoto.jsonl",
        [
            "sagemath_mcp-0.9.0-py3-none-any.whl",
            "sagemath_mcp-0.9.0.tar.gz",
            "sagemath-mcp-0.9.0.mcpb",
        ],
    )
    result = _run(bundle)
    assert result.returncode == 0, result.stderr
    assert "3 attested subject(s)" in result.stdout


def test_a_missing_artifact_fails_the_release(tmp_path: Path) -> None:
    """What v0.8.0's own provenance looks like: wheel and sdist, no bundle.

    The attestation step succeeds either way -- a glob that matches nothing is
    not an error -- so this is the only place the gap is caught.
    """
    bundle = _bundle(
        tmp_path / "partial.intoto.jsonl",
        ["sagemath_mcp-0.8.0-py3-none-any.whl", "sagemath_mcp-0.8.0.tar.gz"],
    )
    result = _run(bundle)
    assert result.returncode == 1
    assert ".mcpb" in result.stderr
    assert "::error::" in result.stderr


def test_subjects_are_read_from_every_line(tmp_path: Path) -> None:
    """The action appends when it attests more than once in a job, so a bundle
    file is JSON Lines and reading only the first line would miss subjects."""
    bundle = _bundle(
        tmp_path / "multi.intoto.jsonl",
        ["sagemath_mcp-0.9.0-py3-none-any.whl", "sagemath_mcp-0.9.0.tar.gz"],
        ["sagemath-mcp-0.9.0.mcpb"],
    )
    result = _run(bundle)
    assert result.returncode == 0, result.stderr


def test_the_release_runs_the_check(tmp_path: Path) -> None:
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "scripts/check_provenance_bundle.py" in release, (
        "the release attaches a provenance asset without checking what it covers"
    )
