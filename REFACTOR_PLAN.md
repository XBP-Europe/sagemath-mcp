# Plan: the 2026-09 structural refactor

> **Status: done, 2026-09-27**, on branch `refactor-2026-09`, one commit per
> step. The progress record at the bottom says what was done, what went
> differently from this plan, and why; the outcome is summarised at the end.

The `server.py` split (PR #38, recorded in `REFACTOR_SERVER_SPLIT.md`) left the
tool modules in good shape but moved the weight elsewhere. Measured on
2026-09-27 at `fdf7cc8`, with no open functional work:

| Target | Size | Problem |
|---|---|---|
| `security.validate_module` | 577 lines, ~104 branches | One 450-line `for node in ast.walk(module)` with 13 `if isinstance(...)` rules in a row |
| `tools/verify.py` `verify_claim` | 522 lines | 440 of them are one f-string of Sage code: not linted, not covered, not highlighted |
| `session.py` | 1,205 lines | `SageSession` (662) mixes process lifecycle, the stdout protocol and journal persistence; `SageSessionManager` (435) mixes scope/alias keys with the warm pool |
| `_sage_worker.py` | 1,443 lines | Namespace scrubbing (~600), result formatting, code splitting and the I/O protocol in one file |
| `codegen.py` | 842 lines | Security gates beside numeric helpers and two stats-only helpers; other modules import 35 of its `_private` names, so they are its API |
| Tool boilerplate | 40 context guards, 32 `resolve_session(client_scope(...))` | One identity rule, copied everywhere |
| `tests/test_server.py` | 2,490 lines | Every tool domain in one test file, while the source is split by domain |

**Goal:** each module one job, no function holding a whole subsystem.
**Non-goal:** behaviour. Every step is a move or an extraction. A test may be
edited only because a name moved, never because a result changed.

## Why it can be done safely

`validate_module` decomposes cleanly. All 13 rules in the node loop are pure
checks -- each raises or passes, none mutates shared state -- and they read a
small fixed context (`policy`, `bound`, `exempt_module_names`, `assigned_here`,
`called_names`, `injects_names`). The `continue`s inside the attribute rule
belong to its inner loop over chain segments, not the node loop. So an ordered
table of rule functions, applied per node in the same order over the same
single walk, yields the same first refusal for every input.

**The hazard is patching.** 44 tests `monkeypatch.setattr` a module attribute.
If a name moves and the old module re-exports it, the patch lands on the
re-export and silently stops affecting the code under test: green, testing
nothing. So moved names are **not** re-exported inside the package -- a stale
patch target then fails loudly with `AttributeError` -- and call sites are
retargeted, as the server split did for its 37.

## Oracles (step 0)

Three mechanical answers to "did anything change?", in place before anything
moves:

1. **Tool contract** -- `tests/test_tool_inventory.py` (exists): every tool
   name, schema and description.
2. **Generated code** -- `tests/test_generated_code_golden.py` (new): the exact
   Sage code, and trusted flag, every Sage-backed tool sends for 139 cases
   covering every tool and every operation. Pinned in
   `tests/fixtures/generated_code.txt`.
3. **Validator verdicts** -- the corpus sweep now records a SHA-256 over every
   doctest example's outcome, refusal messages in full, in
   `doctest-corpus-stats.md`. Baseline on SageMath 10.9:
   `ff2631d8fabe180a71490e2d0b933226851a37e57c0f7a4c7d0e9697ec85e265`,
   identical over two runs. Per-rule counts can stay equal while verdicts trade
   places; this cannot.

Plus the standing gates on every step: 100% statement and branch coverage,
`make lint`, `make test`, and for the steps touching the validator or the
worker, the integration suite in the Sage container.

## Steps

0. **Oracles** -- as above, plus this document.
1. **`runtime.session_for(ctx, name)`** -- the context guard and session
   resolution as one helper; the 40 copies go. Messages byte-identical.
2. **The verify ladder becomes a file** -- the 430 static lines of Sage move to
   `src/sagemath_mcp/sage_code/verify_ladder.py`, loaded as text behind a data
   header built from `_encode_literal`. Ruff lints it; the `^` lint covers it.
   Generated code byte-identical by oracle 2.
3. **Split `codegen.py`** -- `gates.py` (validation gates, now public names:
   `encode_literal`, `validated_expression`, `validated_identifier`, ...),
   `numeric.py` (exact integers, matrices, large ints), `transport.py`
   (`evaluate_structured`, result reconstruction, the prelude). The
   distribution helpers move to `tools/stats.py`.
4. **`security.py`**, in two commits:
   - **4a** move only -- `policy.py` (`SecurityPolicy`, env helpers,
     `trusted_policy`), `refusals.py` (message and spelling tables),
     `imports.py` (`rewrite_permitted_imports`).
   - **4b** `validate_module` becomes a pre-pass building a frozen
     `_ValidationContext` and an ordered tuple of 13 named rule functions.
     Every security comment moves verbatim with its rule. Gates: identical
     corpus fingerprint, full security and property suites, integration.
5. **`session.py`** -- `journal.py` (persistence), `_WorkerChannel` (stdout
   pump, framed-response matching), `WarmPool` (pre-started workers).
6. **The worker becomes a package** -- `worker/` with `scrub`, `format`,
   `split`, `protocol`; `_sage_worker.py` stays the thin entry point, so the
   launch command `-m sagemath_mcp._sage_worker` is unchanged.
7. **Tests mirror the source** -- `test_server.py` becomes
   `tests/tools/test_<domain>.py`. Moves only; the collected count is
   unchanged.
8. **Docs** -- the `CLAUDE.md` architecture section, and this record.

## Deliberately out of scope

- The generated `allowlist*.py` and `star_exports*.py`.
- `SecurityPolicy` defaults, and every tool name, schema and description.
- `test_security_bypass.py`: organised by review item, it is the audit trail.
- Unifying the `*_operation` tools behind `Literal` types. That changes the
  schemas, which is a contract change, not a refactor.

## Progress record

- **Delivery changed:** planned as one PR per step, done as one branch with one
  commit per step, each verified before the next began, and a single PR at the
  end. Every step builds on the one before, and stacked PRs have silently
  merged into each other here before (#118 into #119).
- **Step 0** -- done. 139 golden cases, 1 of them a pinned refusal (Poisson has
  no quantile). Fingerprint baseline as above.
- **Step 1** -- done. 39 guards and 32 lookups replaced; the guard stays where
  it stood rather than merging into the lookup, because validation runs between
  the two in most tools and merging would change which error a bad call gets
  first. The `list_sage_sessions` resource keeps its own guard: it answers `[]`.
- **Step 2** -- done, byte-identical on the first try. Different from the plan:
  the Sage globals the ladder reads are bound to placeholders *above* the marker
  line rather than F821 being switched off, so ruff still catches a typo in the
  ladder; only B018 (the deliberate final bare expression) is ignored. Two new
  lint tests: no XOR operator in `sage_code/*.py` (checked to fail on a planted
  `^`), and exactly one marker per file. Wheel and sdist both carry the file.
- **Step 3** -- done. `codegen.py` is gone: `gates.py`, `numeric.py`,
  `transport.py` and, different from the plan, a fourth module `prelude.py` --
  the prelude is not transport. Names imported across modules dropped their
  underscore (12, plus `EXACT_JSON_INT_LIMIT`, which `transport` needs from
  `numeric`); helpers used only at home kept theirs. The distribution helpers
  moved into `tools/stats.py`, where the helper-interpolation guard saw their
  f-strings for the first time; both interpolate only into a `ToolError`, and
  are now in its reviewed table with that reason. The fuzz workflow triggers
  on `gates.py`. Golden code unchanged; corpus fingerprint unchanged;
  integration 1485 passed.
- **Step 4a** -- done. `security.py` 1,706 -> 962 lines; `policy.py` (455),
  `refusals.py` (189), `imports.py` (147). `LOGGER` stayed, so the logger name
  `sagemath_mcp.security` is unchanged. Two hard-coded file lists had to follow
  the move, and both would have gone quietly wrong rather than red forever:
  `test_docs_settings` looks for environment reads in named files (they are in
  `policy.py` now), and the mutation config scoped `security.py` alone, which
  would have dropped the moved logic from the score. The fuzz workflow triggers
  on all four. One slip on the way: the first run of the migration script's
  import regrouping ate the name after a `# noqa` inside a parenthesised import;
  ruff caught it as undefined names, the step was reverted and re-run.
  Fingerprint unchanged; integration 1485 passed; both fuzz campaigns clean.
- **Step 4b** -- done. `validate_module` is a pre-pass, a frozen
  `_ValidationContext` and 13 rule functions registered by node type in
  `_NODE_RULES`. Different from the plan: dispatch is by node type rather than
  every rule on every node -- same rules, same order per node, cheaper -- which
  made each rule's leading `isinstance` unreachable, so those clauses went. One
  comment was attached to the wrong block (the note on forbidden references sat
  above the `del` rule inserted between it and its rule) and now heads its rule.
  Fingerprint unchanged. **Mutation:** 63.73% (499/783) before, 62.24%
  (488/784) after. No earlier mutant changed outcome; all 12 new survivors were
  on new lines and equivalent as tested (11 on a string annotation's `|`, one on
  `frozen=True`). A follow-up commit kills them with two tests that pin real
  invariants, each checked by planting the mutation.
- **Step 5** -- done, reshaped. Planned as three extractions; done as
  `journal.py` (`JournalMixin`), `channel.py` (`WorkerChannelMixin`),
  `errors.py`, and the whole manager moved to `manager.py`. Mixins rather than
  composition, because tests and tools call `session.save_journal()`,
  `manager.warm_up()` and the rest directly, and a mixin keeps every name on
  `self`. The warm pool stayed inside the manager rather than becoming a third
  mixin: it constructs `SageSession`, so as a mixin imported by `session.py` it
  would have needed an import inside the function. The mixins and the manager log
  under `sagemath_mcp.session`, as before. One slip: the import-retargeting
  script excluded files *named* `session.py`, which skipped `tools/session.py`;
  collection failed at once and it was fixed. Integration 1487 passed.
- **Step 6** -- done, narrowed. Planned as a `worker/` package; done as one
  extraction, `scrub_catalog.py` (502 lines: the danger modules, the bare
  names, the baked denylist, and the derivation and star-export screen). The
  rest stays in `_sage_worker.py` (1,443 -> 962 lines), because it is held
  together by module state: `PURE_PYTHON` is patched on `_sage_worker` in 24
  tests, `_STARTUP_ERROR`, `_WITHHELD_NAMES` and `_PROTOCOL` are rebound with
  `global`, and `_latex` is patched and called from `_execute`. Spread over
  modules, each would need every read made late-bound and every patch
  retargeted -- the silent-patch hazard at its worst. The catalog reads none of
  that. Even so, the hazard surfaced once: four tests assign the catalog lists on
  the module to change what the worker strips, and the worker had imported them
  by value. It failed red; the worker now reads `scrub_catalog.<list>` at call
  time. `make denylist` writes to the catalog now and was run end to end: it
  finds its block. Its derivation drops one name the baked list carries,
  `interfaces` -- the untouched pre-refactor code derives the same 258, so that
  is pre-existing, and the list was left as it was. Fingerprint unchanged;
  integration 1487 passed.
- **Step 7** -- done. `tests/test_server.py` (2,490 lines, 188 tests) is now
  `tests/tools/test_<domain>.py` for the seven tool modules, `tests/stubs.py`
  for the shared `StubSession`/`_stub_manager`, the transport and numeric unit
  tests in `test_codegen.py` beside the other tests of those modules, and 9
  server-level tests left in `test_server.py`. Proof: the multiset of (test
  name, outcome) is identical before and after over all 1,496 tests, and Sage
  collects the same 1,496. Two things only a careful look found: two discrete
  tests call their tool through `getattr(server, tool)`, invisible to the
  classifier, and were moved by hand; and `test_every_documented_example_is_
  exercised` read `tests/test_*.py` non-recursively, so it had stopped seeing the
  moved tool tests while still passing -- it uses `rglob` now.
- **Step 8** -- done. `CLAUDE.md`'s architecture section, `AGENTS.md`,
  `TESTING.md`, `SECURITY.md`'s layer table and the README diagram describe the
  new layout; the README's request flow also named a method that does not exist
  (`get_or_create`; it is `get`). CHANGELOG has an Unreleased entry. Historical
  records -- CHANGELOG entries, REVIEW_ACTIONS, the security-review report --
  keep the paths they were written against.

## Outcome

| Measure | Before (`fdf7cc8`) | After |
|---|---|---|
| Largest function | `validate_module`, 577 lines, ~104 branches | `validate_module`, 146 lines, 23 |
| `verify_claim` | 522 lines, 440 of them an f-string | 91 lines; the ladder is linted source |
| Largest module | `security.py`, 1,706 lines | `security.py`, 1,110 |
| `session.py` | 1,205 lines | 397 (+ `manager.py` 480, `journal.py` 210, `channel.py` 185) |
| `_sage_worker.py` | 1,443 lines | 962 (+ `scrub_catalog.py` 502) |
| `codegen.py` | 842 lines | gone: `gates` 424, `numeric` 98, `transport` 158, `prelude` 124 |
| `tests/test_server.py` | 2,490 lines, 188 tests | 9 server tests; 179 in `tests/tools/` and `test_codegen.py` |
| Tests collected | 1,492 | 1,496 (+4 guards: two lint, rule registration, frozen context) |
| Corpus fingerprint | `ff2631d8...` | `ff2631d8...`, at every step |

Every step kept 100% statement and branch coverage, the tool inventory and the
generated-code golden file byte-identical, and passed the integration suite in
the SageMath 10.9 container.

## Left as found, on purpose

- **The `interfaces` entry in the baked denylist.** The derivation no longer
  produces it, and the pre-refactor code agrees. Stripping an extra name is the
  safe direction; dropping it is a security decision, not a refactor.
- **Cross-module imports of private names that did not move** -- `gates` and
  the worker read `security._bound_names`, `prelude` reads `_SYMBOL_SHAPE` and
  `_GREEK_NAMES`. Renaming them was not needed for any step, and each is a
  one-line change when it is.
- **The rest of the worker**, for the module-state reasons in step 6.
- **`star_export_screen`, `dangerous_sage_names`, `rewrite_permitted_imports`
  and `_execute`** are the largest functions now (114-146 lines). None is a
  loop of independent rules the way `validate_module` was, so no mechanical
  argument makes splitting them provably safe; each would need its own case.

