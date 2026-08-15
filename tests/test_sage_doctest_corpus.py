"""SageMath's own doctests, run against this server's validator.

**Provenance.** The corpus here is not ours and is not in this repository. It is
SageMath's own doctest suite, read at run time out of the SageMath installation
the tests are running against — `sage/**/*.py` and `*.pyx`, the `sage: ` examples
in their docstrings. SageMath is Copyright (C) The Sage Development Team and is
licensed **GPL-2.0-or-later**; this project is MIT. Nothing derived from it is
copied into this tree, committed, or redistributed: the harvest happens in
memory, inside the container, and only *counts* survive into the assertions
below. That is why the baselines are numbers rather than lists of snippets, and
why a failure prints its examples instead of storing them.

    https://www.sagemath.org/  --  https://github.com/sagemath/sage

**Why this suite exists.** `test_math_coverage.py` asserts that mathematics
works, against a table written by hand: ~19 preparser forms, ~60 truths, ~30
binding forms. That table is only as good as what somebody thought to type, and
the two most recent policy defects — `f(x) = x^2 + 1` refused because the
preparser writes `__tmp__`, and `import` refused with a message no model could
act on — were both forms nobody had written down.

SageMath's doctests are the largest corpus of *idiomatic Sage that is known to be
correct* in existence: 334,000 examples in the `.py` sources alone, written by
the people who designed the syntax, covering every corner of the library. Run
through `preparse` + `validate_module` they answer one question at scale —
**would this server refuse the mathematics Sage itself documents?** — and they
answer it in about a minute.

**What is deliberately out of scope.** Roughly an eighth of the corpus uses
capabilities this server does not offer and will not: imports, `save`/`load` and
the rest of persistence, file paths, the external CAS interfaces, `%` magics,
network access, and examples tagged `# optional`/`# needs` for packages that may
not be installed. Those are classified and counted, not asserted over. The
mathematics they contain is separately proven reachable by
`test_the_blocked_interfaces_do_not_block_the_mathematics` below, which is the
question that actually matters: *is a scrubbed name costing anyone their work?*
"""

from __future__ import annotations

import ast
import collections
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sagemath_mcp.config import SageSettings
from sagemath_mcp.security import SecurityViolation, _bound_names, validate_module
from sagemath_mcp.session import SageSession

requires_sage = pytest.mark.skipif(
    shutil.which("sage") is None, reason="Sage executable not available"
)

# --- harvest ------------------------------------------------------------------

_PROMPT = re.compile(r"^(\s*)sage:\s?(.*)$")
_CONTINUATION = re.compile(r"^(\s*)\.\.\.\.:\s?(.*)$")
# Cython sources cannot be parsed with `ast`, so their docstrings are found by
# their quotes. Coarser than the AST, and it only has to delimit a namespace.
_PYX_DOCSTRING = re.compile(r'"""(.*?)"""', re.DOTALL)

# Capabilities this server does not offer, by design. A doctest that uses one is
# out of scope: it is not evidence about the mathematics.
EXCLUSIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("import", re.compile(r"^\s*(import|from)\s+\w")),
    ("persistence", re.compile(r"\b(save|load|attach|dumps|loads|db|save_session|"
                               r"load_session|sage_input|explain_pickle)\s*\(")),
    ("filesystem", re.compile(r"\b(open|tmp_filename|tmp_dir|SAGE_TMP|os\.|shutil\.|"
                              r"pathlib|\.write_to_|\.savefig|write\()")),
    ("interfaces", re.compile(r"\b(gp|maxima|singular|gap|magma|mathematica|maple|"
                              r"matlab|octave|macaulay2|sage0|lie|mwrank|polymake|"
                              r"fricas|giac|kash|axiom|mupad|scilab|lisp|regina)"
                              r"\s*\(\s*['\"]")),
    ("shell-or-eval", re.compile(r"\b(eval|exec|compile|sage_eval|preparse|cython|"
                                 r"fortran|sh|getattr|setattr|globals|locals|vars)\s*\(")),
    ("network", re.compile(r"\b(oeis|get_remote_file|urlopen|requests\.)")),
    ("display", re.compile(r"\b(show|view|browse|html|pretty_print|interact|"
                           r"animate)\s*\(")),
    ("repl-magic", re.compile(r"^\s*(%|!|\?|help\(|search_src|search_doc|"
                              r"sage\.|reset\(|restore\()")),
    ("optional-tag", re.compile(r"#\s*(optional|needs|known bug|not implemented|"
                                r"not tested)")),
    # Python protocol rather than mathematics: `I.__repr__()`, `key.__getitem__`.
    # Dunder access is refused outright and that rule is load-bearing.
    ("dunder", re.compile(r"__\w+__")),
)


