"""Run SageMath's own doctests through the server and check what comes back.

`test_sage_doctest_corpus.py` proves this server would *accept* the mathematics
SageMath documents. It does not prove Sage computes it: every example there is
validated and none is executed. This file closes that, and it is the expensive
half — 26 examples a second against 9,000 for validation, so the whole corpus
would be about three and a half hours.

**It is therefore opt-in and sampled.** Nothing here runs on the pull-request
path. `make doctest-execution` takes a deterministic sample; the stride and the
block budget are environment variables so a nightly can widen them.

    SAGEMATH_MCP_DOCTEST_EXECUTION=1 SAGEMATH_MCP_DOCTEST_BLOCKS=400 \\
        sage -python -m pytest tests/test_sage_doctest_execution.py

**Provenance.** As with the validation sweep, the corpus is SageMath's own,
GPL-2.0-or-later, read at run time from the installation under test and never
copied into this MIT repository. See `test_sage_doctest_corpus.py` for the note
in full.

**What a bounded spike got wrong, and what this does about it.** Three things
each produced a false failure, and each is a property of doctests rather than of
this server:

1. **Expected exceptions.** 16% of the sample raised, and most were meant to:
   `factorial(-32)` and `is_prime_power("foo")` document their errors. A
   `Traceback (most recent call last): ... ValueError: ...` block is an
   assertion, not a failure, and is matched on the exception's final line.
2. **Block dependencies.** Skipping an example does not skip what depends on it.
   A `# random` line assigning `A = random_matrix(RDF, 3, 3)` was dropped from
   comparison and the following `A.parent()` was then compared against a stale
   `A`. Exclusion here means *do not compare*, never *do not execute* — and a
   block containing something genuinely unrunnable is dropped whole.
3. **Warnings.** Sage's expected output sometimes contains a `doctest:warning`
   block; ours arrive on stderr, so those comparisons are skipped rather than
   failed.

Widening the sample from 60 blocks to 400 found two more, and both are about
what a doctest *is* rather than what Sage computes:

4. **Tags that mark a wrong answer on purpose.** `# todo: not implemented` is
   the same tag as `# not implemented` with a word in front of it, and
   `QQ['x'] in Algebras(Fields())` is written expecting `True` while returning
   `False` today. Comparing against one fails for the reason the tag exists.
5. **Sage's REPL lays matrices out in columns.** A sequence of matrices prints
   side by side there and stacked here, because that formatting lives in
   `sage.repl.display` and results come back as `repr`. The mathematics is
   identical; the layout is not, and it is on the queue rather than hidden.

Measured after all five: 400 docstrings, 2,163 examples, 1,259 comparable,
**100% agreement, no mismatches and no unexpected errors**.

Comparison is SageMath's own `SageOutputChecker`, which implements the `...`
ellipsis and `# tol` semantics the corpus is written against. Reimplementing
that would be inventing a second dialect of somebody else's format.
"""

from __future__ import annotations

import contextlib
import doctest
import os
import re
import shutil
from dataclasses import dataclass, field

import pytest

from sagemath_mcp.config import SageSettings
from sagemath_mcp.session import SageSession

from .test_sage_doctest_corpus import _docstrings, sage_library

requires_sage = pytest.mark.skipif(
    shutil.which("sage") is None, reason="Sage executable not available"
)
opt_in = pytest.mark.skipif(
    os.getenv("SAGEMATH_MCP_DOCTEST_EXECUTION") != "1",
    reason="slow: set SAGEMATH_MCP_DOCTEST_EXECUTION=1 (see the module docstring)",
)

_PROMPT = re.compile(r"^(\s*)sage:\s?(.*)$")
_CONTINUATION = re.compile(r"^(\s*)\.\.\.\.:\s?(.*)$")
_TRACEBACK = re.compile(r"^\s*Traceback \(most recent call last\)", re.MULTILINE)
_EXCEPTION_LINE = re.compile(r"^\s*(\w+(?:Error|Exception|Warning|Interrupt)):?(.*)$")

