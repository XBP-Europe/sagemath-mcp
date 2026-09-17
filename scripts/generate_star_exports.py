"""Regenerate src/sagemath_mcp/star_exports.py from the installed SageMath.

Caller imports are refused by default. This file is the curated exception: a
hand-reviewed list of internal SageMath modules whose `from <module> import *`
is safe because every public name they export is ordinary mathematics. The
generator screens each candidate against the same danger basis the namespace
scrub uses (`_star_export_screen` in `_sage_worker.py`) and writes only the
modules that pass whole -- clean-modules-only, never a filtered subset.

    docker exec sage-mcp bash -lc 'cd /workspace && sage -python \
        scripts/generate_star_exports.py > /tmp/star_exports_new.py'
    docker exec sage-mcp cat /tmp/star_exports_new.py \
        > src/sagemath_mcp/star_exports.py

Write through a temporary file, never straight over star_exports.py: this
script imports the security policy, which imports star_exports. A shell
redirect truncates the file before the import runs.

The integration test `test_the_star_exports_match_this_sage` re-screens every
listed module and fails if the installed Sage disagrees -- a version that adds
a shell, compiler, pickle or file helper to a listed module fails the suite.

CANDIDATE_MODULES is the human-curated input. Adding one is a review step: it
is included only if the screen passes it, and the doctest corpus sweep is where
its value shows up. `sage.libs.ecl` is deliberately absent -- it screens clean
but `EclObject` evaluates Lisp, which the screen cannot see.

A module maps to the set of names it is PERMITTED to drop. Empty, the usual
case, means clean as a whole. A non-empty set is a reviewed exception: a
dangerous name in the set is dropped, a dangerous name outside it still fails
the module whole, and a listed name the module does not export simply goes
unused (the generator says so on stderr, because the two runtimes differ --
passagemath's `sage.matroids.advanced` re-exports no `lazy_import`). What each
runtime actually dropped is written into its own generated file, which is what
the drift test re-checks. See `_star_export_screen` and REVIEW_ACTIONS item 77.
"""

from __future__ import annotations

import sys
import textwrap

from sagemath_mcp._sage_worker import _star_export_screen

# Curated candidates: internal modules the doctest corpus star-imports and whose
# mathematics is otherwise unreachable. Each is admitted only if it screens
# clean as a whole; a comment records the corpus weight that motivated it.
CANDIDATE_MODULES: dict[str, frozenset[str]] = {
    "sage.rings.polynomial.real_roots": frozenset(),                       # 191
    "sage.matroids.lean_matrix": frozenset(),                              # 93
    "sage.graphs.graph_decompositions.modular_decomposition": frozenset(), # 87
    "sage.coding.binary_code": frozenset(),                                # 72
    "sage.combinat.sf.kfpoly": frozenset(),                                # 26
    "sage.modular.dims": frozenset(),                                      # 23
    "sage.schemes.elliptic_curves.weierstrass_morphism": frozenset(),      # 23
    "sage.libs.lcalc.lcalc_Lfunction": frozenset(),                        # 27
    "sage.plot.plot3d.shapes": frozenset(),                                # 19
    "sage.matroids.union_matroid": frozenset(),                            # 14
    "sage.modules.fp_graded.module": frozenset(),                          # 14
    "sage.combinat.dlx": frozenset(),                                      # 13
    "sage.rings.fraction_field_FpT": frozenset(),                          # 15
    # Re-admitted under item 63's drop-module-objects screen: each was dirty for
    # a re-exported module object alone (`real_roots`/`dims` were item-60 modules
    # item 61 dropped whole; `pbori` re-exports `operator`/`sage`). The module
    # objects are dropped, the mathematics is kept. Corpus star-import weight in
    # the comment. `sage.libs.ecl` stays out despite screening clean -- EclObject
    # evaluates Lisp, which no screen can see; curation, not the screen, keeps it
    # excluded.
    "sage.rings.polynomial.pbori.pbori": frozenset(),                      # 38
    "sage.rings.polynomial.pbori": frozenset(),                            # 11
    # Item 77. Sage's own public entry points for these areas re-export import
    # machinery next to the mathematics, and failing the module whole for it cost
    # the largest single block of corpus refusals left. Each drop is one name the
    # caller could never reach anyway: the scrub deletes it from the namespace
    # and the validator refuses it by name, so the drop removes nothing a caller
    # had. The number is the corpus refusals inside blocks that star-import the
    # module, measured by scripts/analyse_corpus_refusals.py.
    "sage.matroids.advanced": frozenset({"lazy_import"}),                  # 217
    "sage.combinat.matrices.latin": frozenset({"libgap"}),                 # 146
    "sage.graphs.generators.distance_regular": frozenset(                   # 36
        {"LazyImport", "libgap"}
    ),
}

