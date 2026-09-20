"""Assert the image tag set a release is about to push.

`docker/metadata-action` decides the tags, and what it decides is invisible
until someone pulls. v0.8.3 shipped with only `v0.8.3` and `latest`, because
the action ran on its defaults with no `tags:` input -- so the chart's own
advice ("prefer a release tag over `latest`") pointed at tags that did not
exist, and nobody could tell until they tried.

The tag list cannot be checked before a release: `type=semver` produces nothing
on a branch, so a dry-run dispatch cannot exercise it. This runs inside the
release instead, between the metadata step and the push, and fails the release
rather than publishing a tag set that is quietly short.

Reads the produced tags on stdin, one per line, as the action emits them.
"""

from __future__ import annotations

import argparse
import re
import sys

#: `v1.2.3`, the only shape the release trigger and this project's tags take.
#: A pre-release (`v1.2.3-rc1`) is deliberately unmatched: it must not claim the
#: moving `1.2` tag, and this says so instead of guessing.
RELEASE_TAG = re.compile(r"^v(?P<version>(?P<major>\d+)\.(?P<minor>\d+)\.\d+)$")


def expected_tags(image: str, ref_name: str, suffix: str = "") -> set[str]:
    """The tags a release of `ref_name` must publish, or an empty set.

    Empty means "this ref is not a plain release tag", which is not a failure:
    the same workflow runs on dispatch, where there is nothing to assert.
    """
    match = RELEASE_TAG.match(ref_name)
    if not match:
        return set()
    version, major, minor = match["version"], match["major"], match["minor"]
    return {
        f"{image}:{ref_name}{suffix}",  # the git ref, verbatim
        f"{image}:{version}{suffix}",  # pin a deployment to this patch
        f"{image}:{major}.{minor}{suffix}",  # track the minor line
        f"{image}:latest{suffix}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--ref-name", required=True)
    parser.add_argument("--suffix", default="")
    args = parser.parse_args(argv)

    expected = expected_tags(args.image, args.ref_name, args.suffix)
    if not expected:
        print(f"{args.ref_name} is not a release tag; nothing to assert.")
        return 0

    produced = {line.strip() for line in sys.stdin if line.strip()}
    if missing := sorted(expected - produced):
        print(
            "The metadata step did not produce every tag this release must "
            f"publish.\n  missing:  {', '.join(missing)}\n  produced: "
            f"{', '.join(sorted(produced)) or '(none)'}\n"
            "Fix the `tags:` input of the docker/metadata-action step rather "
            "than relaxing this check: a tag the documentation names and the "
            "registry lacks is worse than no tag.",
            file=sys.stderr,
        )
        return 1
    print(f"All {len(expected)} required tags are present:")
    for tag in sorted(expected):
        print(f"  {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