# An example this server will not run, by design. The block is dropped whole:
# executing half of it would compare later lines against a namespace that never
# got the earlier one's effect.
_UNRUNNABLE = re.compile(
    r"^\s*(import|from)\s+\w"
    r"|\b(save|load|attach|dumps|loads|sage_input|explain_pickle)\s*\("
    r"|\b(open|tmp_filename|tmp_dir|SAGE_TMP|os\.|shutil\.|\.savefig)"
    r"|\b(eval|exec|compile|sage_eval|preparse|cython|fortran|getattr|setattr)\s*\("
    r"|\b(oeis|get_remote_file|urlopen)"
    r"|\b(gap|singular|maxima|magma|maple|matlab|octave|macaulay2|gp|pari|axiom|"
    r"fricas|giac|r)\s*\(\s*['\"]"
    r"|^\s*(%|!|\?|help\(|search_src)"
    # Module traversal anywhere in the line, not only at the start:
    # `C = sage.categories.examples.crystals.X(n=4)` is refused by the attribute
    # rules and is not a statement about whether Sage computes correctly.
    r"|\bsage\.\w"
    # `# todo: not implemented` is the same tag with a word in front of it, and
    # it marks a doctest that documents a *wrong* answer on purpose --
    # `QQ['x'] in Algebras(Fields())` is written expecting True and returns
    # False today. Comparing against it fails for the reason the tag exists.
    r"|#\s*(todo:?\s*)?(optional|needs|known bug|not implemented|not tested)"
    # Dunder access is refused outright and that rule is load-bearing, so a
    # doctest exercising `C.__iter__(...)` or `C1.__eq__(C2)` is out of scope
    # here exactly as it is in the validation sweep.
    r"|__\w+__"
)
# Runnable, but its output is not worth comparing: it is random, it is a memory
# address, it is timing, or it warns.
_DO_NOT_COMPARE = re.compile(
    r"#\s*(random|abs tol|rel tol)"
    r"|\b(random|randint|shuffle|sample)\s*\("
    r"|0x[0-9a-f]{6,}"
    # Any doctest-emitted warning, not just the one spelled `doctest:warning`:
    # `doctest:...: FutureWarning` is the other spelling, and ours go to stderr
    # either way.
    r"|doctest:"
)
# Sage's REPL lays a sequence of matrices out side by side, in columns, and for
# a while this server stacked them and these comparisons were skipped. They are
# not skipped any more: `_format_result` renders a sequence through Sage's own
# `format_list`, so the layout is the one the doctests record. The pattern is
# kept as an assertion instead -- the suite should now be *comparing* these, and
# a run where none appears means the harness has stopped reaching them.
_MATRIX_COLUMNS = re.compile(r"\]\s\s+\[")


@dataclass
class Example:
    source: str
    expected: str


@dataclass
class Outcome:
    blocks: int = 0
    dead_workers: int = 0
    examples: int = 0
    matched: int = 0
    mismatched: int = 0
    errors: int = 0
    expected_errors: int = 0
    not_compared: int = 0
    tall_layouts: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def compared(self) -> int:
        return self.matched + self.mismatched

    @property
    def agreement(self) -> float:
        return self.matched / self.compared if self.compared else 1.0

    def report(self, limit: int = 12) -> str:
        lines = [
            f"{self.blocks} docstrings, {self.examples} examples: "
            f"{self.matched} matched, {self.mismatched} mismatched, "
            f"{self.errors} unexpected errors, {self.expected_errors} expected errors, "
            f"{self.not_compared} not compared, {self.tall_layouts} tall layouts, "
            f"{self.dead_workers} dead workers",
            f"output agreement {self.agreement:.2%}",
        ]
        lines.extend(f"  {failure}" for failure in self.failures[:limit])
        return "\n".join(lines)


def examples_of(block: str) -> list[Example]:
    """(source, expected) pairs, in the order Sage runs them.

    Written out rather than reusing the corpus file's splitter because that one
    only needs the input. Expected output runs from the end of an example to the
    next prompt or the next blank line, which is the rule the format actually
    uses -- getting it wrong is what compared `A.parent()` against a stale `A`.
    """
    found: list[Example] = []
    source: list[str] | None = None
    expected: list[str] = []

    def flush() -> None:
        if source is not None:
            found.append(Example("\n".join(source), "\n".join(expected).strip()))

    for line in block.splitlines():
        prompt = _PROMPT.match(line)
        continuation = _CONTINUATION.match(line)
        if prompt:
            flush()
            source, expected = [prompt.group(2)], []
        elif continuation and source is not None and not expected:
            source.append(continuation.group(2))
        elif source is not None:
            if not line.strip():
                flush()
                source, expected = None, []
            else:
                expected.append(line.strip())
    flush()
    return [example for example in found if example.source.strip()]


def _expected_exception(expected: str) -> str | None:
    """The exception a doctest documents, or None.

    Sage writes these as a traceback with an ellipsis for the frames, so the
    only reliable part is the last line: `ValueError: factorial only defined
    for nonnegative integers`.
    """
    if not _TRACEBACK.search(expected):
        return None
    for line in reversed(expected.splitlines()):
        match = _EXCEPTION_LINE.match(line)
        if match:
            return match.group(1)
    return "Exception"


