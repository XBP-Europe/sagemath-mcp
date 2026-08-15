#!/usr/bin/env python
"""Categorise every refusal the SageMath doctest corpus provokes.

`tests/test_sage_doctest_corpus.py` measures *how many* of SageMath's own
documented examples this server would refuse. This answers the question that
follows: **which of those refusals cost a mathematician their work?**

A refusal falls into one of four verdicts:

  deliberate-safe   the capability is genuinely dangerous, and the mathematics
                    behind it is reachable another way (an external CAS
                    interface whose computation Sage also does in-process)
  deliberate-costly the refusal is intended, and the idiom it blocks has no
                    equally natural spelling -- a decision worth revisiting
  over-block        ordinary code refused because a name that is dangerous as a
                    Sage global is unremarkable as a local or a method
  not-ours          nothing this server withheld: names the doctest itself
                    created at run time, or examples that trip a size limit

Run inside the Sage container:

    sage -python scripts/analyse_doctest_refusals.py

The corpus is SageMath's, GPL-2.0-or-later, read at run time and never copied
into this repository. See tests/test_sage_doctest_corpus.py for the provenance
note in full.
"""

from __future__ import annotations

import ast
import collections
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
logging.disable(logging.CRITICAL)

from sagemath_mcp.security import SecurityViolation, _bound_names, validate_module  # noqa: E402
from tests.test_sage_doctest_corpus import (  # noqa: E402
    _docstrings,
    _examples,
    _exclusion,
    sage_library,
)

NAME_IN_MESSAGE = re.compile(r"'([^']+)'")


def called_as_a_global(name: str, source: str) -> bool:
    """Is this the dangerous global being called, or a method of the same name?

    `gap(...)` spawns GAP. `x.trace()` is the trace of a matrix. Both produce the
    same refusal, and only the first one has a security justification, so the dot
    is what separates a deliberate block from an over-block.
    """
    return bool(re.search(rf"(?<![.\w]){re.escape(name)}\s*\(", source))

# The external computer algebra systems. Each is blocked because Sage's
# interface spawns the real program and hands it a string, and those programs
# have shell escapes; each computation is also available in-process.
CAS_INTERFACES = {
    "gp", "pari", "maxima", "singular", "gap", "gap3", "Gap", "magma", "Magma",
    "macaulay2", "maple", "mathematica", "mathics", "matlab", "octave", "scilab",
    "axiom", "fricas", "giac", "kash", "lisp", "mupad", "polymake", "sage0", "lie",
    "r", "ecm", "ECM", "frobby", "regina", "genus2reduction", "qepcad", "qepcad_formula",
    "gfan", "kenzo", "phc", "tachyon", "four_ti_2", "latte", "normaliz",
}

# The REPL's own plumbing: session state, verbosity, source search, attachment.
# None of it computes anything.
REPL_PLUMBING = {
    "set_verbose", "get_verbose", "import_statements", "search_src", "search_doc",
    "search_def", "attached_files", "load_attach_path", "load_attach_mode", "reset",
    "restore", "attach", "detach", "edit", "trace", "browse", "banner", "quit", "exit",
    "sage_input", "explain_pickle", "install_doc", "version", "interact", "input_box",
    "input_grid", "text_control", "slider", "range_slider", "checkbox", "selector",
}

# Output and rendering. `latex` is the interesting one: it builds a string and
# writes nothing, unlike `view`, `show` and `html` beside it.
RENDERING = {"latex", "view", "show", "html", "pretty_print", "animate", "print_or_typeset"}

# Persistence and the filesystem, which callers do not get.
PERSISTENCE = {"save", "load", "dumps", "loads", "db", "db_save", "save_session",
               "load_session", "sageobj", "get_remote_file", "open", "tmp_filename",
               "tmp_dir", "cython", "cython_lambda", "fortran", "sh"}


def verdict_for_name(name: str, live: set[str]) -> tuple[str, str]:
    """(verdict, bucket) for a name this server would not let a caller read."""
    if name in CAS_INTERFACES:
        return "deliberate-safe", "external CAS interface"
    if name in REPL_PLUMBING:
        return "deliberate-safe", "REPL plumbing"
    if name in PERSISTENCE:
        return "deliberate-safe", "persistence / filesystem / compiler"
    if name in RENDERING:
        return ("deliberate-costly" if name == "latex" else "deliberate-safe",
                "rendering and display")
    if name == "_":
        return "deliberate-costly", "the REPL's previous-result name"
    if name in live:
        return "over-block", "exists in SageMath, offered by nobody"
    return "not-ours", "created by the doctest at run time"


