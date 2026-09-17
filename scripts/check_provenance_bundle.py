"""Check that a release's provenance bundle covers everything the release ships.

`actions/attest-build-provenance` writes one Sigstore bundle naming every
subject it attested. The release attaches that file as
`sagemath-mcp-<version>.intoto.jsonl`, and a consumer who verifies against it
is entitled to read "this file is provenance for this release". If a glob in
the workflow ever stops matching -- a renamed directory, a bundle that failed to
pack -- the attestation still succeeds, the asset still appears, and it quietly
covers less than it claims. That is worse than shipping no provenance at all, so
this fails the build instead.

Usage: ``python3 scripts/check_provenance_bundle.py <bundle.intoto.jsonl>``
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

# One artefact of each kind is attached to every release: the wheel, the sdist
# and the one-click desktop bundle.
REQUIRED_SUFFIXES = (".whl", ".tar.gz", ".mcpb")


def subjects_in(bundle_path: Path) -> list[str]:
    """Every subject name in the bundle, across all its lines.

    The file is JSON Lines: normally one bundle, but the action appends when it
    runs more than once in a job, so read every line.
    """
    names: list[str] = []
    for line in bundle_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        bundle = json.loads(line)
        payload = bundle["dsseEnvelope"]["payload"]
        statement = json.loads(base64.b64decode(payload))
        names.extend(subject["name"] for subject in statement["subject"])
    return names


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(f"usage: {Path(__file__).name} <bundle.intoto.jsonl>", file=sys.stderr)
        return 2
    bundle_path = Path(argv[0])
    names = subjects_in(bundle_path)
    print(f"{bundle_path}: {len(names)} attested subject(s)")
    for name in names:
        print(f"  {name}")
    missing = [
        suffix
        for suffix in REQUIRED_SUFFIXES
        if not any(name.endswith(suffix) for name in names)
    ]
    if missing:
        print(
            f"::error::{bundle_path} has no provenance for {', '.join(missing)}; "
            f"it names only {names}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI test
    raise SystemExit(main(sys.argv[1:]))
