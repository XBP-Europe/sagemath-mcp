# Roadmap

This document tracks planned improvements to the SageMath MCP server, organized by priority and effort. The goal is to strengthen the server's position as a universal mathematics MCP server that enables LLMs to perform any symbolic or discrete mathematical operation.

**Current state (v0.6.1):** 39 MCP tools (32 Sage-backed, 7 infrastructure) covering calculus, algebra, linear algebra, ODEs, number theory, combinatorics, graph theory, group theory, elliptic curves, coding theory, boolean algebra, polynomial rings, geometry, probability, vector calculus, statistics, 2D/3D plotting, numeric root-finding, incremental streaming, an MCP-level health probe and a documentation lookup. As of 2026-08-24 the suites pass 916 unit tests at 100% statement and branch coverage, over 1,000 collected against a real SageMath 10.9 runtime, and the extended CLI cases across Claude, Gemini and Codex. Counts are a snapshot; the coverage floor is the part CI enforces. Every tool carries MCP annotations (`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`), pinned by an inventory test.

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
fix and regression test. Every one is closed except the account-side half of
item 7: the Smithery and Glama submissions need repository-owner access.

- [ ] Smithery: their publish flow changed since this item was written — the current
      docs describe hosted-URL and MCPB-bundle publishing only, and no longer document
      the GitHub/`smithery.yaml` connect. Check smithery.ai/new for a legacy GitHub tab
      before choosing between hosting an HTTP endpoint and wrapping an MCPB bundle.
- [ ] Glama: `glama.json` naming the maintainers is merged (#50, the org-repo
      claiming route); the browser-side Claim flow on the listing is the remaining step.

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

- [ ] **`verify_claim` tool.** Axiom ships a `verify` tool with confidence
      scoring; nothing in the Sage field does. This is a checking primitive, not
      a domain tool, and it matches the dominant failure mode of models doing
      mathematics: confident wrong algebra. The model states a claim —
      `integral(x^2/(e^x-1), x, 0, oo) == 2*zeta(3)` — and the server re-checks
      it independently. Mechanism: the claim string passes the same preparse +
      AST validation as `evaluate_sage` (no new security surface); the generated
      check climbs a ladder — Sage's symbolic prover, exact difference
      (`(lhs-rhs).simplify_full().is_zero()`), exact arithmetic over `QQbar`/`AA`
      when the claim is constant, then high-precision numeric sampling over the
      free variables — and answers `proved`, `refuted`, `supported` (with sample
      count and precision), or `undecided`. Two rules keep it honest: the prover
      returning `False` means *not proved*, never *false* — `refuted` requires an
      exhibited counterexample evaluated exactly; and `supported` always carries
      its evidence, never a bare confidence number. Costs on landing: tool
      inventory snapshot, math-coverage cases, and bypass tests that the claim
      string cannot reach anything the evaluate gate refuses.
- [ ] **Outcome benchmarks.** Axiom publishes GSM8K / MATH accuracy deltas;
      this project's doctest corpus sweep proves the guardrails do not refuse
      mathematics, which is a different claim from "models get more answers
      right with these tools". The machinery is already here:
      `tests/cli_integration` drives Claude, Gemini and Codex against the live
      server with per-case validation. Add a benchmark case set (a fixed-seed
      subset of the MIT-licensed GSM8K and MATH datasets) and a no-tools control
      mode in the runner, emit the with/without scores to a stats file the way
      the corpus sweep writes `doctest-corpus-stats.md`, and publish the deltas
      in the README. Runs where the CLI nightlies run — never CI-gated, because
      the number measures the client model as much as the server.
- [ ] **Passagemath runtime for install footprint.** "Where this project is
      behind" item 4 above, now with a route: passagemath ships SageMath as
      modularized pip distributions, so `pip install "sagemath-mcp[passagemath]"`
      could stand up the 32 Sage-backed tools without the ~3 GB image or a local
      Sage build. The three generated artifacts (allowlist, star exports, baked
      denylist) are derived from *the installed Sage*, so the passagemath
      namespace needs its own reviewed set: generate both variants with the
      existing scripts, bake both, select by probing the runtime at worker start,
      and extend the weekly drift job to cover both. The open design cost is
      exactly that doubling — two artifact sets to review on every engine bump —
      and it is priced in, not discovered later.
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

The two still-open features above — `verify_claim` and outcome benchmarks — plus
the passagemath runtime are what remain of the survey.

---

## Explicitly not planned

**More domain tools.** At 37 the surface already exceeds every peer. The gaps that
matter are distribution and session ergonomics, not coverage. (`verify_claim` in the
field-survey section is not an exception to this: it is a checking primitive over
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
