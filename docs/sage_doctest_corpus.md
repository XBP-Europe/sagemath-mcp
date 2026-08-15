# SageMath's doctests as a syntax corpus

## Why

`test_math_coverage.py` is this project's counterweight to the security suite:
every test in `test_security_bypass.py` asserts something is *refused*, so a
policy that refused everything would pass all of them. The counterweight is a
hand-written table — roughly 19 preparser forms, 60 truths, 30 binding forms —
and it is therefore exactly as good as what somebody thought to type.

Two recent defects were forms nobody had typed. `f(x) = x^2 + 1` is the first
function definition in the Sage tutorial and it was refused for eight months,
because the preparser expands it through `__tmp__` and the dunder rule caught the
preparser's own scratch name. Nothing in 683 tests used the syntax.

SageMath's doctests are the largest body of idiomatic, known-correct Sage in
existence, written by the people who designed the language: **432,878 examples
across 3,168 source files** in 10.9. Running them through this server's
validator turns "did anyone think to test that spelling?" into a measurement.

## What is built

`tests/test_sage_doctest_corpus.py`, integration-only, 48 seconds.

It walks the installed SageMath library, extracts the `sage: ` examples from
every docstring (AST-parsed for `.py`, quote-delimited for `.pyx`), and pushes
each through `preparse` + `validate_module`. Examples are grouped **by
docstring**, and names bound by earlier examples authorise later reads — which
is what a session does, and without it ordinary code looks refused.

Five assertions:

| test | what it protects |
|---|---|
| `test_the_corpus_is_the_whole_library` | the harvest cannot silently evaporate: floors on files, docstrings, examples, and a ceiling on unparsable ones |
| `test_this_server_accepts_the_mathematics_sagemath_documents` | the headline acceptance ratio, ≥ 98.5% |
| `test_every_refusal_is_a_rule_we_meant_to_write` | no refusal may come from a rule that is not named and capped in the file |
| `test_the_shadowing_rules_stay_emptied` | the three rules item 46 emptied of the shadowing class stay empty of it |
| `test_the_blocked_interfaces_do_not_block_the_mathematics` | every scrubbed CAS interface's computation is still reachable in-process |
| `test_the_mathematics_behind_an_import_is_still_reachable` | the 138 mathematical names that live behind an import are reachable by their public spelling |
| `test_the_imports_that_change_nothing_are_dropped_at_scale` | the import rewrite still recognises the shapes it was written for — 1,840 of 19,191 dropped, 1,819 then running |

`scripts/analyse_doctest_refusals.py` categorises the refusals by whether the
security justification holds. It is a script rather than a test because its
output is a judgement to read, not a property to assert.

## Licensing and provenance

SageMath is Copyright (C) The Sage Development Team, licensed
**GPL-2.0-or-later**. This project is MIT.

The corpus is therefore **never vendored**. It is read at run time from the
SageMath installation the tests are running against, held in memory for the
duration of the sweep, and discarded. Only counts reach the assertions, which is
why every baseline in the file is a number rather than a list of snippets, and
why a failing assertion prints its examples instead of storing them.

- <https://www.sagemath.org/>
- <https://github.com/sagemath/sage>

A Sage upgrade moves the baselines. A *drop* in acceptance is the signal; refresh
by reading the report a failing assertion prints.

## What it measured (SageMath 10.9, 2026-08-15)

```
3,168 files, 60,094 docstrings, 432,878 examples
accepted 369,170   refused 5,258   out of scope 58,268
acceptance among in-scope examples: 98.60%
```

The first measurement was 97.81%, with 8,218 refusals. Categorising those
(below) found that a third had no security justification; fixing them removed
2,960 refusals — 36% — and added two names to the allowlist.

The acceptance ratio is **blind to the import rewrite by construction**: any
example containing an import is skipped before validation, so an import that is
now dropped never enters the count. Measured separately, 1,840 of the 19,191
examples containing an import have it dropped and 1,819 then run — the change
moves that number, not this one.

Out of scope means the example uses a capability this server does not offer:
imports (19,149), examples tagged `# optional`/`# needs` (30,219), persistence,
file paths, external CAS interfaces, `%` magics, network, and dunder protocol
calls. Those are classified and counted, never asserted over.

Of the original 8,218 refusals: 35.8% had a strong security justification, 29.4%
were not this server's doing (names the doctest created at run time), and **a
third had no strong justification**. Those four — `latex`, the
forbidden-global-shadows-a-local class, `operator.le`, and the REPL's `_` — were
fixed under REVIEW_ACTIONS.md items 45 and 46, along with five more found by
going through the remaining buckets by the same rule. What is left in those
buckets is five refusals in 432,878 examples — `open`, `exec`, `compile`,
`globals` and `getattr`, primitives with no mathematical use.

The most important negative result: **no mathematical name is missing from the
allowlist anywhere in the corpus.** Every name refused as "not offered" is an
external CAS interface, REPL plumbing, or a name the doctest invented.

## Executing it (`make doctest-execution`)

The validation sweep proves the server would *accept* Sage's mathematics; it
does not prove Sage computes it. `tests/test_sage_doctest_execution.py` closes
that, and it is the expensive half — 26 examples a second against 9,000, so the
whole corpus is about three and a half hours. It is therefore **opt-in and
sampled**, never on the pull-request path:

```bash
make doctest-execution                    # 60 docstrings, ~40s
BLOCKS=400 STRIDE=7 make doctest-execution   # a nightly's worth, ~7 minutes
```

Measured against SageMath 10.9: 400 docstrings, 2,163 examples, 1,279
comparable, **100% agreement, no mismatches and no unexpected errors**.

Comparison is SageMath's own `SageOutputChecker`, which implements the `...`
ellipsis and `# tol` semantics the corpus is written against; reimplementing it
would be inventing a second dialect of somebody else's format.

The denominator is the honest part. Of 2,163 examples, 869 are not compared —
they have no expected output, or their output is random, a memory address, a
warning, or Sage's column-aligned matrix layout. An example with nothing to
compare says nothing about whether Sage computed correctly, so counting it would
only flatter the number.

Five things a harness needs, each of which caused a false failure before it was
handled: expected exceptions (a `Traceback` block is an assertion), block
dependencies (exclusion means *do not compare*, never *do not execute*),
warnings, `# todo: not implemented` tags that mark a deliberately wrong answer,
and Sage's REPL matrix layout — which turned out to be a defect in this server
rather than a property of doctests, and was fixed: results now go through Sage's
own `format_list`, so those nine comparisons are made instead of skipped.

## What is not built yet

**Cython sources beyond docstring extraction.** `.pyx` docstrings are found by
their quotes rather than by parsing, which is coarser than the AST path used for
`.py`. It has been adequate — the `.pyx` files contribute ~98,000 examples and
their refusal profile matches the `.py` files — but a nested `"""` inside a
docstring would silently truncate a block.
