# Plan: the 2026-09 structural refactor

> **Status:** in progress on branch `refactor-2026-09`, one commit per step.
> The progress record at the bottom says what has been done, what went
> differently from this plan, and why.

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