HEADER = '''"""The `from <module> import *` statements caller code is allowed to keep.

Caller imports are refused by default (item 27): an import is how you get back
everything the namespace scrub removed. But a great deal of idiomatic Sage --
and 1,546 examples in SageMath's own doctests -- opens with a star import of an
*internal* module whose public names are all ordinary mathematics:
`from sage.matroids.lean_matrix import *`. Those names are not dangerous; they
are simply not what `sage.all` chose to export, so the namespace does not hold
them and the import is the only way to reach them.

This is the curated, reviewed exception. For each module here, every public
name passed the same danger screen the namespace scrub applies -- clean as a
whole or excluded entirely, never filtered. `rewrite_permitted_imports` expands
`from <module> import *` into the explicit list below before validation, so what
runs is exactly what was screened, and the names become the caller's to read
the way any name they bind does. Nothing is added to the allowlist and the
allowlist is never suspended.

Generated by scripts/generate_star_exports.py; checked against the installed
Sage by an integration test. Do not edit by hand -- a module that gains a
name reaching a shell, compiler, pickle or file belongs out of the curated
list, not filtered here.
"""

from __future__ import annotations

STAR_EXPORTS: dict[str, frozenset[str]] = {
'''

DROPS_HEADER = '''
#: Names a listed module exports that the screen deliberately did NOT export.
#:
#: Only ever import machinery re-exported next to the mathematics --
#: `lazy_import`, `libgap` -- which the namespace scrub deletes from the
#: namespace and the validator refuses by name, so dropping one removes nothing
#: a caller had. It is recorded rather than filtered silently: the drift test
#: re-screens each module permitting exactly these names, so a Sage that adds a
#: different dangerous export to a listed module fails the screen with the new
#: name instead of dropping it quietly. A module absent from here screened clean
#: as a whole on this runtime.
STAR_EXPORT_DROPS: dict[str, frozenset[str]] = {'''


def main() -> int:
    lines = [HEADER]
    drops: dict[str, frozenset[str]] = {}
    for module_name, expected_drops in CANDIDATE_MODULES.items():
        dropped: set[str] = set()
        screened = _star_export_screen(
            module_name, expected_drops=expected_drops, dropped_out=dropped
        )
        if not screened:
            print(f"skipped (screens dirty): {module_name}", file=sys.stderr)
            continue
        # What was permitted and what was needed differ per runtime:
        # passagemath's `sage.matroids.advanced` re-exports no `lazy_import` and
        # is clean as a whole there. Record what this runtime actually dropped,
        # and say so, rather than writing a permission the artifact does not use.
        if unused := expected_drops - dropped:
            print(
                f"note: {module_name} needed no drop for {sorted(unused)} on this "
                "runtime; the permission is unused here",
                file=sys.stderr,
            )
        if dropped:
            drops[module_name] = frozenset(dropped)
        names = textwrap.fill(
            ", ".join(f'"{name}"' for name in sorted(screened)),
            width=84,
            initial_indent="        ",
            subsequent_indent="        ",
        )
        lines.append(f'    "{module_name}": frozenset({{\n{names}\n    }}),')
    lines.append("}\n")
    lines.append(DROPS_HEADER)
    for module_name, expected_drops in sorted(drops.items()):
        listed = ", ".join(f'"{name}"' for name in sorted(expected_drops))
        lines.append(f'    "{module_name}": frozenset({{{listed}}}),')
    lines.append("}\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
