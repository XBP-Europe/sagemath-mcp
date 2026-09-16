"""Which names does the corpus sweep actually refuse, and where do they live?

`tests/test_sage_doctest_corpus.py` reports refusals per *rule*, because that is
what the acceptance ceilings are written against. To reduce refusals you need
the other cut: per *name*, with the Sage module each name is defined in, so a
whole module's worth of refusals can be weighed against one star-export entry.

Run it inside the Sage container, from the repository root:

    docker exec sage-mcp bash -lc \\
        "cd /workspace && sage -python scripts/analyse_corpus_refusals.py"

It writes JSON to stdout (`--json`) or a readable ranking by default. Nothing is
asserted and no corpus text is printed beyond the refused name itself: the
corpus is GPL, this repository is MIT, and the sweep has always kept counts
only.
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
from sagemath_mcp._sage_worker import (
    _OFFERED_SHIM_NAMES,
    _auto_declarable_symbols,
)
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

# The rule this script exists for. Everything else is either a boundary we
# meant to draw (external programs, file writes) or too rare to chase.
UNOFFERED = re.compile(r"^'([^']+)' is not a name this server offers")


def refused_names(
    paths: list[Path],
) -> tuple[collections.Counter[str], collections.Counter[str]]:
    """Count, per name, how often the corpus asks for a name we do not offer.

    Also count refusals *attributable to a star import the block already made*.
    That second number is the one that matters for the star-export mechanism: a
    module is only worth admitting if the doctests reach its names by writing
    `from <module> import *`, which `rewrite_permitted_imports` can then expand.
    A name used bare, with no such import, needs a different fix entirely.
    """
    from sage.repl.preparse import preparse

    counts: collections.Counter[str] = collections.Counter()
    by_star: collections.Counter[str] = collections.Counter()
    for path in paths:
        for block in _docstrings(path):
            bound: set[str] = set()
            evaluated = False
            session_injected = False
            # Every module this block has star-imported, admitted or not.
            starred: list[str] = []
            for source in _examples(block):
                try:
                    prepared = preparse(source)
                    module = ast.parse(prepared)
                except (SyntaxError, ValueError, RecursionError, TypeError):
                    continue
                bound |= _bound_names(module)
                star = _STAR_IMPORT.match(source)
                if star:
                    starred.append(star.group(1))
                    if star.group(1) in STAR_EXPORTS:
                        bound |= STAR_EXPORTS[star.group(1)]
                session_injected = session_injected or injects_session_names(module)
                if evaluated:
                    bound.add("_")
                evaluated = True
                if _exclusion(source):
                    continue
                offered = frozenset(bound) | _OFFERED_SHIM_NAMES
                offered |= _auto_declarable_symbols(
                    module, offered | ALLOWED_CALLER_NAMES, frozenset()
                )
                try:
                    validate_module(
                        module,
                        code=prepared,
                        extra_allowed_names=offered,
                        session_injects_names=session_injected,
                    )
                except SecurityViolation as exc:
                    match = UNOFFERED.match(str(exc))
                    if match:
                        counts[match.group(1)] += 1
                        for module_name in starred:
                            if module_name not in STAR_EXPORTS:
                                by_star[module_name] += 1
                except RecursionError:
                    continue
    return counts, by_star


def provenance(names: list[str]) -> dict[str, str]:
    """Where each name is defined, read from the installed Sage.

    A name absent from `sage.all` is the interesting case: it is mathematics
    Sage documents through an internal module, which is exactly what the
    star-export mechanism exists to reach.
    """
    import sage.all

    found: dict[str, str] = {}
    for name in names:
        value = getattr(sage.all, name, None)
        if value is None:
            found[name] = "(not in sage.all)"
            continue
        module = getattr(value, "__module__", None)
        found[name] = module or f"(no __module__: {type(value).__name__})"
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--top", type=int, default=80, help="how many names to show")
    args = parser.parse_args()

    library = sage_library()
    if library is None:
        print("SageMath library not importable", file=sys.stderr)
        return 1
    sources = sorted(library.rglob("*.py")) + sorted(library.rglob("*.pyx"))
    counts, by_star = refused_names(sources)
    where = provenance([name for name, _ in counts.most_common(args.top)])

    if args.json:
        json.dump(
            {
                "total_refusals": sum(counts.values()),
                "distinct_names": len(counts),
                "names": [
                    {"name": name, "count": count, "defined_in": where.get(name, "?")}
                    for name, count in counts.most_common(args.top)
                ],
                "unadmitted_star_modules": [
                    {"module": module_name, "refusals_in_block": count}
                    for module_name, count in by_star.most_common(args.top)
                ],
            },
            sys.stdout,
            indent=2,
        )
        print()
        return 0

    print(f"{sum(counts.values())} refusals over {len(counts)} distinct names\n")
    print(f"{'count':>6}  {'name':<34} defined in")
    for name, count in counts.most_common(args.top):
        print(f"{count:>6}  {name:<34} {where.get(name, '?')}")

    print(
        "\n\nRefusals in blocks that star-imported a module we do not admit.\n"
        "This is what a star-export entry could actually recover:\n"
    )
    print(f"{'count':>6}  module")
    for module_name, count in by_star.most_common(args.top):
        print(f"{count:>6}  {module_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