@dataclass
class Harvest:
    """What the corpus did when pushed through the validator."""

    files: int = 0
    blocks: int = 0
    examples: int = 0
    accepted: int = 0
    refused: int = 0
    excluded: int = 0
    unparsed: int = 0
    reasons: collections.Counter = field(default_factory=collections.Counter)
    samples: dict[str, list[str]] = field(default_factory=lambda: collections.defaultdict(list))

    @property
    def in_scope(self) -> int:
        return self.accepted + self.refused

    @property
    def acceptance(self) -> float:
        return self.accepted / self.in_scope if self.in_scope else 0.0

    def report(self, limit: int = 12) -> str:
        lines = [
            f"{self.files} files, {self.blocks} docstrings, {self.examples} examples",
            f"accepted {self.accepted}, refused {self.refused}, excluded {self.excluded}, "
            f"acceptance {self.acceptance:.4%}",
        ]
        for reason, count in self.reasons.most_common(limit):
            lines.append(f"  {count:>6}  {reason}")
            for sample in self.samples.get(reason, [])[:2]:
                lines.append(f"          e.g. {sample}")
        return "\n".join(lines)


def sage_library() -> Path | None:
    """Where the running SageMath keeps its sources, or None."""
    try:
        import sage
    except ImportError:  # pragma: no cover - integration only
        return None
    path = Path(sage.__file__).resolve().parent
    return path if path.is_dir() else None