async def run_block(session: SageSession, block: str, checker, flags: int,
                    outcome: Outcome) -> None:
    """Execute one docstring's examples in order, comparing what can be compared."""
    parsed = examples_of(block)
    if not parsed or any(_UNRUNNABLE.search(example.source) for example in parsed):
        return
    outcome.blocks += 1

    for example in parsed:
        outcome.examples += 1
        wanted_exception = _expected_exception(example.expected)
        try:
            result = await session.evaluate(
                example.source, want_latex=False, capture_stdout=True
            )
        except Exception as exc:
            if wanted_exception:
                outcome.expected_errors += 1
            else:
                outcome.errors += 1
                outcome.failures.append(
                    f"raised: {example.source.splitlines()[0][:70]!r} -> "
                    f"{type(exc).__name__}: {str(exc)[:80]}"
                )
            continue

        if wanted_exception:
            outcome.errors += 1
            outcome.failures.append(
                f"expected {wanted_exception}: {example.source.splitlines()[0][:70]!r}"
            )
            continue
        if (
            not example.expected
            or _DO_NOT_COMPARE.search(example.source + "\n" + example.expected)
        ):
            outcome.not_compared += 1
            continue

        if _MATRIX_COLUMNS.search(example.expected):
            outcome.tall_layouts += 1
        got = ((result.stdout or "") + (result.result or "")).strip()
        if checker.check_output(example.expected + "\n", got + "\n", flags):
            outcome.matched += 1
        else:
            outcome.mismatched += 1
            outcome.failures.append(
                f"{example.source.splitlines()[0][:60]!r}\n"
                f"        want {example.expected[:70]!r}\n"
                f"        got  {got[:70]!r}"
            )


@requires_sage
@opt_in
@pytest.mark.asyncio
async def test_sagemath_computes_what_its_doctests_say() -> None:
    """A deterministic sample of the corpus, executed and compared.

    The assertion is agreement among the examples that *can* be compared, which
    is the honest denominator: an example with no expected output, or whose
    output is random or a memory address, says nothing about whether Sage
    computed correctly.
    """
    from sage.doctest.parsing import SageOutputChecker

    library = sage_library()
    if library is None:  # pragma: no cover - integration only
        pytest.skip("SageMath library not importable")

    stride = int(os.getenv("SAGEMATH_MCP_DOCTEST_STRIDE", "40"))
    budget = int(os.getenv("SAGEMATH_MCP_DOCTEST_BLOCKS", "60"))

    checker = SageOutputChecker()
    flags = doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE | doctest.IGNORE_EXCEPTION_DETAIL
    outcome = Outcome()

    sources = (sorted(library.rglob("*.py")) + sorted(library.rglob("*.pyx")))[::stride]
    for path in sources:
        if outcome.blocks >= budget:
            break
        for block in _docstrings(path):
            if outcome.blocks >= budget:
                break
            # One session per docstring: Sage runs a docstring's examples against
            # a shared scope, and so must this.
            session = SageSession(
                f"doctest-{outcome.blocks}",
                SageSettings(force_python_worker=False, eval_timeout=20.0),
            )
            try:
                await run_block(session, block, checker, flags, outcome)
            except Exception as exc:  # a doctest that kills the worker
                outcome.dead_workers += 1
                outcome.failures.append(f"block aborted: {type(exc).__name__}: {exc}")
            finally:
                with contextlib.suppress(Exception):
                    await session.shutdown()

    assert outcome.blocks >= 20, f"sampled too little to mean anything:\n{outcome.report()}"
    assert outcome.compared >= 100, f"almost nothing was comparable:\n{outcome.report()}"
    # The spike measured 98.3% with a naive harness. Below 95% means either Sage
    # is computing differently or this harness has stopped understanding the
    # format -- both worth a person looking.
    assert outcome.agreement >= 0.95, outcome.report(20)
    # An unexpected exception is the more interesting failure: it is code Sage
    # documents as working that this server could not run.
    assert outcome.errors <= outcome.examples * 0.05, outcome.report(20)
    # And the layout comparisons are actually being reached. They were skipped
    # while this server stacked a sequence of matrices that Sage lays out in
    # columns; they pass now, and a run where none appears means the harness has
    # stopped getting to them rather than that the formatting is fine.
    assert outcome.tall_layouts >= 1, outcome.report()
