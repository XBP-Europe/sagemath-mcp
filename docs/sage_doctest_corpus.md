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
| `test_this_server_accepts_the_mathematics_sagemath_documents` | the headline acceptance ratio, ≥ 97.5% |
| `test_every_refusal_is_a_rule_we_meant_to_write` | no refusal may come from a rule that is not named and capped in the file |
| `test_the_shadowing_rules_stay_emptied` | the three rules item 46 emptied of the shadowing class stay empty of it |
| `test_the_blocked_interfaces_do_not_block_the_mathematics` | every scrubbed CAS interface's computation is still reachable in-process |

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
accepted 368,401   refused 6,027   out of scope 58,268
acceptance among in-scope examples: 98.39%
```

The first measurement was 97.81%, with 8,218 refusals. Categorising those
(below) found four that had no security justification; fixing them removed
2,191 refusals and added two names to the allowlist.

Out of scope means the example uses a capability this server does not offer:
imports (19,149), examples tagged `# optional`/`# needs` (30,219), persistence,
file paths, external CAS interfaces, `%` magics, network, and dunder protocol
calls. Those are classified and counted, never asserted over.

Of the original 8,218 refusals: 35.8% had a strong security justification, 29.4%
were not this server's doing (names the doctest created at run time), and **a
third had no strong justification**. Those four — `latex`, the
forbidden-global-shadows-a-local class, `operator.le`, and the REPL's `_` — were
fixed under REVIEW_ACTIONS.md items 45 and 46. What remains in those buckets is
deliberate: `vars`, `locals`, `input` and `eval` stay refused as identifiers
because they are the Python evaluation primitives, at a measured cost of about
30 examples in 432,878.

The most important negative result: **no mathematical name is missing from the
allowlist anywhere in the corpus.** Every name refused as "not offered" is an
external CAS interface, REPL plumbing, or a name the doctest invented.

## What is not built yet

**Executing the corpus and comparing output.** The validation sweep proves the
server would *accept* Sage's mathematics; it does not prove Sage computes it.
A bounded spike over 979 examples measured:

- **26.5 examples/second** — 350× slower than validation, so the full corpus is
  about 3.5 hours. This is a sampled nightly job, never a PR test.
- **98.3% output agreement** using SageMath's own `SageOutputChecker`, which is
  the right comparator: it implements the `...` ellipsis and `# tol` semantics
  that Sage's doctests are written against.

Three things the spike showed a real harness would need, each of which caused a
false failure:

1. **Expected exceptions.** 16% of the sample raised, and most were doctests that
   are *supposed* to — `factorial(-32)`, `is_prime_power("foo")`. The
   `Traceback (most recent call last): ... ValueError: ...` block has to be
   parsed and asserted, not treated as an error.
2. **Block dependencies.** Skipping an example does not skip what depends on it.
   A `# random`-tagged `A = random_matrix(RDF, 3, 3)` was excluded from
   comparison and the following `A.parent()` was then compared against a stale
   `A`. Exclusion has to mean *do not compare*, not *do not execute* — except for
   the genuinely unrunnable, where the whole block must be dropped.
3. **Warnings.** Sage's expected output sometimes contains a `doctest:warning`
   block; ours arrive on stderr.

**Cython sources beyond docstring extraction.** `.pyx` docstrings are found by
their quotes rather than by parsing, which is coarser than the AST path used for
`.py`. It has been adequate — the `.pyx` files contribute ~98,000 examples and
their refusal profile matches the `.py` files — but a nested `"""` inside a
docstring would silently truncate a block.
