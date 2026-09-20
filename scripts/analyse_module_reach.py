"""How much of the `sage.<...>` refusal is a spelling, and how much is reach?

Item 79 closed a sandbox escape by refusing any attribute chain rooted at the
`sage` module: `sage.misc.persist.unpickle_global` was arbitrary code
execution, and the deny-by-default allowlist could not see it because `sage`
itself is an ordinary allowlisted name. The refusal costs 1,090 corpus
examples, the largest single bucket left, and the refusal message tells the
caller to "name the function directly".

For a chain whose leaf is a name the server *already offers*, that advice is
the whole story: `sage.rings.integer.Integer` and `Integer` are the same
object, so the dotted form asks for nothing the bare form does not already
give. Permitting exactly those chains would be capability-neutral -- not a
relaxation with a justification, but a spelling of something already allowed.

Whether that is worth building depends entirely on how many of the 1,090 are
that shape, which nobody has measured. This script measures it and asserts
nothing. Run it inside the Sage container, from the repository root:

    docker exec sage-mcp bash -lc \\
        "cd /workspace && sage -python scripts/analyse_module_reach.py"

Counts only; no corpus text beyond the dotted path itself.
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sagemath_mcp._artifacts import ALLOWED_CALLER_NAMES, STAR_EXPORTS
from sagemath_mcp._sage_worker import _OFFERED_SHIM_NAMES, _auto_declarable_symbols
from sagemath_mcp.security import (
    SecurityViolation,
    _bound_names,
    injects_session_names,
    validate_module,
)
from tests.test_sage_doctest_corpus import (
    _STAR_IMPORT,
    _docstrings,
    _examples,
    _exclusion,
    sage_library,
)

REACH = re.compile(r"^Reaching into the '([^']+)' module is not permitted")

#: Buckets, worst-to-best for the reader.
NOT_OFFERED = "not-offered"  # must stay refused: real reach
UNRESOLVABLE = "unresolvable"  # the path does not exist in this Sage
NEUTRAL = "capability-neutral"  # leaf IS an object the caller can already name
SHADOWED = "same-name-different-object"  # leaf shares a name but not identity


def _chains(module: ast.Module) -> list[str]:
    """Every maximal attribute chain rooted at a bare `sage`, as written."""
    found: list[str] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.Attribute):
            continue
        segments: list[str] = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            segments.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name) and current.id == "sage":
            # Maximal only: skip a chain that is itself the value of another.
            if any(c.startswith("sage." + ".".join(reversed(segments)) + ".") for c in found):
                continue
            found.append("sage." + ".".join(reversed(segments)))
    return found


def _resolve(path: str) -> object | None:
    """The object a dotted path names, or None. Imports submodules as needed."""
    import importlib

    segments = path.split(".")
    obj: object | None = None
    # Longest importable prefix first, then getattr the rest.
    for split in range(len(segments), 0, -1):
        try:
            obj = importlib.import_module(".".join(segments[:split]))
        except Exception:
            continue
        for segment in segments[split:]:
            try:
                obj = getattr(obj, segment)
            except AttributeError:
                return None
        return obj
    return None


def classify(path: str, offered: dict[str, object]) -> str:
    """Which bucket this chain falls in. `offered` maps bare name -> value."""
    leaf = path.rsplit(".", 1)[-1]
    resolved = _resolve(path)
    if resolved is None:
        return UNRESOLVABLE
    # Identity, not the name. `sage.rings.integer.Integer is Integer` is what
    # makes permitting the chain add nothing; the leaf happening to match some
    # offered name proves nothing, because names are reused across Sage.
    if any(value is resolved for value in offered.values()):
        return NEUTRAL
    if leaf in offered:
        return SHADOWED
    return NOT_OFFERED


def scan(paths: list[Path]) -> tuple[collections.Counter[str], int]:
    """Count, per dotted path, how often the corpus is refused for reaching."""
    from sage.repl.preparse import preparse

    counts: collections.Counter[str] = collections.Counter()
    total = 0
    for path in paths:
        for block in _docstrings(path):
            bound: set[str] = set()
            evaluated = False
            session_injected = False
            for source in _examples(block):
                try:
                    prepared = preparse(source)
                    module = ast.parse(prepared)
                except (SyntaxError, ValueError, RecursionError, TypeError):
                    continue
                bound |= _bound_names(module)
                star = _STAR_IMPORT.match(source)
                if star and star.group(1) in STAR_EXPORTS:
                    bound |= STAR_EXPORTS[star.group(1)]
                session_injected = session_injected or injects_session_names(module)
                if evaluated:
                    bound.add("_")
                evaluated = True
                if _exclusion(source):
                    continue
                names = frozenset(bound) | _OFFERED_SHIM_NAMES
                names |= _auto_declarable_symbols(module, names | ALLOWED_CALLER_NAMES, frozenset())
                try:
                    validate_module(
                        module,
                        code=prepared,
                        extra_allowed_names=names,
                        session_injects_names=session_injected,
                    )
                except SecurityViolation as exc:
                    if not REACH.match(str(exc)):
                        continue
                    total += 1
                    for chain in _chains(module) or ["(chain not recovered)"]:
                        counts[chain] += 1
                except RecursionError:
                    continue
    return counts, total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    import sage.all

    offered = {
        name: getattr(sage.all, name)
        for name in ALLOWED_CALLER_NAMES
        if hasattr(sage.all, name)
    }

    library = sage_library()
    if library is None:
        print("SageMath library not importable", file=sys.stderr)
        return 1
    sources = sorted(library.rglob("*.py")) + sorted(library.rglob("*.pyx"))
    counts, total = scan(sources)
    buckets: collections.Counter[str] = collections.Counter()
    per_bucket: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    for chain, count in counts.items():
        bucket = classify(chain, offered)
        buckets[bucket] += count
        per_bucket[bucket][chain] += count

    if args.json:
        json.dump(
            {
                "refusals": total,
                "buckets": dict(buckets),
                "chains": {b: dict(c) for b, c in per_bucket.items()},
            },
            sys.stdout,
            indent=2,
        )
        return 0

    print(f"{total} refusals by the module-reach rule, {len(counts)} distinct chains\n")
    print(f"{'count':>7}  bucket")
    for bucket, count in buckets.most_common():
        print(f"{count:>7}  {bucket}")
    for bucket in (NEUTRAL, SHADOWED, NOT_OFFERED, UNRESOLVABLE):
        if not per_bucket[bucket]:
            continue
        print(f"\n--- {bucket} ---")
        for chain, count in per_bucket[bucket].most_common(args.limit):
            print(f"{count:>7}  {chain}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
