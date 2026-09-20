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
    # Item 78, the second pass over the same ranking. Each screens clean as a
    # whole -- no drop needed -- and each is mathematics a caller could ask for
    # rather than scaffolding. Nothing here is individually large; together they
    # are the rest of what the star-import mechanism can reach.
    "sage.tests.arxiv_0812_2725": frozenset(),                             # 31
    "sage.combinat.designs.gen_quadrangles_with_spread": frozenset(),      # 16
    "sage.manifolds.operators": frozenset(),                               # 15
    "sage.structure.set_factories": frozenset(),                           # 14
    "sage.structure.set_factories_example": frozenset(),                   # 14
    "sage.typeset.symbols": frozenset(),                                   # 12
    "sage.algebras.exterior_algebra_groebner": frozenset(),                # 8
    "sage.combinat.species.library": frozenset(),                          # 7
    "sage.schemes.toric.fano_variety": frozenset(),                        # 6
    "sage.matroids.transversal_matroid": frozenset(),                      # 6
    "sage.games.hexad": frozenset(),                                       # 5
    "sage.schemes.toric.chow_group": frozenset(),                          # 5
    "sage.quadratic_forms.genera.spinor_genus": frozenset(),               # 4
    "sage.rings.polynomial.pbori.interpolate": frozenset(),                # 4
    "sage.combinat.superpartition": frozenset(),                           # 3
    "sage.matroids.gammoid": frozenset(),                                  # 3
    "sage.modules.fp_graded.free_module": frozenset(),                     # 2
    "sage.rings.padics.padic_relaxed_errors": frozenset(),                 # 2
    "sage.combinat.cyclic_sieving_phenomenon": frozenset(),                # 1
    # Item 80, third pass. Item 78 concluded the remaining bucket was "mostly
    # boundaries rather than gaps"; that was measured by which modules screened
    # CLEAN, and never asked why the dirty ones were dirty. These six each fail
    # on exactly one re-exported helper -- the same case item 77 built the drop
    # mechanism for -- and carry real mathematics behind it. `pari` and
    # `get_verbose` join `lazy_import` and `libgap` as names the scrub deletes
    # and the validator refuses, so dropping one takes nothing from a caller.
    "sage.data_structures.stream": frozenset({"lazy_import"}),             # 12
    "sage.combinat.partition_algebra": frozenset({"lazy_import"}),         # 10
    "sage.combinat.knutson_tao_puzzles": frozenset({"lazy_import"}),       # 9
    "sage.rings.qqbar": frozenset({"lazy_import"}),                        # 5
    "sage.rings.complex_mpc": frozenset({"pari"}),                         # 5
    "sage.rings.polynomial.toy_buchberger": frozenset({"get_verbose"}),    # 5
    # `sage.combinat.designs.ext_rep` (9) is NOT admitted, though it would need
    # only `tmp_filename` and `dump_to_tmpfile` dropped. That module's purpose
    # is reading design data out of files and URLs, so it is the filesystem
    # boundary rather than mathematics behind an import helper -- the same call
    # `sage.misc.sageinspect` gets.
    # Screened clean and still excluded, by curation rather than by the screen --
    # the same call `sage.libs.ecl` gets. `sage.misc.sageinspect` (30) reads
    # source files and returns filesystem paths, which is the introspection the
    # policy withholds, not mathematics. `sage.symbolic.random_tests` (9),
    # `sage.structure.list_clone_timings_cy` (4) and `sage.misc.benchmark` (8)
    # are Sage's own test and timing scaffolding: admitting them would raise the
    # corpus number without giving a caller anything to compute with.
    # `sage.misc.nested_class` (3) exports `nested_pickle` and
    # `modify_for_nested_pickle`. `sage.structure.richcmp` (3) is comparison
    # infrastructure. The big remaining blocks stay refused on their merits:
    # `sage.misc.explain_pickle` (98) and `pickle`/`copyreg` (39) are pickle
    # machinery, `sage.libs.ecl` (87) evaluates Lisp, `sage.interfaces.rubik` (9)
    # spawns a program, and `gmpy2` (17) is not a Sage module at all.
    # Item 89, the first pass driven by the *module-reach* measurement rather
    # than the star-import one. `scripts/analyse_module_reach.py` showed that
    # 835 of the 1,090 refusals under the item-79 rule reach a name offered
    # nowhere at all -- so the refusal's advice, "name the function directly",
    # could not be followed. These are the modules behind the largest blocks of
    # that, each screening clean as a whole. The number is the module-reach
    # refusals, which these recover in the dotted spelling as well as the star
    # one, since `STAR_EXPORTS` now authorizes both.
    "sage.rings.ideal": frozenset(),                                       # 89
    "sage.structure.element": frozenset(),                                 # 36
    "sage.graphs.base.sparse_graph": frozenset(),                          # 38
    "sage.graphs.base.graph_backends": frozenset(),                        # 27
    "sage.graphs.base.dense_graph": frozenset(),                           # 25
    "sage.combinat.misc": frozenset(),                                     # 13
    "sage.graphs.genus": frozenset(),                                      # 10
    "sage.modular.pollack_stevens.fund_domain": frozenset(),               # 9
    "sage.graphs.cliquer": frozenset(),                                    # 7
    "sage.misc.mrange": frozenset(),                                       # 6
    "sage.combinat.free_dendriform_algebra": frozenset(),                  # 5
    "sage.modular.abvar.cuspidal_subgroup": frozenset(),                   # 5
    "sage.modular.modform.space": frozenset(),                             # 5
    "sage.modular.modsym.modsym": frozenset(),                             # 5
    "sage.rings.integer": frozenset(),                                     # 3
    "sage.functions.trig": frozenset(),                                    # 2
    "sage.groups.additive_abelian.additive_abelian_wrapper": frozenset(),  # 1
    # Screened CLEAN and still excluded, by curation. The screen reads a module
    # for code execution, not for what the mathematics is:
    #   `sage.env` (1) exports 75 names, and they are SAGE_ROOT, SAGE_SRC and
    #   the rest of the installation's filesystem layout. Nothing in it
    #   executes; all of it is the filesystem boundary the policy withholds.
    #   The same call `sage.misc.sageinspect` gets, and the clearest reminder
    #   that a clean screen is a floor and not the decision.
    #   `sage.symbolic.constants` (5) re-exports `unpickle_Constant` and
    #   `register_symbol` next to `pi` and `e`. The constants themselves are
    #   already offered by name, so admitting the module would add the pickle
    #   and symbol-table helpers and almost no mathematics.
    #   `sage.misc.weak_dict` (31), `sage.structure.dynamic_class` (10),
    #   `sage.structure.coerce_maps` (9) are data structures and metaclass
    #   plumbing; `sage.rings.tests` (16) is Sage's own test scaffolding, the
    #   same call `sage.symbolic.random_tests` got.
    #   `sage.manifolds.utilities` (23) is real mathematics but re-exports
    #   `latex`, which this server withholds by name and SECURITY.md documents
    #   as withheld. Admitting it would contradict the documentation, so it
    #   waits for a decision about `latex` rather than settling one quietly.
    #   `sage` itself (1) and `sage.combinat` (1) screen clean only because
    #   their package roots export almost nothing: `load_ipython_extension` and
    #   `getdoc`. Neither is mathematics.
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
