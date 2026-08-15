"""Regenerate `_DANGEROUS_SAGE_NAME_LIST` in src/sagemath_mcp/_sage_worker.py.

The worker strips dangerous Sage helpers by name, from a list baked into the
source. The list is *derived* from `_DANGEROUS_SAGE_MODULES`, but it is baked
rather than computed at startup because computing it meant reading `__module__`
off every entry in Sage's namespace, and Sage's lazy imports resolve when you do
that: worker startup went from instant to 1.8 seconds, inside the caller's first
evaluation.

The cost of baking it is that adding a module to `_DANGEROUS_SAGE_MODULES` does
nothing until the list is regenerated -- which is exactly what happened when
`sage.misc.call` was added and `attrcall` stayed reachable. An integration test
catches the mismatch; this script is how you fix it.

Run it with `make denylist`. It works in two halves because the container mounts
the checkout read-only: the script runs *inside* Sage and prints the names it
derived, and the splice into the worker happens on the host. Review the diff --
each name removed from the namespace is one callers can no longer reach, and the
point of the exercise is that some of them should not have been reachable.
"""

from __future__ import annotations

import os
import re
import sys
import textwrap
from pathlib import Path

WORKER = Path(__file__).resolve().parents[1] / "src" / "sagemath_mcp" / "_sage_worker.py"
BLOCK = re.compile(
    r"(_DANGEROUS_SAGE_NAME_LIST: frozenset\[str\] = frozenset\(\{\n)(.*?)(\}\)\n)",
    re.DOTALL,
)


def emit() -> int:
    """Print the derived names, one per line. Runs inside Sage."""
    sys.path.insert(0, str(WORKER.parents[1]))
    from sagemath_mcp._sage_worker import _dangerous_sage_names

    derived = _dangerous_sage_names()
    if not derived:
        print("refusing to emit an empty list; is this running inside Sage?", file=sys.stderr)
        return 1
    print("\n".join(sorted(derived)))
    return 0


def apply(names_file: Path) -> int:
    """Splice the emitted names into the worker. Runs on the host."""
    derived = sorted(n for n in names_file.read_text(encoding="utf-8").split() if n)
    if not derived:
        print("refusing to write an empty list", file=sys.stderr)
        return 1

    source = WORKER.read_text(encoding="utf-8")
    match = BLOCK.search(source)
    if match is None:
        print("could not find _DANGEROUS_SAGE_NAME_LIST in the worker", file=sys.stderr)
        return 1

    before = set(re.findall(r'"([^"]+)"', match.group(2)))
    body = textwrap.fill(
        " ".join(f'"{name}",' for name in derived),
        width=96,
        initial_indent="    ",
        subsequent_indent="    ",
    )
    updated = source[: match.start(2)] + body + "\n" + source[match.end(2) :]
    temporary = WORKER.with_suffix(".py.new")
    temporary.write_text(updated, encoding="utf-8")
    os.replace(temporary, WORKER)

    added, removed = sorted(set(derived) - before), sorted(before - set(derived))
    print(f"{len(before)} -> {len(derived)} names")
    print(f"  added:   {added}" if added else "  added:   none")
    if removed:
        print(f"  removed: {removed}")
    return 0


def main() -> int:
    if "--emit" in sys.argv:
        return emit()
    index = sys.argv.index("--apply")
    return apply(Path(sys.argv[index + 1]))


if __name__ == "__main__":
    raise SystemExit(main())