def main() -> int:
    import sage.all
    from sage.repl.preparse import preparse

    live = set(dir(sage.all))
    library = sage_library()
    if library is None:
        print("SageMath library not importable", file=sys.stderr)
        return 2

    verdicts: collections.Counter = collections.Counter()
    buckets: collections.Counter = collections.Counter()
    names: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    samples: dict[str, list[str]] = collections.defaultdict(list)
    total = 0

    sources = sorted(library.rglob("*.py")) + sorted(library.rglob("*.pyx"))
    for path in sources:
        for block in _docstrings(path):
            bound: set[str] = set()
            for source in _examples(block):
                try:
                    prepared = preparse(source)
                    module = ast.parse(prepared)
                except (SyntaxError, ValueError, RecursionError, TypeError):
                    continue
                bound |= _bound_names(module)
                if _exclusion(source):
                    continue
                try:
                    validate_module(module, code=prepared,
                                    extra_allowed_names=frozenset(bound))
                    continue
                except SecurityViolation as exc:
                    message = str(exc)
                except RecursionError:
                    continue

                total += 1
                found = NAME_IN_MESSAGE.search(message)
                name = found.group(1) if found else ""

                if message.startswith(("Sage code exceeds", "Sage code is too",
                                       "Sage code has too")):
                    verdict, bucket = "not-ours", "example larger than the input limit"
                elif "is not a name this server offers" in message:
                    verdict, bucket = verdict_for_name(name, live)
                elif "is not defined. This server predefines" in message:
                    verdict, bucket = verdict_for_name(name, live)
                elif "dunder" in message:
                    verdict, bucket = "deliberate-safe", "dunder access"
                elif "writing files is not available" in message:
                    verdict, bucket = "deliberate-safe", "persistence / filesystem / compiler"
                elif message.startswith(("Import statements", "Relative imports",
                                         "Importing")):
                    verdict, bucket = "deliberate-safe", "imports"
                elif message.startswith(("Global statements", "Nonlocal statements")):
                    verdict, bucket = "deliberate-safe", "global / nonlocal statement"
                elif "Access through" in message or "forbidden module" in message:
                    # A module traversal, unless the name is simply a variable.
                    verdict, bucket = (
                        ("deliberate-safe", "module traversal")
                        if re.search(rf"(?<![.\w]){re.escape(name)}\.", source)
                        else ("over-block", "forbidden global shadowing a local")
                    )
                elif name in {"attrcall", "attrgetter", "methodcaller", "itemgetter",
                              "raw_getattr", "getattr_debug", "call_method",
                              "AttrCallObject", "sage_eval", "preparse", "eval", "exec",
                              "compile", "getattr", "setattr", "globals", "locals",
                              "vars", "open", "__import__", "input"}:
                    # String-path attribute access and the evaluation primitives,
                    # unless the doctest is using the word as its own variable.
                    verdict, bucket = (
                        ("deliberate-safe", "string-path attribute access / eval")
                        if called_as_a_global(name, source)
                        else ("over-block", "forbidden global shadowing a local")
                    )
                elif name in CAS_INTERFACES | PERSISTENCE | REPL_PLUMBING | RENDERING:
                    verdict, bucket = (
                        ("deliberate-safe", "dangerous global, called as one")
                        if called_as_a_global(name, source)
                        else ("over-block", "a method or variable of the same name")
                    )
                else:
                    verdict, bucket = "over-block", "forbidden global shadowing a local"

                verdicts[verdict] += 1
                buckets[(verdict, bucket)] += 1
                if name:
                    names[bucket][name] += 1
                if len(samples[bucket]) < 4:
                    samples[bucket].append(f"{path.name}: {source[:88]}")

    print(f"\n=== {total} refusals, categorised ===\n")
    order = ["over-block", "deliberate-costly", "deliberate-safe", "not-ours"]
    for verdict in order:
        count = verdicts[verdict]
        print(f"{verdict:>18}  {count:>6}  {100*count/max(total,1):5.1f}%")

    print("\n--- by bucket ---")
    for (verdict, bucket), count in sorted(buckets.items(), key=lambda kv: -kv[1]):
        print(f"\n  [{verdict}] {bucket}: {count} ({100*count/max(total,1):.1f}%)")
        top = ", ".join(f"{n}({c})" for n, c in names[bucket].most_common(12))
        if top:
            print(f"      names: {top}")
        for sample in samples[bucket][:2]:
            print(f"      e.g.   {sample}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