def _docstrings(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if "sage: " not in text:
        return []
    if path.suffix == ".pyx":
        return [block for block in _PYX_DOCSTRING.findall(text) if "sage: " in block]
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            docstring = ast.get_docstring(node, clean=False)
            if docstring and "sage: " in docstring:
                found.append(docstring)
    return found


def _examples(block: str) -> list[str]:
    """The input statements of one docstring, continuations folded in.

    A docstring is one namespace: Sage runs its examples in order against a
    shared scope, which is what makes them a fair model of a session here.
    """
    statements: list[str] = []
    current: list[str] | None = None
    for line in block.splitlines():
        prompt = _PROMPT.match(line)
        continuation = _CONTINUATION.match(line)
        if prompt:
            if current:
                statements.append("\n".join(current))
            current = [prompt.group(2)]
        elif continuation and current is not None:
            current.append(continuation.group(2))
        elif current:
            statements.append("\n".join(current))
            current = None
    if current:
        statements.append("\n".join(current))
    return [statement for statement in statements if statement.strip()]


def _exclusion(source: str) -> str | None:
    for label, pattern in EXCLUSIONS:
        if pattern.search(source):
            return label
    return None


def _generalise(message: str) -> str:
    """Collapse a refusal to its rule, so counts are per-rule not per-instance.

    Names and numbers both have to go: "exceeds maximum length (15396 > 8000)"
    is one rule, and leaving the count in made every oversized example its own
    unaccounted-for rule.
    """
    collapsed = re.sub(r"'[^']*'", "'X'", message)
    return re.sub(r"\d+", "N", collapsed).split(".")[0][:88]


def harvest(paths: list[Path]) -> Harvest:
    """Push every doctest example in *paths* through preparse + validate."""
    from sage.repl.preparse import preparse

    result = Harvest()
    for path in paths:
        result.files += 1
        for block in _docstrings(path):
            result.blocks += 1
            # Names the block has created so far. Collected from *every*
            # example including the excluded ones: `from x import y` is out of
            # scope, and it still names something the next line reads. Dropping
            # those bindings made ordinary code look refused.
            bound: set[str] = set()
            evaluated = False
            for source in _examples(block):
                result.examples += 1
                try:
                    prepared = preparse(source)
                    module = ast.parse(prepared)
                except (SyntaxError, ValueError, RecursionError, TypeError):
                    result.unparsed += 1
                    continue
                bound |= _bound_names(module)
                if evaluated:
                    # The worker binds `_` to the previous result, as the Sage
                    # REPL does, so every example after the first in a block can
                    # read it. Without this the sweep reports 694 refusals for a
                    # name that works in any real session.
                    bound.add("_")
                evaluated = True
                label = _exclusion(source)
                if label:
                    result.excluded += 1
                    result.reasons[f"excluded:{label}"] += 1
                    continue
                try:
                    validate_module(
                        module, code=prepared, extra_allowed_names=frozenset(bound)
                    )
                    result.accepted += 1
                except SecurityViolation as exc:
                    result.refused += 1
                    reason = f"refused:{_generalise(str(exc))}"
                    result.reasons[reason] += 1
                    if len(result.samples[reason]) < 3:
                        result.samples[reason].append(f"{path.name}: {source[:90]}")
                except RecursionError:
                    result.unparsed += 1
    return result


@pytest.fixture(scope="module")
def corpus() -> Harvest:
    """One sweep of the whole library, shared by every test that reads it."""
    library = sage_library()
    if library is None:  # pragma: no cover - integration only
        pytest.skip("SageMath library not importable")
    sources = sorted(library.rglob("*.py")) + sorted(library.rglob("*.pyx"))
    if len(sources) < 500:  # pragma: no cover - integration only
        pytest.skip(f"only {len(sources)} Sage sources found; not a full installation")
    return harvest(sources)


# --- the assertions -----------------------------------------------------------
#
# Baselines measured against SageMath 10.9 (2026-08-15): 3,168 sources, 60,094
# docstrings, 432,878 examples, of which 369,168 accepted, 5,260 refused and
# 58,268 out of scope -- 98.60% acceptance among in-scope examples, in 48s.
# They carry margin because a Sage upgrade moves them, and a *drop* is the
# signal. To refresh after an upgrade, call harvest() over the library and read
# report(); a failing assertion prints it too.
#
# The first measurement was 97.81%, with 8,218 refusals. Item 46 removed 2,958
# of them -- 36% -- by releasing everything the policy blocked without a security
# reason: `latex`, `operator.le`, the REPL's `_`, every name that is dangerous as
# a Sage global and unremarkable as a local or a method, and the four evaluation
# primitives whose *identifiers* mathematics uses (`eval` for an eigenvalue,
# `vars` for a list of variables, `input` for an automaton's word, `locals` for
# a dictionary) while their attribute forms stay refused. Two names were added to
# the allowlist to achieve all of it: `latex` and `operator`.

MINIMUM_EXAMPLES = 250_000
MINIMUM_ACCEPTANCE = 0.985


@requires_sage
def test_the_corpus_is_the_whole_library(corpus: Harvest) -> None:
    """A harvest that silently stopped finding examples would pass everything else.

    The same guard as `test_this_suite_cannot_quietly_shrink`: the danger with a
    generated corpus is not that it fails, it is that it evaporates. A Sage
    layout change, a rename, an exception swallowed in the walker — any of them
    turn this suite into a very fast no-op.
    """
    assert corpus.examples >= MINIMUM_EXAMPLES, corpus.report()
    assert corpus.blocks >= 30_000, corpus.report()
    # Cython sources carry the core arithmetic -- Integer, Rational, matrices,
    # polynomials -- and they are found by a different code path to the .py
    # files, so their absence needs its own assertion.
    assert corpus.files >= 3_000, corpus.report()
    # Almost everything must parse. A jump here means the preparser contract
    # changed under us, not that Sage started writing invalid Python.
    assert corpus.unparsed / corpus.examples < 0.01, corpus.report()


@requires_sage
def test_this_server_accepts_the_mathematics_sagemath_documents(corpus: Harvest) -> None:
    """The headline: how much of Sage's own idiom would this server refuse?

    Measured at 98.60%, and the remaining 1.40% is itemised by the test below.
    This is the assertion that would have caught `f(x) = x^2 + 1`: that form
    appears about 1,400 times in the corpus, and refusing it moves this number
    by half a percent — silently, in a suite that only tests what someone
    remembered to write down.
    """
    assert corpus.acceptance >= MINIMUM_ACCEPTANCE, corpus.report(20)
    assert corpus.accepted >= 250_000, corpus.report()


# Every rule that may refuse a corpus example, and the ceiling for each as a
# share of in-scope examples. A rule that is missing here has started firing on
# ordinary mathematics and the test says so by name -- which is the point.
#
# All of them are deliberate now: capabilities the corpus reaches for and this
# server does not offer. Item 46 emptied the three that used to be recorded as
# debt -- see the note beside them, and REVIEW_ACTIONS.md items 45 and 46.
DELIBERATE_RULES: dict[str, float] = {
    "refused:'X' is not a name this server offers": 0.013,
    "refused:'X' is not defined": 0.003,
    "refused:Call to forbidden function 'X' is blocked": 0.001,
    "refused:Access through 'X' is blocked ('X' is not permitted in Sage executions)": 0.001,
    "refused:Access to dunder name 'X' is blocked": 0.001,
    "refused:Access to dunder attribute 'X' is blocked": 0.001,
    "refused:Access to 'X' is blocked: writing files is not available to caller code": 0.001,
    "refused:Reference to forbidden module 'X' is blocked": 0.001,
    "refused:Import statements are disabled for Sage executions": 0.001,
    "refused:Global statements are not permitted in Sage executions": 0.001,
    "refused:Nonlocal statements are not permitted in Sage executions": 0.001,
    "refused:Relative imports are disabled for Sage executions": 0.001,
    "refused:Importing 'X' is blocked ('X' is not permitted in Sage executions)": 0.001,
    # The size limits. Three examples in the corpus trip them, all of them
    # literal data tables -- DES test vectors, a 27x27 matrix written out.
    "refused:Sage code exceeds maximum length": 0.001,
    "refused:Sage code is too deeply nested": 0.001,
    "refused:Sage code has too many AST nodes": 0.001,
    # `latex` may be called and not reached into: `latex(obj)` builds a string,
    # while `latex.has_file(name)` runs `call("kpsewhich %s" % name, shell=True)`
    # and executed a command as the container user on 10.9. The corpus reaches
    # for `latex.extra_preamble` and `latex.has_file` in about 56 examples, all
    # of them typesetting rather than mathematics.
    "refused:'X' may be called but not reached into": 0.001,
    # These three were the shadowing class, and item 46 emptied them: 575
    # refusals became 5 in 432,878 examples. What is left is `open`, `exec`,
    # `compile`, `globals` and `getattr` -- primitives with no mathematical use,
    # `getattr` because Sage needs it in the builtins and it is therefore
    # genuinely reachable.
    "refused:Reference to forbidden name 'X' is blocked": 0.0002,
    "refused:Access to forbidden function 'X' is blocked": 0.0002,
    "refused:Call to forbidden attribute 'X' is blocked": 0.0002,
}

# The three rules item 46 emptied of the shadowing class. Named separately so
# the test below can hold them empty without loosening anything else.
SHADOWING_RULES: tuple[str, ...] = (
    "refused:Reference to forbidden name 'X' is blocked",
    "refused:Access to forbidden function 'X' is blocked",
    "refused:Call to forbidden attribute 'X' is blocked",
)


@requires_sage
def test_every_refusal_is_a_rule_we_meant_to_write(corpus: Harvest) -> None:
    """No refusal may come from a rule nobody accounted for.

    The share matters less than the identity. A new rule appearing here, or a
    known one doubling, is a policy change that has started refusing mathematics
    that SageMath itself ships as documentation — which is exactly the failure
    the security suite cannot see, because every test in it asserts a refusal.
    """
    ceilings = dict(DELIBERATE_RULES)
    unexpected: list[str] = []
    exceeded: list[str] = []

    for reason, count in corpus.reasons.items():
        if not reason.startswith("refused:"):
            continue
        share = count / corpus.in_scope
        ceiling = next(
            (limit for rule, limit in ceilings.items() if reason.startswith(rule)), None
        )
        if ceiling is None:
            unexpected.append(f"{reason}  ({count} examples)\n"
                              f"      e.g. {corpus.samples[reason][:2]}")
        elif share > ceiling:
            exceeded.append(f"{reason}: {share:.4%} > {ceiling:.4%} ({count} examples)\n"
                            f"      e.g. {corpus.samples[reason][:2]}")

    assert not unexpected, (
        "a rule nobody accounted for is refusing SageMath's own documented "
        "mathematics:\n  " + "\n  ".join(unexpected)
    )
    assert not exceeded, (
        "a refusal rule has started firing much more widely than it did:\n  "
        + "\n  ".join(exceeded)
    )


@requires_sage
def test_the_shadowing_rules_stay_emptied(corpus: Harvest) -> None:
    """The three rules item 46 emptied, held empty.

    They fired 575 times before: `A.trace()` is the trace of a matrix,
    `l.remove(x)` is a list, and `db`, `gap`, `maxima` and `sh` are what people
    call their variables. All of it came from names that are dangerous as Sage
    globals and unremarkable in the position they were actually used.

    Five refusals remain in 432,878 examples, and they are `open`, `exec`,
    `compile`, `globals` and `getattr` -- primitives with no mathematical use.
    `eval`, `vars`, `locals` and `input` were released as *identifiers* once
    their absence from builtins, namespace and allowlist was asserted rather
    than assumed; they stay refused as attributes, which is where `latex.eval()`
    lives.

    A rise here means the shadowing class has come back.
    """
    shadowing = sum(
        count
        for reason, count in corpus.reasons.items()
        if any(reason.startswith(rule) for rule in SHADOWING_RULES)
    )
    share = shadowing / corpus.in_scope
    assert share < 0.0002, (
        f"the shadowing rules now cover {share:.4%} of the corpus, up from 0.0013%:\n"
        f"{corpus.report(20)}"
    )


# --- the question the exclusions raise ----------------------------------------


@requires_sage
@pytest.mark.asyncio
async def test_the_blocked_interfaces_do_not_block_the_mathematics() -> None:
    """A scrubbed name is only acceptable if the mathematics survives it.

    The corpus sweep says the names this server refuses are, almost entirely,
    the external CAS interfaces and the REPL's own plumbing. That is a statement
    about names, and on its own it would be a comfortable way to miss the real
    question: `singular`, `gap`, `pari` and `maxima` are how a mathematician
    reaches Gröbner bases, character tables, class numbers and integration.

    They are blocked because each one spawns the real program and hands it a
    string, and those programs have shell escapes. What makes that acceptable is
    that Sage computes all of it in-process as well: the interface is a
    spelling, not a capability. Each case below is the mathematics behind a
    blocked name, done the way that works — and if any of these ever fails, the
    scrub has started costing someone their work.
    """
    session = SageSession("corpus-native", SageSettings(force_python_worker=False,
                                                        eval_timeout=120.0))

    async def value(code: str) -> str:
        result = await session.evaluate(code, want_latex=False, capture_stdout=False)
        return (result.result or "").strip()

    try:
        # singular: Gröbner bases and primary decomposition, in-process.
        await value("R.<u,v> = QQ[]\nI = R.ideal([u^2 + v^2 - 1, u - v])")
        assert await value("I.groebner_basis()") == "[v^2 - 1/2, u - v]"
        assert await value("I.dimension()") == "0"

        # maxima: integration, limits, ODEs, factoring, solving.
        assert "cos(2*x)" in await value("integrate(sin(x)^2*exp(-x), x)")
        assert await value("limit((1 + 1/x)^x, x=oo)") == "e"
        assert await value("(x^3 - 1).factor()") == "(x^2 + x + 1)*(x - 1)"
        assert "x == 2" in await value("solve(x^4 - 5*x^2 + 4 == 0, x)")

        # pari: class numbers, factoring, unit groups, elliptic curve ranks.
        # (`qfbclassno` itself is not an allowlist gap -- SageMath 10.9 no
        # longer exports it at all, and the class number is asked for this way.)
        assert await value("QuadraticField(-23).class_number()") == "3"
        assert await value("(2^61 - 1).is_prime()") == "True"
        assert await value("EllipticCurve('389a').rank()") == "2"
        await value("K.<a> = NumberField(x^3 - 2)")
        assert await value("K.class_number()") == "1"
        assert "C2 x Z" in await value("K.unit_group()")

        # gap: group theory, including the in-process libgap.
        await value("G = SymmetricGroup(5)")
        assert await value("G.order()") == "120"
        assert await value("len(G.conjugacy_classes())") == "7"
        assert await value("G.sylow_subgroup(5).order()") == "5"
        assert await value("libgap(5).Factorial()") == "120"

        # r: distributions, moments, fitting.
        assert await value("mean([1, 2, 3, 4, 5])") == "3"
        assert float(await value(
            "T = RealDistribution('gaussian', 1)\nfloat(T.cum_distribution_function(1.96))"
        )) == pytest.approx(0.975, abs=1e-3)

        # latex: the one blocked name with no equally natural spelling. `latex(e)`
        # is refused and the method behind it is not, so the mathematics is
        # reachable and the idiom is not -- which is why this is a live question
        # rather than a settled one. See REVIEW_ACTIONS.md item 45.
        assert await value("(x^2 + 1)._latex_()") == "'x^{2} + 1'"
        assert "begin{array}" in await value("matrix(QQ, [[1,2],[3,4]])._latex_()")
    finally:
        await session.shutdown()


@requires_sage
@pytest.mark.asyncio
async def test_the_mathematics_behind_an_import_is_still_reachable() -> None:
    """The last bucket, and the last chance for mathematics to be left behind.

    1,818 of the corpus's refusals are names that are not in `sage.all` at all.
    They divide three ways: names the doctest invented at run time, Sage's own
    test plumbing, and -- the part that matters -- 138 names, 538 uses, of real
    mathematics that lives in a submodule and is reachable in Sage only behind
    an import. This server has no imports, so if that mathematics were reachable
    no other way it would be genuinely lost.

    It is not. Almost all of those names are Sage's *internal* spelling, and the
    user-facing path to the same mathematics is exported by `sage.all` and
    offered here: `real_roots` is `p.roots(ring=RR)`, `BasisMatroid` is
    `Matroid(...)`, `BinaryCode` is `codes.*`, `dimension_cusp_forms` is a method
    on `Gamma0(N)`, `modular_decomposition` is a method on a graph. That is the
    same boundary a Sage user meets at the prompt before they type an import.

    Each line below is a name from that bucket, computed the way it is reachable.
    A failure here means a door closed that this argument assumed was open.
    """
    session = SageSession("corpus-imports", SageSettings(force_python_worker=False,
                                                         eval_timeout=180.0))

    async def value(code: str) -> str:
        result = await session.evaluate(code, want_latex=False, capture_stdout=False)
        return (result.result or "").strip()

    try:
        # real_roots, mk_ibpi, root_bounds -- sage.rings.polynomial.real_roots
        await value("R.<u> = PolynomialRing(ZZ)\np = u^5 - 3*u + 1")
        assert await value("p.number_of_real_roots()") == "3"
        roots = await value("p.roots(ring=RR, multiplicities=False)")
        assert len(roots.split(",")) == 3, roots

        # BasisMatroid, LinearMatroid, MinorMatroid, RankMatroid -- sage.matroids
        await value("M = Matroid(matrix(GF(2), [[1,0,0,1,1],[0,1,0,1,0],[0,0,1,0,1]]))")
        assert await value("M.rank()") == "3"
        assert await value("M.bases_count()") == "8"
        assert await value("M.minor(contractions=[0]).rank()") == "2"
        assert await value("matroids.Uniform(2, 4).is_connected()") == "True"

        # BinaryCode, PartitionStack -- sage.coding
        assert await value(
            "C = codes.HammingCode(GF(2), 3)\n"
            "(C.length(), C.dimension(), C.minimum_distance())"
        ) == "(7, 4, 3)"

        # dimension_cusp_forms, dimension_eis, dimension_modular_forms
        assert await value("Gamma0(11).dimension_cusp_forms(2)") == "1"
        assert await value("Gamma0(11).dimension_modular_forms(2)") == "2"
        assert await value("Gamma0(11).dimension_eis(2)") == "1"

        # modular_decomposition, print_md_tree -- sage.graphs.graph_decompositions
        assert "PRIME" in await value("graphs.PetersenGraph().modular_decomposition()[0]")

        # back_circulant, isotopism, bitrade -- sage.combinat.matrices
        assert await value("hadamard_matrix(8).nrows()") == "8"
        assert await value("bool(hadamard_matrix(8).det().abs() == 8^4)") == "True"
        assert await value(
            "len(designs.mutually_orthogonal_latin_squares(3, 4))"
        ) == "3"

        # schur_to_hl, riggings, compat -- sage.combinat.sf.kfpoly
        assert await value(
            "Sym = SymmetricFunctions(QQ)\nSym.schur()(Sym.homogeneous()[2,1])"
        ) == "s[2, 1] + s[3]"

        # CoxGroup -- sage.combinat.root_system
        assert await value("CoxeterGroup(['A', 3]).order()") == "24"

        # declare_ring -- sage.rings.polynomial.pbori
        assert await value("B.<a0, a1> = BooleanPolynomialRing()\n(a0*a1 + a0).degree()") == "2"

        # padic_relaxed_errors, genus, Sphere
        assert await value("Qp(5, 10)(25).valuation()") == "2"
        assert "Signature:  (2, 0)" in await value("IntegralLattice('A2').genus()")
        assert await value("bool(surfaces.Sphere() is not None)") == "True"
    finally:
        await session.shutdown()
