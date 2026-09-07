# Roadmap

This document tracks planned improvements to the SageMath MCP server, organized by priority and effort. The goal is to strengthen the server's position as a universal mathematics MCP server that enables LLMs to perform any symbolic or discrete mathematical operation.

**Current state (last release v0.6.1; the work below is on `main`, unreleased):**
40 MCP tools (33 Sage-backed, 7 infrastructure) covering calculus, algebra,
linear algebra, ODEs, number theory, combinatorics, graph theory, group theory,
elliptic curves, coding theory, boolean algebra, polynomial rings, geometry,
probability, vector calculus, statistics, 2D/3D plotting, numeric root-finding,
claim verification (`verify_claim`), incremental streaming, an MCP-level health
probe and a documentation lookup. As of 2026-09-06 the suites pass ~977 unit
tests at 100% statement and branch coverage, over 1,130 collected against a real
SageMath 10.9 runtime, and the extended CLI cases across Claude, Gemini and Codex
(run locally; the keys are deliberately not in CI). Counts are a snapshot; the
coverage floor is the part CI enforces. Every tool carries MCP annotations
(`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`), pinned by an
inventory test.

Integration coverage now includes every tool exercised against the examples in its own
documentation, and a syntax matrix over the input spellings each tool must accept. Both
run in CI, which had previously reported the integration job as passing while running
nothing at all.

**Caller code moved to deny-by-default in this window.** A name is refused unless
the generated allowlist offers it or the caller's own code bound it. That closed
a run of bypasses which shared one shape — a name nobody had thought to forbid —
and it changes what callers may do: no imports, no external CAS interfaces, no
`show`/`latex`/`html`, and `x, y, z, t` predefined where Sage predefines only
`x`. See `SECURITY.md` for the model and `CHANGELOG.md` for the breaking
details. It also created a new risk in the opposite direction — refusing
legitimate mathematics — which `tests/test_math_coverage.py` exists to catch.

---

## Open work

The live queue is [TODO.md](TODO.md); this section says only what shape it is in.

The 2026-08-13 review and the security rounds that followed are all recorded in
[REVIEW_ACTIONS.md](REVIEW_ACTIONS.md) — 34 items, each with its reproduction,
fix and regression test. All are closed; item 7's distribution half resolved on
2026-08-24 (below).

**The 2026-09-06 external review is fully worked through** (two rounds, merged in
PR #61). Every concrete finding is closed, each with a regression test; the
details are in [CHANGELOG.md](CHANGELOG.md) under *Unreleased*. What it produced:

- **`verify_claim`** shipped, then hardened for soundness after the second round —
  it never labels approximate arithmetic or an out-of-domain sample as an exact
  result (see the field-survey item below).
- **Portable workspace handles.** `start_sage_session` issues an unguessable
  bearer `workspace_token` that addresses one workspace independently of the
  transport-level MCP session id — the direction the 2026-07-28 MCP spec's
  retirement of protocol-level sessions points to. This closes the last of the
  session-ergonomics gap the survey called out. Names keep transport-scoped
  isolation; the fastmcp cap (below) stays until handles are validated over real
  transports.
- **fastmcp pinned `>=3.4.7,<4`** — 4.0.3 breaks cross-client session isolation
  (REVIEW_ACTIONS item 68). A fresh install otherwise resolves it.
- **Session/worker robustness** — serialized worker startup (no double-launch
  race), a configurable session ceiling, helper-tool evaluations now counted in
  the metrics, and a real `/ready` probe that evaluates `1+1` on the backend.
- **Release & onboarding** — every publish gated on a tag *push* (a dry-run
  dispatch could reach PyPI), the release publishes the exact image its smoke
  test verified, the README `docker run` carries the Compose hardening on
  loopback, and the dev-container scripts pin the Dockerfile's Sage tag.
- **Honest scope docs** — "full access / run any SageMath code" replaced with the
  deny-by-default subset, and the specialized-tools-use-a-fresh-namespace
  semantics surfaced where the model reads them.

One non-blocking note from the review remains open, tracked in TODO.md: the
verifier trusts Sage's own evaluation semantics for the exact-comparison rung,
which the 0.7.0 release is the natural point to revisit before shipping.

Distribution is settled: the server is listed on the **official MCP registry**
(`io.github.XBP-Europe/sagemath-mcp`, published by the release pipeline) and on
**Glama** (claimed as XBP-Europe via `glama.json`, #50). **Smithery is not
pursued** — since its Arcade.dev acquisition, `smithery.ai/new` publishes only a
public HTTPS endpoint, so listing would require hosting a public, authenticated
code-execution endpoint with a Sage runtime, against the local-only, no-auth
posture in `SECURITY.md`. `smithery.yaml` was removed as dead config.

## Letting more legitimate mathematics through (measured 2026-08-15)

Running SageMath's own doctests through the validator — 432,878 examples,
`tests/test_sage_doctest_corpus.py` — accepts 98.59% of what is in scope. The
5,266 refusals were categorised by whether the security justification holds
(REVIEW_ACTIONS.md items 45 and 46), and everything that failed that test has
been fixed.

What remains is that breakdown read the other way round: not *is this refusal
justified* but *what would it take for this mathematics to work?* Five items
came out of it, each with the count that motivates it and each reproduced
against SageMath 10.9, and all six are done: `nonlocal` and `global`, room for a
pasted matrix, refusal messages that name the spelling which works, run-time
names from `inject_variables()`, and executing the corpus rather than only
validating it. That last one measured **100% agreement** with the output
SageMath's doctests document, over 1,259 comparable examples in a 400-docstring
sample. It surfaced one more thing on the way, now also fixed: Sage's REPL lays
a sequence of matrices out in columns where this server stacked them, so a basis
of eight 3x3 matrices arrived as 32 lines instead of 4. That queue is empty.

Deliberately *not* among them: the external CAS interfaces (2,153 refusals),
whose mathematics is reachable in-process and tested to be; the 538 uses of
Sage's internal spellings for mathematics that has a public one; and the
evaluation primitives, which stay refused whatever the namespace holds. Those
are boundaries, not gaps.

## Competitive position (surveyed 2026-08-13)

> The numbers below are the 2026-08-13 snapshot (this project at 37 tools, 12
> stars). The **2026-08-24 field survey and code read** above supersede it: the
> tool surface is now 39, and the "behind" items were revisited against the
> peers' actual source. Kept as the dated baseline it was measured as.

### The SageMath MCP field

| Project | Stars | Language | Tools | Session model | Last push |
|---------|------:|----------|------:|---------------|-----------|
| **this project** | **12** | Python | **37** | Subprocess per client, named workspaces, interrupt | active |
| [GaloisHLee/mcp-server-sagemath](https://github.com/GaloisHLee/mcp-server-sagemath) | 11 | TypeScript | 3 | Explicitly stateless | 2025-12 |
| [sanshanjianke/scicompute-mcp](https://github.com/sanshanjianke/scicompute-mcp) | 4 | Python | multi-backend | Persistent | 2026-04 |
| [justice8096/sagemath-mcp-server](https://github.com/justice8096/sagemath-mcp-server) | 1 | — | 10 | — | 2026-05 |
| [szeider/mcp-sage](https://github.com/szeider/mcp-sage) | 1 | Python | 5 | Jupyter kernel, named multi-session | 2026-08 |

The adjacent market is roughly five times larger and is where attention actually goes:
[mcp-wolframalpha](https://github.com/akalaric/mcp-wolframalpha) (84),
[sympy-mcp](https://github.com/sdiehl/sympy-mcp) (79),
[wolframalpha-llm-mcp](https://github.com/Garoth/wolframalpha-llm-mcp) (55),
[mathematica-mcp](https://github.com/AbhiRawat4841/mathematica-mcp) (44),
[fermat-mcp](https://github.com/abhiphile/fermat-mcp) (20).

### Where this project leads

- **Security posture under repair.** The configurable AST validator is useful
  defence in depth against accidental misuse, but review items 1-3 show that it
  is not currently an adversarial sandbox. Do not treat sandboxing as a competitive
  differentiator until the bypass tests and container hardening are complete.
- **Tool surface.** 37 against 3, 5 and 10 for the SageMath peers.
- **Verification.** 496 unit and 575 real-runtime tests (2026-08-14); peer test coverage is largely
  invisible.
- **Documentation.** 1218 README lines against 481, 284, 187 and 89.
- **Operations.** Helm chart, Cosign-signed images, monitoring resource, health endpoint.
  No peer ships this.
- **Distribution.** On PyPI with signed releases. Notably sympy-mcp, the most-starred
  symbolic server, is not on PyPI at all.

### Where this project is behind

1. **Worker transport.** szeider/mcp-sage drives Sage through the Jupyter kernel
   protocol rather than raw subprocess management, citing "reliable prompt detection,
   clean separation of stdout / stderr / return values, native interrupt support, and
   robust multi-line input". Those are precisely the problems this project solved by
   hand, and a framing bug in that hand-rolled layer surfaced as recently as v0.4.0.
   The 2026-08-24 code read (below) confirmed the trade-off is real but their side
   is not free: that server has no preparser (`2^3` is XOR there), drops rich
   output, and does not interrupt on timeout. The hand-rolled layer was hardened
   the same week — the worker now leads its own process group and the JSON protocol
   moved off descriptor 1, closing the descriptor-inheritance class the v0.4.0 bug
   belonged to.
2. ~~**Interrupt versus restart.**~~ Closed by `interrupt_sage_session`.
3. ~~**One session per client.**~~ Closed by `start` / `list` / `stop_sage_session`.
4. **Install friction.** `uvx mcp-sage` runs with no install via PEP 723 inline
   dependencies. This project needs a local SageMath or a ~3 GB image. A route is
   now on the roadmap (the passagemath runtime extra, below); the gap is real
   until it ships.
5. **Academic anchor.** Their server is cited in a NeSy 2026 paper. This project has no
   equivalent reference.

### Adopted from the field survey (2026-08-24)

Glama's related-servers set was compared feature-by-feature on 2026-08-24
(sympy-mcp, Axiom's Giac-in-WASM server, justice8096's Sage wrapper, math-mcp,
math-logic-mcp). Most of what they have and this project lacks is either the
point of their design (statelessness, small engines) or already decided against
here. Three features survived the filter — each makes sense for this server and
each has a mechanism, not just a wish — and a fourth resolved into
documentation rather than surface:

- [x] **`verify_claim` tool.** *Done, 2026-09-06.* Shipped as designed here
      (`tools/verify.py`): the claim passes the fragment gate every tool
      parameter passes (no new security surface), and the generated check climbs
      the ladder — Sage's symbolic prover, exact difference
      (`(lhs-rhs).simplify_full().is_zero()`), exact arithmetic over `QQbar`/`AA`
      when the claim is constant, then certified interval arithmetic and numeric
      sampling over the free variables — answering `proved`, `refuted`,
      `supported` (with sample count and precision) or `undecided`. Both honesty
      rules landed: the prover returning `False` is never reported as *false*
      (`refuted` requires an exact decision or an exhibited counterexample, with
      interval evidence always a certified enclosure), and `supported` always
      carries its evidence. The landing costs were paid: inventory snapshot,
      real-Sage ladder cases in `tests/test_verify.py`, and bypass tests that
      the claim string cannot reach anything the evaluate gate refuses. A second
      external-review round (2026-09-06) closed two soundness holes: a comparison
      over machine floats (`RR(1) + RR(1)/10^20 == RR(1)`) is now `supported` via
      a `float_comparison` method, never `proved` — the operands are inspected
      for exactness, decimal literals read as exact rationals — and a sampled
      counterexample can no longer fall outside a stated domain (`x != 1/2` under
      `assume(x, 'integer')` is not refuted at 1/2). Assumptions are named in the
      evidence of any verdict that relied on them.
- [x] **Outcome benchmarks.** *Done, 2026-09-07.* `benchmarks/` — a fixed,
      seeded case set (`cases.json`, 24 problems across five difficulty tiers,
      every gold answer verified in the Sage container) and a Workflow
      (`outcome_benchmark.workflow.js`) that runs it through the model twice,
      reasoning-only vs. with Sage compute, and scores every answer for
      mathematical equivalence in Sage by an independent step. Published to
      `benchmark-stats.md` and the README the way the corpus sweep writes
      `doctest-corpus-stats.md`. First run (subject `haiku`): **17/24 → 24/24**,
      the whole +7 in the compute-heavy/infeasible tiers, including one
      reasoning-only answer that was *confidently wrong* — the failure mode the
      server addresses. Never CI-gated: the number measures the model as much as
      the server. Follow-up remains to fold the fixed case set + a no-tools
      control into `tests/cli_integration` for the rigorous three-arm
      (no-tools / `evaluate_sage`-only / full-catalogue) version under the CLI
      nightlies, where real tool-gating and per-client keys live.
- [ ] **Passagemath runtime for install footprint.** "Where this project is
      behind" item 4 above. **Evaluated 2026-09-06**
      ([docs/passagemath_evaluation.md](docs/passagemath_evaluation.md), verified
      empirically): verdict **adopt, pinned to a verified release**, and the fit
      is better than this sketch assumed — `pip install passagemath-standard`
      yields a runtime where `from sage.all import *` works, `_sage_worker.py`
      runs unmodified, and all 33 Sage-backed tool domains pass on 10.8.9, at
      ~1 GB download / 3.8 GB disk / ~1 min versus the ~3 GB image. Two blockers
      before it ships: (1) the star-exports/denylist derivation is layout-
      sensitive and over-fires under the modular layout — the real engineering,
      ~1–2 days, and it overlaps the "classify rather than accept" allowlist item
      in TODO.md; (2) the full suite and doctest corpus sweep run against the pin.
      Don't track their latest release: 10.8.10/10.8.11 each shipped a broken core
      backend on Linux x86_64 (found in the evaluation, not their tracker), so an
      exact pin plus a cold-install smoke gate in CI, which folds their release
      risk into this project's existing engine-bump discipline. The priced-in cost
      is still the two artifact sets to review on every engine bump.
- [x] **Manifolds and GR: document, don't build.** *Done, 2026-08-24.* sympy-mcp's
      tensor/GR tools (Schwarzschild/Kerr metrics, Ricci/Einstein tensors) are its
      one breadth advantage, and Sage has the stronger machinery underneath
      (SageManifolds, including the metric catalog). The niche-domains decision
      below stands: no dedicated tool. Instead the gap closed at zero surface
      cost — a worked hyperbolic-plane GR example through `evaluate_sage` in
      `USAGE.md`, and `test_use_cases.py::test_use_cases_cover_the_sympy_mcp_showcase`
      pinning the curvature workflow (custom Lorentzian, hyperbolic plane, catalog
      sphere) end to end against real Sage.

Surveyed and *not* adopted: Axiom's stateless-HTTP scaling (statelessness is
their design, session state is this project's point), its CLI one-shot mode (a
different product), math-logic-mcp's Z3 layer (not Sage's instrument), and
justice8096's per-call process model (rejected here for cold-start cost from
the start).

### Shipped from the code-level read (2026-08-24)

A second pass the same day read each peer's source (not just its features). It
produced fixes and small features that are already merged, recorded here so the
roadmap reflects what the survey actually changed:

- **Worker process hygiene** (from szeider's GAP crash-loop guard and a
  transport-corruption bug in scicompute): the worker leads its own process
  group and every hard kill goes through `os.killpg`, so helpers Sage forks are
  reaped rather than orphaned; the JSON protocol moved off descriptor 1 so a
  forked child cannot corrupt the framing.
- **MCP tool annotations** (from justice8096): every tool declares
  `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`.
- **Coaching timeout message** (from szeider's model-directed error text): the
  timeout error names the retry — larger `timeout`, streaming, interrupt.
- **`check_sage_health`** (from GaloisHLee) and **`lookup_sage_doc`** (from
  scicompute's `doc` tool): an MCP-level readiness probe and a doc-URL lookup
  that also reports whether a name is offered to caller code.
- **Peer workloads as tests**: GaloisHLee's lattice workout (det/LLL/Hermite)
  and szeider's `structure_description()` GAP case, pinned in `test_use_cases.py`.

The still-open feature above — outcome benchmarks — plus the passagemath
runtime are what remain of the survey; `verify_claim` shipped 2026-09-06, and
portable workspace handles closed the session-ergonomics gap the same day.

---

## Explicitly not planned

**More domain tools.** At 40 the surface already exceeds every peer. The gaps that
matter are distribution and session ergonomics, not coverage — and session
ergonomics is now largely closed (named workspaces, interrupt, portable handles).
(`verify_claim` is not an exception to this: it is a checking primitive over
claims, not another slice of mathematical coverage.)

---

## Design notes worth remembering

Kept because each one cost a debugging session and none is obvious from the code.

- **`interrupt` deliberately does not take the session lock.** The evaluation
  being interrupted holds it, so waiting would deadlock until the computation
  everyone is trying to stop finishes on its own.
- **The worker's `except Exception` did not catch `KeyboardInterrupt`**, which is
  a `BaseException`. Without handling it explicitly the worker exited and took
  the namespace with it — defeating the point of interrupting rather than
  cancelling.
- **FastMCP's `mount`/`import_server` prefix tool names.** Composing the `tools/`
  package that way would rename every tool a client has configured, which is why
  the modules decorate against a shared `mcp` object instead.
- **Jupyter kernel transport was prototyped and rejected** (2026-08-13): stock
  ipykernel executes code the AST policy blocks, so it would need a permanent
  custom kernel, and startup cost 1010 ms against 463 ms. The measurements and
  the debugger finding are in
  [`prototypes/jupyter_transport/FINDINGS.md`](prototypes/jupyter_transport/FINDINGS.md).

## Niche domains — no further dedicated tools planned

These are reachable through `evaluate_sage`, which documents them in its own
description. Dedicated tools are not planned: the problems are too varied for a
single interface, or Sage is not the right instrument.

| Domain | Access via `evaluate_sage` | Why no dedicated tool |
|--------|---------------------------|----------------------|
| Tensor operations | Sage tensor module with index notation | Very specialized |
| Category theory | Limited Sage support | Out of Sage's scope |
| Unit conversion | External `units` package | Domain-specific |
| Curve fitting | Limited in Sage (scipy is better) | Wrong tool for the job |

Five domains that were once on this list — graph theory, group theory, elliptic
curves, coding theory and boolean algebra — did get dedicated tools
(`graph_operation`, `group_operation`, `elliptic_curve_operation`,
`coding_theory_operation`, `boolean_algebra_operation`).

## Completed work

Not listed here. Every shipped change is in [CHANGELOG.md](CHANGELOG.md) with
its release, and the reasoning behind the security work is in
[REVIEW_ACTIONS.md](REVIEW_ACTIONS.md). This file previously carried four
sections of ticked boxes that duplicated both and went stale — one of them still
listed five domains as having no dedicated tool when all five had shipped.
